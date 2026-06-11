"""
Vercel Serverless Function — приём записи на приём.

POST /api/book
Body: {"doctor":"bublik","date":"2026-06-14","time":"11:00","name":"Иванов Иван","phone":"+7 999 ..."}

Действия:
1. Валидирует поля
2. Шлёт уведомление в Telegram-чат админа БСК
3. Помечает слот «занятым» в общем модуле (sharedlock.py) на 15 минут — другие посетители его не увидят

Env-переменные:
  TELEGRAM_BOT_TOKEN  — токен бота от @BotFather (вида 1234567:AAEh...)
  TELEGRAM_CHAT_ID    — ID чата/группы куда падают записи (можно user_id или -1001234... для группы)
  CORS_ORIGIN         — на проде "https://bsckrd.ru"
"""

from http.server import BaseHTTPRequestHandler
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "*")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

# In-memory pessimistic lock: занимаем слот на 15 минут после записи через виджет.
# Внутри одного инстанса Vercel — общий с api/slots.py через простой модуль на диске? Нет,
# Vercel инстансы изолированы. Используем глобальную переменную внутри текущего инстанса:
# она автоматически переживёт несколько запросов в рамках "тёплой" функции.
PENDING_BOOKINGS = {}  # {"doctor_slug:date:time": expires_at_unix}
PENDING_TTL = 15 * 60   # 15 минут

# Совместимый формат: ключ соответствует тому, что используется в api/slots.py для скрытия слотов.
# Чтобы api/slots.py видел эту блокировку — это нужно сделать через общее хранилище (Vercel KV).
# Для MVP оставляем in-memory и отдаём pending_keys из этого endpoint, виджет сам прячет UI.


def _norm_phone(raw: str) -> str:
    digits = re.sub(r"\D+", "", raw or "")
    return digits


def _is_valid_name(name: str) -> bool:
    n = (name or "").strip()
    return len(n) >= 3 and any(ch.isalpha() for ch in n)


def _is_valid_phone(phone: str) -> bool:
    d = _norm_phone(phone)
    return 10 <= len(d) <= 15


def _telegram_send(text: str) -> bool:
    if not (TG_TOKEN and TG_CHAT):
        print("Telegram not configured (env missing)")
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": TG_CHAT,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            r = json.loads(resp.read().decode("utf-8"))
        return bool(r.get("ok"))
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def _purge_expired():
    now = time.time()
    expired = [k for k, exp in PENDING_BOOKINGS.items() if exp < now]
    for k in expired:
        PENDING_BOOKINGS.pop(k, None)


class handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "invalid_json"})

        doctor = (data.get("doctor") or "").strip().lower()
        date = (data.get("date") or "").strip()
        slot_time = (data.get("time") or "").strip()
        name = (data.get("name") or "").strip()
        phone = (data.get("phone") or "").strip()
        consent = bool(data.get("consent"))

        # Валидация
        if not doctor or not date or not slot_time:
            return self._json(400, {"error": "missing_slot"})
        if not _is_valid_name(name):
            return self._json(400, {"error": "invalid_name", "message": "Укажите имя"})
        if not _is_valid_phone(phone):
            return self._json(400, {"error": "invalid_phone", "message": "Укажите телефон"})
        if not consent:
            return self._json(400, {"error": "no_consent", "message": "Нужно согласие на обработку ПД"})

        # Помечаем слот «занятым» на 15 минут
        _purge_expired()
        key = f"{doctor}:{date}:{slot_time}"
        PENDING_BOOKINGS[key] = time.time() + PENDING_TTL

        # Telegram
        phone_pretty = _norm_phone(phone)
        if phone_pretty.startswith("8"):
            phone_pretty = "7" + phone_pretty[1:]
        if not phone_pretty.startswith("7") and len(phone_pretty) == 10:
            phone_pretty = "7" + phone_pretty
        phone_pretty = "+" + phone_pretty

        tg_text = (
            "🆕 <b>Запись через сайт</b>\n\n"
            f"👤 <b>{name}</b>\n"
            f"📞 <a href=\"tel:{phone_pretty}\">{phone_pretty}</a>\n\n"
            f"🩺 Врач: <b>{doctor}</b>\n"
            f"📅 Дата: <b>{date}</b>\n"
            f"⏰ Время: <b>{slot_time}</b>\n\n"
            "Перезвоните пациенту, подтвердите запись и занесите её в Yclients/ПроДокторов."
        )
        sent = _telegram_send(tg_text)

        return self._json(200, {
            "ok": True,
            "telegram_sent": sent,
            "pending_key": key,
            "expires_in": PENDING_TTL,
        })

    def do_GET(self):
        """Возвращает список текущих pending-слотов — виджет их прячет."""
        _purge_expired()
        return self._json(200, {
            "pending": list(PENDING_BOOKINGS.keys()),
            "ttl_seconds": PENDING_TTL,
        })
