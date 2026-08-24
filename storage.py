from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "runtime_data"))
DB_PATH = DATA_DIR / "free_calendar.sqlite3"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY,start_date TEXT NOT NULL,title_key TEXT NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_date);
                CREATE INDEX IF NOT EXISTS idx_events_title ON events(title_key);
                CREATE TABLE IF NOT EXISTS signals (id TEXT PRIMARY KEY,source_id TEXT NOT NULL,title TEXT NOT NULL,excerpt TEXT NOT NULL,url TEXT NOT NULL,kind TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_signals_last_seen ON signals(last_seen DESC);
                CREATE TABLE IF NOT EXISTS source_status (source_id TEXT PRIMARY KEY,last_checked TEXT,last_success TEXT,status TEXT NOT NULL DEFAULT 'never',detail TEXT,events_found INTEGER NOT NULL DEFAULT 0,signals_found INTEGER NOT NULL DEFAULT 0);
            """)

    def seed_events(self, seed_path: Path):
        if not seed_path.exists(): return
        try: rows=json.loads(seed_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError,OSError): return
        for row in rows: self.upsert_event(row)

    @staticmethod
    def title_key(title: str) -> str:
        return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in title).split())

    def upsert_event(self,event:dict):
        event=dict(event); event_id=str(event.get("id") or "").strip()
        if not event_id or not event.get("start") or not event.get("title"): return False
        title_key=self.title_key(event["title"]); start_date=str(event["start"])[:10]
        with self.connect() as conn:
            existing=conn.execute("SELECT id,payload FROM events WHERE start_date=? AND title_key=? LIMIT 1",(start_date,title_key)).fetchone()
            if existing and existing["id"]!=event_id:
                old=json.loads(existing["payload"]); old_sources={(s.get("name"),s.get("url")):s for s in old.get("sources",[])}
                for source in event.get("sources",[]): old_sources[(source.get("name"),source.get("url"))]=source
                old["sources"]=list(old_sources.values())
                if len(event.get("description",""))>len(old.get("description","")): old["description"]=event.get("description")
                old["score"]=max(float(old.get("score",0)),float(event.get("score",0)))
                conn.execute("UPDATE events SET payload=?,updated_at=? WHERE id=?",(json.dumps(old,ensure_ascii=False),now_iso(),existing["id"])); return False
            conn.execute("INSERT INTO events(id,start_date,title_key,payload,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET start_date=excluded.start_date,title_key=excluded.title_key,payload=excluded.payload,updated_at=excluded.updated_at",(event_id,start_date,title_key,json.dumps(event,ensure_ascii=False),now_iso()))
        return True

    def list_events(self):
        # The calendar is a planning tool, not an archive. Never surface expired rows.
        today=datetime.now().astimezone().date().isoformat()
        with self.connect() as conn: rows=conn.execute("SELECT payload FROM events WHERE start_date>=? ORDER BY start_date,title_key",(today,)).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def upsert_signal(self,signal:dict):
        with self.connect() as conn:
            exists=conn.execute("SELECT id FROM signals WHERE id=?",(signal["id"],)).fetchone()
            conn.execute("INSERT INTO signals(id,source_id,title,excerpt,url,kind,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen,excerpt=excluded.excerpt,title=excluded.title",(signal["id"],signal["source_id"],signal["title"],signal["excerpt"],signal["url"],signal.get("kind","special-interest"),signal.get("first_seen",now_iso()),now_iso()))
        return not bool(exists)

    def list_signals(self,limit=30):
        # Signals are leads. If a page stops mentioning one, it should age out quickly.
        cutoff=(datetime.now(timezone.utc)-timedelta(days=14)).isoformat()
        with self.connect() as conn: rows=conn.execute("SELECT * FROM signals WHERE last_seen>=? ORDER BY last_seen DESC LIMIT ?",(cutoff,int(limit))).fetchall()
        return [dict(row) for row in rows]

    def update_source_status(self,source_id:str,status:str,detail="",events_found=0,signals_found=0):
        checked=now_iso(); success=checked if status=="ok" else None
        with self.connect() as conn:
            conn.execute("INSERT INTO source_status(source_id,last_checked,last_success,status,detail,events_found,signals_found) VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET last_checked=excluded.last_checked,last_success=CASE WHEN excluded.status='ok' THEN excluded.last_success ELSE source_status.last_success END,status=excluded.status,detail=excluded.detail,events_found=excluded.events_found,signals_found=excluded.signals_found",(source_id,checked,success,status,detail[:500],int(events_found),int(signals_found)))

    def source_statuses(self):
        with self.connect() as conn: rows=conn.execute("SELECT * FROM source_status ORDER BY source_id").fetchall()
        return [dict(row) for row in rows]

    def stats(self):
        with self.connect() as conn:
            events=conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]; signals=conn.execute("SELECT COUNT(*) AS n FROM signals").fetchone()["n"]; checked=conn.execute("SELECT COUNT(*) AS n FROM source_status WHERE last_checked IS NOT NULL").fetchone()["n"]
        return {"events":events,"signals":signals,"sources_checked":checked,"db_path":str(self.db_path)}
