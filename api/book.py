"""
Vercel Serverless Function — приём записи на приём.

POST /api/book
Body: {"doctor":"bublik","date":"2026-06-14","time":"11:00","name":"Иванов","phone":"+7 999 ...","consent":true}

Действия:
1. Валидирует поля
2. Шлёт письмо администратору БСК через Resend API
3. Помечает слот «занятым» (in-memory) на 15 минут — другие посетители его не увидят

Env-переменные:
  RESEND_API_KEY      — API-ключ Resend (вида re_xxx)
  BOOKING_EMAIL_TO    — получатель (по умолчанию bsckrd@gmail.com)
  BOOKING_EMAIL_FROM  — отправитель (по умолчанию "БСК <onboarding@resend.dev>")
  CORS_ORIGIN         — на проде "https://bsckrd.ru"

GET /api/book — возвращает список pending-слотов, чтобы виджет их скрыл.
"""

from http.server import BaseHTTPRequestHandler
import html as html_mod
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "*")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
BOOKING_EMAIL_TO = os.environ.get("BOOKING_EMAIL_TO", "bsckrd@gmail.com")
BOOKING_EMAIL_FROM = os.environ.get("BOOKING_EMAIL_FROM", "БСК запись <onboarding@resend.dev>")

# In-memory pessimistic lock на инстансе Vercel
PENDING_BOOKINGS = {}  # {"doctor:date:time": expires_at}
PENDING_TTL = 15 * 60  # 15 минут


def _norm_phone(raw: str) -> str:
    return re.sub(r"\D+", "", raw or "")


def _is_valid_name(name: str) -> bool:
    n = (name or "").strip()
    return len(n) >= 3 and any(ch.isalpha() for ch in n)


def _is_valid_phone(phone: str) -> bool:
    d = _norm_phone(phone)
    return 10 <= len(d) <= 15


def _pretty_phone(raw: str) -> str:
    d = _norm_phone(raw)
    if d.startswith("8"):
        d = "7" + d[1:]
    if not d.startswith("7") and len(d) == 10:
        d = "7" + d
    if len(d) == 11 and d.startswith("7"):
        return f"+7 ({d[1:4]}) {d[4:7]}-{d[7:9]}-{d[9:11]}"
    return "+" + d


def _send_email(subject: str, html_body: str, plain_body: str) -> bool:
    if not RESEND_API_KEY:
        print("Resend not configured (RESEND_API_KEY missing)")
        return False
    payload = json.dumps({
        "from": BOOKING_EMAIL_FROM,
        "to": [BOOKING_EMAIL_TO],
        "subject": subject,
        "html": html_body,
        "text": plain_body,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload, method="POST",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            r = json.loads(resp.read().decode("utf-8"))
        print(f"Resend response: {r}")
        return bool(r.get("id"))
    except urllib.error.HTTPError as e:
        print(f"Resend HTTP {e.code}: {e.read()[:300]}")
        return False
    except Exception as e:
        print(f"Resend error: {e}")
        return False


def _purge_expired():
    now = time.time()
    expired = [k for k, exp in PENDING_BOOKINGS.items() if exp < now]
    for k in expired:
        PENDING_BOOKINGS.pop(k, None)


def _build_email(doctor: str, date: str, slot_time: str, name: str, phone_pretty: str):
    esc = html_mod.escape
    html_body = f"""<!doctype html>
<html><body style="font-family: -apple-system, Helvetica, Arial, sans-serif; color: #00304A; background: #f4f4f4; padding: 24px;">
  <div style="max-width: 560px; margin: 0 auto; background: #fff; border-radius: 16px; padding: 32px; border: 1px solid #ebeff2;">
    <h2 style="margin: 0 0 6px; color: #00304A;">🆕 Запись через сайт</h2>
    <p style="color: #4A4A4A; margin: 0 0 24px; font-size: 14px;">Поступила новая заявка с bsckrd.ru</p>

    <table style="width: 100%; border-collapse: collapse; font-size: 15px;">
      <tr><td style="padding: 10px 0; color: #4A4A4A; width: 130px;">Пациент</td><td style="padding: 10px 0; font-weight: 700;">{esc(name)}</td></tr>
      <tr><td style="padding: 10px 0; color: #4A4A4A; border-top: 1px solid #ebeff2;">Телефон</td><td style="padding: 10px 0; font-weight: 700; border-top: 1px solid #ebeff2;"><a href="tel:{esc(phone_pretty)}" style="color: #68B6C8; text-decoration: none;">{esc(phone_pretty)}</a></td></tr>
      <tr><td style="padding: 10px 0; color: #4A4A4A; border-top: 1px solid #ebeff2;">Врач</td><td style="padding: 10px 0; font-weight: 700; border-top: 1px solid #ebeff2;">{esc(doctor)}</td></tr>
      <tr><td style="padding: 10px 0; color: #4A4A4A; border-top: 1px solid #ebeff2;">Дата</td><td style="padding: 10px 0; font-weight: 700; border-top: 1px solid #ebeff2;">{esc(date)}</td></tr>
      <tr><td style="padding: 10px 0; color: #4A4A4A; border-top: 1px solid #ebeff2;">Время</td><td style="padding: 10px 0; font-weight: 700; border-top: 1px solid #ebeff2;">{esc(slot_time)}</td></tr>
    </table>

    <div style="margin-top: 24px; padding: 16px 18px; background: linear-gradient(135deg, rgba(104,182,200,0.12), rgba(104,182,200,0.04)); border-left: 4px solid #68B6C8; border-radius: 0 10px 10px 0; font-size: 13px; color: #00304A; line-height: 1.5;">
      Перезвоните пациенту в течение часа, подтвердите запись и занесите её в Yclients / ПроДокторов.
    </div>

    <p style="margin: 24px 0 0; font-size: 11px; color: #9aa5ab; text-align: center;">
      Согласие на обработку ПД подтверждено.<br>Слот зарезервирован на 15 минут.
    </p>
  </div>
</body></html>"""
    plain_body = (
        f"Новая запись через сайт\n\n"
        f"Пациент: {name}\n"
        f"Телефон: {phone_pretty}\n"
        f"Врач:    {doctor}\n"
        f"Дата:    {date}\n"
        f"Время:   {slot_time}\n\n"
        f"Перезвоните пациенту, подтвердите запись и занесите её в Yclients/ПроДокторов."
    )
    return html_body, plain_body


class handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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

    def do_GET(self):
        _purge_expired()
        return self._json(200, {
            "pending": list(PENDING_BOOKINGS.keys()),
            "ttl_seconds": PENDING_TTL,
        })

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

        if not doctor or not date or not slot_time:
            return self._json(400, {"error": "missing_slot"})
        if not _is_valid_name(name):
            return self._json(400, {"error": "invalid_name", "message": "Укажите имя"})
        if not _is_valid_phone(phone):
            return self._json(400, {"error": "invalid_phone", "message": "Укажите корректный телефон"})
        if not consent:
            return self._json(400, {"error": "no_consent", "message": "Нужно согласие на обработку ПД"})

        _purge_expired()
        key = f"{doctor}:{date}:{slot_time}"
        PENDING_BOOKINGS[key] = time.time() + PENDING_TTL

        phone_pretty = _pretty_phone(phone)
        subject = f"Запись: {name} — {date} {slot_time}"
        html_body, plain_body = _build_email(doctor, date, slot_time, name, phone_pretty)
        sent = _send_email(subject, html_body, plain_body)

        return self._json(200, {
            "ok": True,
            "email_sent": sent,
            "pending_key": key,
            "expires_in": PENDING_TTL,
        })
