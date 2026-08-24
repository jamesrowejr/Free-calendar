from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

OPENAI_URL = "https://api.openai.com/v1/responses"
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")

SYSTEM = """You extract real upcoming local events from social-media evidence for a personal Savannah, Georgia event calendar.
The calendar favors unusually good value and genuinely interesting experiences, not generic filler.
Home base: Savannah, GA. Rough radius: about 60 minutes driving.
High-interest examples: car shows/cruise-ins/Cars & Coffee/autocross, animal births/birthdays/debuts/feedings/keeper talks, free museum days, unusual tours, live music, festivals, open houses, grand openings, community events with free food/drinks/giveaways, quirky local events.
Low-interest examples unless exceptional: routine meetings, generic networking, ordinary classes/workshops, repetitive farmers markets.
Important: distinguish the Facebook/Instagram POST DATE from the EVENT DATE. Never treat an old historical post as a future event. Images may be flyers and can contain the best event details.
Return ONLY one valid JSON object. No markdown.
Schema:
{
  "is_event": boolean,
  "confidence": number from 0 to 1,
  "title": string or null,
  "start": ISO-8601 local datetime/date string or null,
  "end": ISO-8601 local datetime/date string or null,
  "location": string or null,
  "cost": number or null,
  "cost_label": string,
  "categories": array of short strings,
  "perks": array of short strings,
  "description": concise useful summary,
  "value_score": number from 0 to 10,
  "why_it_is_good": short string,
  "needs_review": boolean,
  "review_reason": string or null
}
Use null rather than inventing details. If the event is clearly expired, set is_event=false and explain in review_reason."""


def _output_text(payload: dict) -> str:
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    return payload.get("output_text", "") or ""


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _request(api_key: str, user_content: list[dict]) -> dict:
    body = {
        "model": MODEL,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM}]},
            {"role": "user", "content": user_content},
        ],
        "max_output_tokens": 1400,
    }
    req = Request(OPENAI_URL, data=json.dumps(body).encode("utf-8"), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=55) as resp:
        return json.loads(resp.read().decode("utf-8"))


def analyze_capture(capture: dict, api_key: str) -> dict:
    media = capture.get("media") or []
    media_summary = []
    image_urls = []
    for item in media[:10]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        alt = str(item.get("alt") or "")
        media_summary.append({"type": item.get("type"), "alt": alt[:1600], "url": url[:1600]})
        if url.startswith("https://") and len(image_urls) < 2 and not any(x in url.lower() for x in ("emoji", "profile")):
            image_urls.append(url)
    user_text = {
        "today": datetime.now().astimezone().isoformat(),
        "platform": capture.get("platform"),
        "source_name": capture.get("source_name"),
        "source_url": capture.get("source_url"),
        "post_url": capture.get("post_url"),
        "post_text": capture.get("text", "")[:30000],
        "media_metadata": media_summary,
    }
    text_item = {"type": "input_text", "text": json.dumps(user_text, ensure_ascii=False)}
    content = [text_item] + [{"type": "input_image", "image_url": url} for url in image_urls]
    try:
        payload = _request(api_key, content)
    except HTTPError:
        # Social CDN images sometimes require browser cookies. If OpenAI cannot fetch them,
        # retry with the full post text + image alt metadata instead of dropping the capture.
        if image_urls:
            payload = _request(api_key, [text_item])
        else:
            raise
    result = _extract_json(_output_text(payload))
    result["model"] = MODEL
    result["image_count"] = len(image_urls)
    return result


def event_from_analysis(capture: dict, analysis: dict):
    if not analysis.get("is_event") or float(analysis.get("confidence") or 0) < 0.72:
        return None
    title = str(analysis.get("title") or "").strip()
    start = str(analysis.get("start") or "").strip()
    if not title or not start:
        return None
    try:
        event_date = datetime.fromisoformat(start.replace("Z", "+00:00")).date()
        if event_date < datetime.now().astimezone().date():
            return None
    except ValueError:
        if not re.match(r"^20\d\d-\d\d-\d\d", start):
            return None
    source_url = capture.get("post_url") or capture.get("source_url")
    platform = (capture.get("platform") or "social").title()
    source_name = capture.get("source_name") or platform
    cost = analysis.get("cost")
    try:
        cost = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        cost = None
    score = max(0.0, min(10.0, float(analysis.get("value_score") or 6.0)))
    return {
        "id": f"social-{capture.get('id')}",
        "title": title,
        "start": start,
        "end": analysis.get("end") or None,
        "location": analysis.get("location") or "Location TBA",
        "cost": cost,
        "costLabel": analysis.get("cost_label") or ("FREE" if cost == 0 else "Price unknown"),
        "score": round(score, 1),
        "categories": analysis.get("categories") or ["community"],
        "perks": analysis.get("perks") or [],
        "confidence": "high" if float(analysis.get("confidence") or 0) >= 0.88 else "medium",
        "description": analysis.get("description") or analysis.get("why_it_is_good") or "Discovered from social media.",
        "sources": [{"name": f"{source_name} ({platform})", "url": source_url}],
        "discoveredBy": "social-ai",
        "whyGood": analysis.get("why_it_is_good") or "",
    }


def process_pending_social(storage, limit=8):
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {"enabled": False, "processed": 0, "published": 0, "review": 0, "errors": 0}
    rows = storage.pending_social_captures(limit=limit)
    stats = {"enabled": True, "processed": 0, "published": 0, "review": 0, "errors": 0}
    for capture in rows:
        stats["processed"] += 1
        try:
            analysis = analyze_capture(capture, api_key)
            event = event_from_analysis(capture, analysis)
            if event and not analysis.get("needs_review"):
                storage.upsert_event(event)
                storage.mark_social_analysis(capture["id"], "published", analysis, event_id=event["id"])
                stats["published"] += 1
            else:
                status = "review" if analysis.get("is_event") or analysis.get("needs_review") else "ignored"
                storage.mark_social_analysis(capture["id"], status, analysis)
                if status == "review": stats["review"] += 1
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
            storage.mark_social_analysis(capture["id"], "error", {"error": str(exc)[:1000]})
            stats["errors"] += 1
    return stats


def start_social_worker(storage, interval_seconds=45, initial_delay=12):
    def worker():
        time.sleep(initial_delay)
        while True:
            try:
                process_pending_social(storage)
            except Exception as exc:
                print(f"Social AI worker error: {exc}")
            time.sleep(interval_seconds)
    thread = threading.Thread(target=worker, name="freecal-social-ai", daemon=True)
    thread.start()
    return thread
