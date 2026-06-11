"""
Vercel Serverless Function — свободные окна врача БСК.

Эндпойнт: GET /api/slots?doctor=bublik&date=2026-06-14
          GET /api/slots?doctor=bublik   (все 14 дней)

Источник: ProDoctorov /ajax/schedule/slots_bulk/
Кэш:      in-memory 5 минут на (doctor)

Env-переменные:
  DOCTOR_MAPPING_JSON — переопределяет дефолтный маппинг docs→ids
  CORS_ORIGIN         — для прода поставить "https://bsckrd.ru"
"""

from http.server import BaseHTTPRequestHandler
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

# --- Конфиг ---

CACHE = {}
CACHE_TTL = 300  # 5 минут

DEFAULT_MAPPING = {
    "bublik": {"doctor_id": 1202028, "lpu_id": 102428, "slug": "1202028-bublik", "city": "krasnodar"},
}
DOCTOR_MAPPING = json.loads(os.environ.get("DOCTOR_MAPPING_JSON") or json.dumps(DEFAULT_MAPPING))
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "*")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# --- ProDoctorov ---

def _get_csrf(slug: str, city: str = "krasnodar"):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    page_url = f"https://prodoctorov.ru/{city}/vrach/{slug}/"
    req = urllib.request.Request(
        page_url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9",
        },
    )
    try:
        with opener.open(req, timeout=12) as resp:
            resp.read()
    except Exception as e:
        print(f"CSRF fetch error: {e}")
        return None, None
    for cookie in jar:
        if cookie.name == "csrftoken":
            return cookie.value, jar
    return None, jar


def fetch_slots_from_prodoctorov(doctor_id: int, lpu_id: int, slug: str, city: str, days: int = 14):
    csrf, jar = _get_csrf(slug, city)
    if not csrf:
        return {}
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    payload = json.dumps({
        "days": days,
        "dt_start": datetime.now().strftime("%Y-%m-%d"),
        "doctors_lpus": [{"doctor_id": doctor_id, "lpu_id": lpu_id}],
        "town_timedelta": 3,
        "lpu_timedelta": [[lpu_id, 3]],
        "user_timedelta": 3,
        "all_slots": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://prodoctorov.ru/ajax/schedule/slots_bulk/",
        data=payload,
        method="POST",
        headers={
            "User-Agent": UA,
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
            "Referer": f"https://prodoctorov.ru/{city}/vrach/{slug}/",
            "Origin": "https://prodoctorov.ru",
            "Accept": "application/json, text/plain, */*",
        },
    )
    try:
        with opener.open(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"slots_bulk HTTP {e.code}: {e.read()[:300]}")
        return {}
    except Exception as e:
        print(f"slots_bulk error: {e}")
        return {}
    for row in data.get("result", []):
        if row.get("doctor_id") == doctor_id:
            return row.get("slots") or {}
    return {}


def filter_free(slots_by_date: dict) -> dict:
    return {
        date: [{"time": s["time"], "duration": s.get("duration", 1800)} for s in slots if s.get("free")]
        for date, slots in slots_by_date.items()
    }


def get_doctor_slots(doctor_slug: str) -> dict:
    now = time.time()
    cached = CACHE.get(doctor_slug)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]
    m = DOCTOR_MAPPING.get(doctor_slug)
    if not m:
        return {}
    raw = fetch_slots_from_prodoctorov(
        doctor_id=m["doctor_id"], lpu_id=m["lpu_id"],
        slug=m["slug"], city=m.get("city", "krasnodar"), days=14,
    )
    free = filter_free(raw)
    CACHE[doctor_slug] = (now, free)
    return free


# --- Vercel HTTP handler ---

class handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=120")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        doctor = (qs.get("doctor", [""])[0] or "").strip().lower()
        date = (qs.get("date", [""])[0] or "").strip()

        if not doctor or doctor not in DOCTOR_MAPPING:
            return self._json(400, {
                "error": "unknown doctor",
                "available": list(DOCTOR_MAPPING.keys()),
            })

        all_slots = get_doctor_slots(doctor)
        if date:
            return self._json(200, {"doctor": doctor, "date": date, "slots": all_slots.get(date, [])})
        return self._json(200, {"doctor": doctor, "slots_by_date": all_slots})
