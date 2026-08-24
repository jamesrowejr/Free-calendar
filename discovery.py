from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import threading
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

USER_AGENT = "FreeCalendar/0.5 (+personal Savannah event indexer)"
ANIMAL_TERMS = [
    "baby", "new arrival", "debut", "birthday", "gender reveal", "name reveal",
    "keeper talk", "animal encounter", "feeding", "hatching", "cub", "pup",
    "calf", "foal", "kid goat", "goat", "wolf", "sloth", "otter", "cougar",
    "wildlife", "barnyard", "adoption event"
]
FREE_TERMS = ["free", "no cost", "complimentary", "free admission", "no admission"]
CIVIC_SKIP_TERMS = ["city council", "commission meeting", "board meeting", "committee meeting", "neighborhood association meeting", "workshop", "planning commission", "authority meeting"]
MONTH_RE = r"January|February|March|April|May|June|July|August|September|October|November|December"


def fetch_text(url: str, timeout=18) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def flatten_jsonld(value):
    if isinstance(value, list):
        for item in value:
            yield from flatten_jsonld(item)
    elif isinstance(value, dict):
        if value.get("@type") == "Event" or (isinstance(value.get("@type"), list) and "Event" in value.get("@type")):
            yield value
        for key in ("@graph", "itemListElement"):
            if key in value:
                yield from flatten_jsonld(value[key])


def extract_jsonld_events(page: str):
    blocks = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.I | re.S)
    out = []
    for block in blocks:
        try:
            data = json.loads(html_lib.unescape(block.strip()))
        except Exception:
            continue
        out.extend(flatten_jsonld(data))
    return out


