"""Medicine reminders and "the box is running out" alerts.

The patient enters their own schedule (as their doctor told them): every 6,
8, 12 or 24 hours from a first dose, so many units per dose. Badeel never
suggests a dose. From the schedule and the number of units in the box
(taken from the drug list when the pack size is known) it works out the
next dose and how many days the box still lasts.

Notifications reach the phone through Web Push. A server task sends them:
    python manage.py send-reminders            (run it every 5 minutes)
    python manage.py send-reminders --loop 300 (or keep it running)
Without the task, the patient still sees everything on the dashboard, and an
open Badeel tab shows the dose notification itself.
"""
import base64
import json
import math
import os
from datetime import datetime, timedelta, timezone

from flask import current_app

from .. import db

EVERY_HOURS = (6, 8, 12, 24)
REFILL_DAYS = 2                      # warn when the box lasts this many days or less
DOSE_WINDOW = timedelta(minutes=20)  # a dose notification is sent at most this late
FMT = "%Y-%m-%d %H:%M:%S"


def parse(text):
    return datetime.strptime(text, FMT).replace(tzinfo=timezone.utc)


def fmt(dt):
    return dt.astimezone(timezone.utc).strftime(FMT)


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)


# ------------------------------------------------------------ schedule maths
def last_dose(r, now):
    """Time of the most recent dose at or before now, or None before the first dose."""
    first = parse(r["first_dose_at"])
    if now < first:
        return None
    step = timedelta(hours=r["every_hours"])
    return first + step * int((now - first) / step)


def next_dose(r, now):
    first = parse(r["first_dose_at"])
    if now < first:
        return first
    return last_dose(r, now) + timedelta(hours=r["every_hours"])


def box_status(r, now):
    """{'units_left', 'days_left', 'runs_out_at', 'refill_due'} or None when the box size is unknown."""
    if not r["units_in_box"]:
        return None
    first = parse(r["first_dose_at"])
    start = max(first, parse(r["box_started_at"])) if r["box_started_at"] else first
    step = timedelta(hours=r["every_hours"])
    # doses since the box was opened, counting the one at the start time itself
    doses = 0 if now < start else int((now - start) / step) + 1
    left = max(0.0, r["units_in_box"] - doses * r["units_per_dose"])
    per_day = r["units_per_dose"] * 24 / r["every_hours"]
    days = left / per_day
    doses_left = math.floor(left / r["units_per_dose"] + 1e-9)
    runs_out = (start + step * (doses + doses_left - 1)) if doses_left else now
    return {"units_left": left, "days_left": days, "runs_out_at": runs_out,
            "refill_due": days <= REFILL_DAYS}


# ------------------------------------------------------------ data
def for_user(user_id):
    return db.query(
        "SELECT r.*, d.trade_name, d.trade_name_ar, d.availability, d.pack_count, d.form "
        "FROM reminders r JOIN drugs d ON d.id = r.drug_id WHERE r.user_id = ? ORDER BY d.trade_name",
        (user_id,))


def summary(user_id, now=None):
    """Reminders of one patient with next dose and box status, for the dashboard."""
    now = now or utcnow()
    out = []
    for r in for_user(user_id):
        out.append({"r": r, "next": next_dose(r, now) if r["active"] else None, "box": box_status(r, now)})
    return out


# ------------------------------------------------------------ Web Push keys
def _key_path(name):
    return os.path.join(os.path.dirname(current_app.config["DATABASE"]), name)


def push_available():
    try:
        import pywebpush  # noqa: F401
    except ImportError:
        return False
    return True


def vapid_keys():
    """(private PEM path, public key for the browser). Created on first use in instance/."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    path = _key_path("vapid_private.pem")
    if not os.path.exists(path):
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # readable by the owner only
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
    with open(path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return path, base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def send_push(sub, payload, contact):
    """Send one notification. Returns False when the browser no longer accepts them."""
    from pywebpush import WebPushException, webpush
    private_path, _ = vapid_keys()
    try:
        webpush(subscription_info={"endpoint": sub["endpoint"],
                                   "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                data=json.dumps(payload, ensure_ascii=False), vapid_private_key=private_path,
                vapid_claims={"sub": contact}, ttl=3600)
        return True
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        return status not in (404, 410)          # 404/410: the subscription is gone


# ------------------------------------------------------------ the server task
def due(now=None):
    """Notifications to send now: [(reminder_row, kind)] with kind 'dose' or 'refill'."""
    now = now or utcnow()
    out = []
    for r in db.query("SELECT r.*, d.trade_name, d.trade_name_ar, d.availability FROM reminders r "
                      "JOIN drugs d ON d.id = r.drug_id WHERE r.active = 1"):
        dose = last_dose(r, now)
        if dose and now - dose <= DOSE_WINDOW and (not r["last_dose_notified"] or parse(r["last_dose_notified"]) < dose):
            out.append((r, "dose", dose))
        box = box_status(r, now)
        if box and box["refill_due"] and (not r["refill_notified_at"]
                                          or now - parse(r["refill_notified_at"]) >= timedelta(hours=24)):
            out.append((r, "refill", box))
    return out


def message(r, kind, info, lang="ar"):
    name = r["trade_name_ar"] if lang == "ar" and r["trade_name_ar"] else r["trade_name"]
    if kind == "dose":
        return {"title": f"ميعاد {name}", "body": "ده ميعاد الجرعة بتاعتك.",
                "url": "/me#reminders", "tag": f"dose-{r['id']}"}
    days = info["days_left"]
    body = (f"العلبة هتخلص خلال {math.ceil(days)} يوم." if days > 0 else "العلبة خلصت.")
    if r["availability"] == "shortage":
        body += " الدواء ناقص: شوف البدايل."
    return {"title": f"{name}: اشتري علبة جديدة", "body": body,
            "url": f"/drug/{r['drug_id']}", "tag": f"refill-{r['id']}"}


def send_due(now=None, sender=None, contact="mailto:admin@badeel.invalid", log=print):
    """Send what is due. sender(sub, payload) can be replaced in tests."""
    now = now or utcnow()
    sender = sender or (lambda sub, payload: send_push(sub, payload, contact))
    sent = 0
    for r, kind, info in due(now):
        subs = db.query("SELECT * FROM push_subscriptions WHERE user_id = ?", (r["user_id"],))
        payload = message(r, kind, info)
        for sub in subs:
            if sender(sub, payload):
                sent += 1
            else:
                db.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub["id"],))
        column = "last_dose_notified" if kind == "dose" else "refill_notified_at"
        db.execute(f"UPDATE reminders SET {column} = ? WHERE id = ?",
                   (fmt(info if kind == "dose" else now), r["id"]))
    db.commit()
    log(f"{sent} notification(s) sent.")
    return sent
