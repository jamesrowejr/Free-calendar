from __future__ import annotations

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from discovery import run_discovery, start_background_discovery
from social_ai import process_pending_social, start_social_worker
from storage import Storage

ROOT=Path(__file__).resolve().parent; MAX_SOCIAL_BODY=1_500_000

def load_json(path:Path,fallback):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError,json.JSONDecodeError):return fallback

SOURCES=load_json(ROOT/'sources.json',[]); STORE=Storage(); STORE.seed_events(ROOT/'data'/'events.json')

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(ROOT),**kwargs)
    def end_headers(self):
        self.send_header('Cache-Control','no-store'); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Access-Control-Allow-Headers','Content-Type'); self.send_header('Access-Control-Allow-Methods','GET,POST,DELETE,OPTIONS'); super().end_headers()
    def json_response(self,payload,status=200):
        body=json.dumps(payload,ensure_ascii=False).encode('utf-8'); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def read_json(self):
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:length=0
        if length<=0 or length>MAX_SOCIAL_BODY:return None
        try:return json.loads(self.rfile.read(length).decode('utf-8'))
        except (UnicodeDecodeError,json.JSONDecodeError):return None
    def do_OPTIONS(self): self.send_response(204); self.end_headers()
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/health': return self.json_response({'ok':True,'service':'free-calendar','version':'hosted-0.8','storage':STORE.stats(),'social_ai':{'enabled':bool(os.environ.get('OPENAI_API_KEY')),'model':os.environ.get('OPENAI_MODEL','gpt-5.6-luna')}})
        if path=='/api/events': return self.json_response(STORE.list_events())
        if path=='/api/preferences': return self.json_response(STORE.preference_profile())
        if path=='/api/sources':
            statuses={row['source_id']:row for row in STORE.source_statuses()}; return self.json_response([{**source,'health':statuses.get(source.get('id'))} for source in SOURCES])
        if path=='/api/signals': return self.json_response(STORE.list_signals())
        if path=='/api/social/analysis': return self.json_response(STORE.list_social_analysis())
        if path=='/api/status': return self.json_response({'storage':STORE.stats(),'sources':STORE.source_statuses(),'social':STORE.social_stats(),'preferences':STORE.preference_profile(),'social_ai':{'enabled':bool(os.environ.get('OPENAI_API_KEY')),'model':os.environ.get('OPENAI_MODEL','gpt-5.6-luna')}})
        return super().do_GET()
    def do_POST(self):
        path=urlparse(self.path).path
        if path=='/api/discovery/run': return self.json_response(run_discovery(STORE,SOURCES))
        if path=='/api/social/process': return self.json_response(process_pending_social(STORE,limit=12))
        if path=='/api/feedback':
            payload=self.read_json()
            if not isinstance(payload,dict) or not payload.get('event_id') or payload.get('rating') not in {'interested','not_for_me','loved'}: return self.json_response({'error':'invalid feedback'},400)
            STORE.set_feedback(str(payload['event_id']),payload['rating'],payload.get('event') if isinstance(payload.get('event'),dict) else {}); return self.json_response({'ok':True,'profile':STORE.preference_profile()})
        if path=='/api/social/capture':
            payload=self.read_json()
            if not isinstance(payload,dict): return self.json_response({'error':'invalid JSON'},400)
            captures=payload.get('captures') if isinstance(payload.get('captures'),list) else [payload]
            if len(captures)>50:return self.json_response({'error':'too many captures'},400)
            results=[STORE.save_social_capture(row) for row in captures if isinstance(row,dict)]; saved=sum(1 for row in results if row.get('saved')); duplicates=sum(1 for row in results if row.get('duplicate'))
            return self.json_response({'ok':True,'received':len(results),'saved':saved,'duplicates':duplicates,'queued_for_ai':saved if os.environ.get('OPENAI_API_KEY') else 0,'social':STORE.social_stats(),'social_ai_enabled':bool(os.environ.get('OPENAI_API_KEY'))})
        return self.json_response({'error':'not found'},404)
    def do_DELETE(self):
        path=urlparse(self.path).path
        if path=='/api/feedback':
            payload=self.read_json()
            if not isinstance(payload,dict) or not payload.get('event_id'): return self.json_response({'error':'invalid feedback'},400)
            STORE.clear_feedback(str(payload['event_id'])); return self.json_response({'ok':True,'profile':STORE.preference_profile()})
        return self.json_response({'error':'not found'},404)

if __name__=='__main__':
    host=os.environ.get('HOST','0.0.0.0'); port=int(os.environ.get('PORT','8000')); interval=int(os.environ.get('DISCOVERY_INTERVAL_SECONDS','21600')); start_background_discovery(STORE,SOURCES,interval_seconds=interval); start_social_worker(STORE); print(f'Free Calendar hosted-0.8 → {host}:{port}'); print(f'Persistent data → {STORE.db_path}'); ThreadingHTTPServer((host,port),Handler).serve_forever()
