from __future__ import annotations

import hashlib
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
                CREATE TABLE IF NOT EXISTS social_captures (id TEXT PRIMARY KEY,platform TEXT NOT NULL,source_url TEXT NOT NULL,post_url TEXT,source_name TEXT,text TEXT NOT NULL,media_json TEXT NOT NULL DEFAULT '[]',captured_at TEXT NOT NULL,last_seen TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'new');
                CREATE INDEX IF NOT EXISTS idx_social_last_seen ON social_captures(last_seen DESC);
                CREATE INDEX IF NOT EXISTS idx_social_status ON social_captures(status);
                CREATE TABLE IF NOT EXISTS social_analysis (capture_id TEXT PRIMARY KEY,status TEXT NOT NULL,result_json TEXT NOT NULL DEFAULT '{}',event_id TEXT,updated_at TEXT NOT NULL,FOREIGN KEY(capture_id) REFERENCES social_captures(id));
                CREATE INDEX IF NOT EXISTS idx_social_analysis_status ON social_analysis(status);
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
                if event.get("whyGood") and not old.get("whyGood"): old["whyGood"]=event.get("whyGood")
                conn.execute("UPDATE events SET payload=?,updated_at=? WHERE id=?",(json.dumps(old,ensure_ascii=False),now_iso(),existing["id"])); return False
            conn.execute("INSERT INTO events(id,start_date,title_key,payload,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET start_date=excluded.start_date,title_key=excluded.title_key,payload=excluded.payload,updated_at=excluded.updated_at",(event_id,start_date,title_key,json.dumps(event,ensure_ascii=False),now_iso()))
        return True

    def list_events(self):
        today=datetime.now().astimezone().date().isoformat()
        with self.connect() as conn: rows=conn.execute("SELECT payload FROM events WHERE start_date>=? ORDER BY start_date,title_key",(today,)).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def upsert_signal(self,signal:dict):
        with self.connect() as conn:
            exists=conn.execute("SELECT id FROM signals WHERE id=?",(signal["id"],)).fetchone()
            conn.execute("INSERT INTO signals(id,source_id,title,excerpt,url,kind,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen,excerpt=excluded.excerpt,title=excluded.title",(signal["id"],signal["source_id"],signal["title"],signal["excerpt"],signal["url"],signal.get("kind","special-interest"),signal.get("first_seen",now_iso()),now_iso()))
        return not bool(exists)

    def list_signals(self,limit=30):
        cutoff=(datetime.now(timezone.utc)-timedelta(days=14)).isoformat()
        with self.connect() as conn: rows=conn.execute("SELECT * FROM signals WHERE last_seen>=? ORDER BY last_seen DESC LIMIT ?",(cutoff,int(limit))).fetchall()
        return [dict(row) for row in rows]

    def save_social_capture(self,capture:dict):
        platform=str(capture.get("platform") or "").lower().strip(); source_url=str(capture.get("source_url") or "").strip(); post_url=str(capture.get("post_url") or "").strip(); text=str(capture.get("text") or "").strip(); source_name=str(capture.get("source_name") or "").strip(); media=capture.get("media") if isinstance(capture.get("media"),list) else []
        if platform not in {"facebook","instagram"} or not source_url or len(text)<12: return {"saved":False,"reason":"invalid"}
        key=post_url or (source_url+"|"+text[:1200]); capture_id=hashlib.sha256(key.encode("utf-8",errors="ignore")).hexdigest()[:32]; ts=now_iso()
        with self.connect() as conn:
            exists=conn.execute("SELECT id,status FROM social_captures WHERE id=?",(capture_id,)).fetchone()
            conn.execute("INSERT INTO social_captures(id,platform,source_url,post_url,source_name,text,media_json,captured_at,last_seen,status) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen,text=CASE WHEN length(excluded.text)>length(social_captures.text) THEN excluded.text ELSE social_captures.text END,media_json=excluded.media_json",(capture_id,platform,source_url,post_url or None,source_name or None,text[:50000],json.dumps(media[:20],ensure_ascii=False),ts,ts,"new"))
        return {"saved":not bool(exists),"duplicate":bool(exists),"id":capture_id}

    def pending_social_captures(self,limit=8):
        with self.connect() as conn:
            rows=conn.execute("SELECT * FROM social_captures WHERE status='new' ORDER BY captured_at ASC LIMIT ?",(int(limit),)).fetchall()
        out=[]
        for row in rows:
            item=dict(row)
            try: item["media"]=json.loads(item.pop("media_json") or "[]")
            except json.JSONDecodeError: item["media"]=[]
            out.append(item)
        return out

    def mark_social_analysis(self,capture_id:str,status:str,result:dict,event_id=None):
        ts=now_iso()
        with self.connect() as conn:
            conn.execute("UPDATE social_captures SET status=? WHERE id=?",(status,capture_id))
            conn.execute("INSERT INTO social_analysis(capture_id,status,result_json,event_id,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(capture_id) DO UPDATE SET status=excluded.status,result_json=excluded.result_json,event_id=excluded.event_id,updated_at=excluded.updated_at",(capture_id,status,json.dumps(result,ensure_ascii=False),event_id,ts))

    def list_social_analysis(self,limit=30):
        with self.connect() as conn:
            rows=conn.execute("SELECT a.capture_id,a.status,a.result_json,a.event_id,a.updated_at,c.platform,c.source_name,c.source_url,c.post_url FROM social_analysis a JOIN social_captures c ON c.id=a.capture_id ORDER BY a.updated_at DESC LIMIT ?",(int(limit),)).fetchall()
        out=[]
        for row in rows:
            item=dict(row)
            try: item["result"]=json.loads(item.pop("result_json") or "{}")
            except json.JSONDecodeError: item["result"]={}
            out.append(item)
        return out

    def social_stats(self):
        with self.connect() as conn:
            total=conn.execute("SELECT COUNT(*) AS n FROM social_captures").fetchone()["n"]
            counts={row["status"]:row["n"] for row in conn.execute("SELECT status,COUNT(*) AS n FROM social_captures GROUP BY status").fetchall()}
            last=conn.execute("SELECT max(last_seen) AS ts FROM social_captures").fetchone()["ts"]
        return {"captures":total,"new":counts.get("new",0),"published":counts.get("published",0),"review":counts.get("review",0),"ignored":counts.get("ignored",0),"errors":counts.get("error",0),"last_capture":last}

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
        return {"events":events,"signals":signals,"sources_checked":checked,"db_path":str(self.db_path),"social":self.social_stats()}