def strip_tags(page: str) -> str:
    page = re.sub(r"<script\b[^>]*>.*?</script>", " ", page, flags=re.I | re.S)
    page = re.sub(r"<style\b[^>]*>.*?</style>", " ", page, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", page)
    return " ".join(html_lib.unescape(text).split())


def normalize_location(raw) -> str:
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        return "Location TBA"
    name = raw.get("name") or ""
    addr = raw.get("address")
    if isinstance(addr, str):
        address = addr
    elif isinstance(addr, dict):
        parts = [addr.get("streetAddress"), addr.get("addressLocality"), addr.get("addressRegion")]
        address = ", ".join(p for p in parts if p)
    else:
        address = ""
    return ", ".join(p for p in (name, address) if p) or "Location TBA"


def cost_from_event(raw: dict):
    offers = raw.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if isinstance(offers, dict):
        price = offers.get("price")
        try:
            numeric = float(price)
            return numeric, "FREE" if numeric == 0 else f"${numeric:g}"
        except (TypeError, ValueError):
            pass
    text = " ".join(str(raw.get(k, "")) for k in ("name", "description")).lower()
    if any(term in text for term in FREE_TERMS):
        return 0, "FREE"
    return None, "Price unknown"


def categories_and_score(title: str, description: str):
    text = f"{title} {description}".lower()
    categories = []
    score = 6.5
    if any(term in text for term in ANIMAL_TERMS):
        categories.append("animals")
        score += 2.0
    if any(x in text for x in ("car show", "cars & coffee", "cars and coffee", "cruise-in", "cruise in")):
        categories.append("cars")
        score += 1.2
    if any(x in text for x in ("concert", "live music", "festival")):
        categories.append("music")
        score += 0.7
    if any(x in text for x in ("park", "outdoor", "garden", "trail")):
        categories.append("outdoors")
    return categories or ["community"], min(score, 9.8)


def slug(text: str):
    return "-".join(re.findall(r"[a-z0-9]+", text.lower()))[:70] or "event"


def normalize_jsonld_event(raw: dict, source: dict):
    title = str(raw.get("name") or "").strip()
    start = str(raw.get("startDate") or "").strip()
    if not title or not start:
        return None
    end = str(raw.get("endDate") or "").strip() or None
    description = strip_tags(str(raw.get("description") or ""))[:700]
    location = normalize_location(raw.get("location"))
    cost, cost_label = cost_from_event(raw)
    categories, score = categories_and_score(title, description)
    if cost == 0:
        score = min(score + 0.8, 9.9)
    event_id = f"auto-{slug(title)}-{start[:10]}"
    url = raw.get("url") or source.get("url")
    return {
        "id": event_id,
        "title": title,
        "start": start,
        "end": end,
        "location": location,
        "cost": cost,
        "costLabel": cost_label,
        "score": round(score, 1),
        "categories": categories,
        "perks": ["Special animal moment"] if "animals" in categories else [],
        "confidence": "high" if source.get("type") == "official" else "medium",
        "description": description or "Automatically indexed from an official event listing.",
        "sources": [{"name": source.get("name", "Source"), "url": url}],
        "discoveredBy": "structured-web",
    }


def parse_civic_date(segment: str):
    date_match = re.search(rf"\b({MONTH_RE})\s+(\d{{1,2}}),\s+(20\d{{2}})", segment, re.I)
    if not date_match:
        return None, None
    try:
        date = datetime.strptime(date_match.group(0), "%B %d, %Y")
    except ValueError:
        return None, None
    after = segment[date_match.end():date_match.end()+180]
    times = re.findall(r"\b(\d{1,2}:\d{2}\s*[AP]M)\b", after, re.I)
    start = date.strftime("%Y-%m-%dT00:00:00")
    end = None
    if times:
        try:
            st = datetime.strptime(times[0].upper().replace("  ", " "), "%I:%M %p")
            start = date.strftime("%Y-%m-%d") + st.strftime("T%H:%M:00")
            if len(times) > 1:
                et = datetime.strptime(times[1].upper().replace("  ", " "), "%I:%M %p")
                end = date.strftime("%Y-%m-%d") + et.strftime("T%H:%M:00")
        except ValueError:
            pass
    return start, end


def extract_civic_events(page: str, source: dict):
    headings = list(re.finditer(r"<h[2-6][^>]*>(.*?)</h[2-6]>", page, re.I | re.S))
    events = []
    seen = set()
    for i, match in enumerate(headings):
        title = strip_tags(match.group(1)).strip(" -–—")
        if not title or len(title) < 4 or len(title) > 180:
            continue
        lower_title = title.lower()
        if any(term in lower_title for term in CIVIC_SKIP_TERMS):
            continue
        seg_end = headings[i+1].start() if i+1 < len(headings) else min(len(page), match.end()+2200)
        segment_html = page[match.end():min(seg_end, match.end()+2200)]
        segment = strip_tags(segment_html)
        start, end = parse_civic_date(segment)
        if not start:
            continue
        key = (title.lower(), start[:10])
        if key in seen:
            continue
        seen.add(key)
        location_match = re.search(r"(?:Location:|@)\s*([^|]{3,140}?)(?=\s+(?:More Details|Details|Description:|Category:|$))", segment, re.I)
        location = location_match.group(1).strip() if location_match else "Location TBA"
        description = segment[:600]
        cost = 0 if any(term in f"{title} {description}".lower() for term in FREE_TERMS) else None
        categories, score = categories_and_score(title, description)
        if cost == 0:
            score = min(score + 0.8, 9.9)
        events.append({
            "id": f"civic-{source['id']}-{slug(title)}-{start[:10]}",
            "title": title,
            "start": start,
            "end": end,
            "location": location,
            "cost": cost,
            "costLabel": "FREE" if cost == 0 else "Price unknown",
            "score": round(score, 1),
            "categories": categories,
            "perks": [],
            "confidence": "medium",
            "description": description or "Indexed from an official municipal calendar.",
            "sources": [{"name": source.get("name", "Official calendar"), "url": source.get("url")}],
            "discoveredBy": "civic-calendar",
        })
    return events


def find_special_signals(page: str, source: dict):
    text = strip_tags(page)
    lower = text.lower()
    found = []
    for term in source.get("watch_terms", ANIMAL_TERMS):
        cursor = 0
        term_lower = term.lower()
        while True:
            idx = lower.find(term_lower, cursor)
            if idx < 0:
                break
            start = max(0, idx - 180)
            end = min(len(text), idx + len(term) + 280)
            excerpt = text[start:end].strip()
            fingerprint = hashlib.sha1(f"{source['id']}|{term_lower}|{excerpt}".encode("utf-8")).hexdigest()[:20]
            found.append({
                "id": fingerprint,
                "source_id": source["id"],
                "title": f"{source['name']}: {term.title()} signal",
                "excerpt": excerpt,
                "url": source["url"],
                "kind": "animal-watch" if source.get("interest") == "animals" else "special-interest",
            })
            cursor = idx + len(term_lower)
            if len(found) >= 12:
                return found
    return found


def run_source(storage, source: dict):
    url = source.get("url")
    if not url or source.get("enabled") is False:
        return {"source": source.get("id"), "status": "skipped", "events": 0, "signals": 0}
    try:
        page = fetch_text(url)
        events_count = 0
        signals_count = 0
        candidates = []
        if source.get("discover", True):
            candidates.extend(filter(None, (normalize_jsonld_event(raw, source) for raw in extract_jsonld_events(page))))
            if source.get("parser") == "civic":
                candidates.extend(extract_civic_events(page, source))
            unique = {}
            for event in candidates:
                unique[(event.get("title", "").lower(), str(event.get("start", ""))[:10])] = event
            for event in unique.values():
                if storage.upsert_event(event):
                    events_count += 1
        if source.get("watch_terms"):
            for signal in find_special_signals(page, source):
                if storage.upsert_signal(signal):
                    signals_count += 1
        storage.update_source_status(source["id"], "ok", f"Fetched {len(page):,} bytes", events_count, signals_count)
        return {"source": source["id"], "status": "ok", "events": events_count, "signals": signals_count}
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        storage.update_source_status(source["id"], "error", str(exc))
        return {"source": source["id"], "status": "error", "error": str(exc), "events": 0, "signals": 0}


def run_discovery(storage, sources: list[dict]):
    results = [run_source(storage, source) for source in sources if source.get("url")]
    return {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "sources": len(results),
        "events_added": sum(r.get("events", 0) for r in results),
        "signals_added": sum(r.get("signals", 0) for r in results),
        "results": results,
    }


def start_background_discovery(storage, sources, interval_seconds=21600, initial_delay=8):
    def worker():
        time.sleep(initial_delay)
        while True:
            try:
                run_discovery(storage, sources)
            except Exception as exc:
                print(f"Discovery worker error: {exc}")
            time.sleep(interval_seconds)
    thread = threading.Thread(target=worker, name="freecal-discovery", daemon=True)
    thread.start()
    return thread
