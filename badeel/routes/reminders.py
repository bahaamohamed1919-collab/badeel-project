"""Medicine reminders, notification sign-up, and the files that make Badeel installable (PWA)."""
import os
from datetime import datetime, timedelta, timezone

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, url_for)

from .. import db, security
from ..services import reminders

bp = Blueprint("reminders", __name__)

try:                                            # Egypt time, with summer time when it applies
    from zoneinfo import ZoneInfo
    LOCAL = ZoneInfo("Africa/Cairo")
except Exception:                               # no time zone data (some Windows set-ups)
    LOCAL = timezone(timedelta(hours=2))


def tr(en, ar):
    return ar if g.lang == "ar" else en


def local(dt):
    return dt.astimezone(LOCAL) if dt else None


def _own(reminder_id):
    r = db.one("SELECT * FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, g.user["id"]))
    if not r:
        abort(404)                              # someone else's reminder looks like a missing one
    return r


@bp.app_template_filter("local_time")
def local_time(dt, with_day=True):
    """'today 20:00', 'tomorrow 08:00' or '2026-11-21 08:00', in Egypt time."""
    if not dt:
        return ""
    lt, today = local(dt), datetime.now(LOCAL).date()
    hm = lt.strftime("%H:%M")
    if not with_day:
        return hm
    if lt.date() == today:
        return tr("today %s", "النهارده %s") % hm
    if lt.date() == today + timedelta(days=1):
        return tr("tomorrow %s", "بكره %s") % hm
    return lt.strftime("%Y-%m-%d ") + hm


@bp.route("/reminders/new/<int:drug_id>", methods=["GET", "POST"])
@security.login_required
def edit(drug_id):
    drug = db.one("SELECT * FROM drugs WHERE id = ?", (drug_id,))
    if not drug:
        abort(404)
    current = db.one("SELECT * FROM reminders WHERE user_id = ? AND drug_id = ?", (g.user["id"], drug_id))
    if request.method == "POST":
        problems = []
        try:
            every = int(request.form.get("every_hours", ""))
            if every not in reminders.EVERY_HOURS:
                raise ValueError
        except ValueError:
            problems.append(tr("Choose how often.", "اختار كل قد إيه."))
        try:
            per_dose = float(request.form.get("units_per_dose", "1").replace(",", "."))
            if not 0 < per_dose <= 10:
                raise ValueError
        except ValueError:
            problems.append(tr("Units per dose must be between 0.5 and 10.", "عدد الوحدات في الجرعة لازم يكون من 0.5 لـ 10."))
        box = request.form.get("units_in_box", "").strip()
        try:
            box = int(box) if box else None
            if box is not None and not 0 < box <= 1000:
                raise ValueError
        except ValueError:
            problems.append(tr("Units in the box must be a whole number.", "عدد الوحدات في العلبة لازم يكون رقم صحيح."))
        try:
            hh, mm = (int(x) for x in request.form.get("first_time", "").split(":")[:2])
            today = datetime.now(LOCAL).date()
            first_local = datetime(today.year, today.month, today.day, hh, mm, tzinfo=LOCAL)
        except (ValueError, TypeError):
            problems.append(tr("Enter the time of the first dose.", "اكتب ميعاد أول جرعة."))
        consent = g.user["consent_at"] or request.form.get("consent") == "yes"
        if not consent:
            problems.append(tr("Tick the consent box to save your medicine times.",
                               "علّم على خانة الموافقة علشان نحفظ مواعيد أدويتك."))
        if problems:
            for p in problems:
                flash(p, "error")
            return render_template("reminders/form.html", drug=drug, current=current, form=request.form,
                                   first_value=request.form.get("first_time", "08:00")), 400

        first = reminders.fmt(first_local)
        now = db.now()
        if current:
            db.execute("UPDATE reminders SET every_hours = ?, first_dose_at = ?, units_per_dose = ?, units_in_box = ?, "
                       "box_started_at = COALESCE(box_started_at, ?), active = 1 WHERE id = ?",
                       (every, first, per_dose, box, first, current["id"]))
        else:
            db.execute("INSERT INTO reminders (user_id, drug_id, every_hours, first_dose_at, units_per_dose, "
                       "units_in_box, box_started_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (g.user["id"], drug_id, every, first, per_dose, box, first, now))
        db.execute("INSERT OR IGNORE INTO favorites (user_id, drug_id, created_at) VALUES (?, ?, ?)",
                   (g.user["id"], drug_id, now))
        if not g.user["consent_at"]:
            db.execute("UPDATE users SET consent_at = ? WHERE id = ?", (now, g.user["id"]))
        security.audit("reminder_saved")          # which medicine is not written to the log
        db.commit()
        flash(tr("Reminder saved. Turn on notifications to get it on this device.",
                 "اتحفظ التذكير. فعّل الإشعارات علشان يوصلك على الجهاز ده."), "success")
        return redirect(url_for("account.dashboard") + "#reminders")
    first_value = local(reminders.parse(current["first_dose_at"])).strftime("%H:%M") if current else "08:00"
    return render_template("reminders/form.html", drug=drug, current=current, form={}, first_value=first_value)


@bp.route("/reminders/<int:reminder_id>/new-box", methods=["POST"])
@security.login_required
def new_box(reminder_id):
    r = _own(reminder_id)
    db.execute("UPDATE reminders SET box_started_at = ?, refill_notified_at = NULL WHERE id = ?",
               (reminders.fmt(reminders.utcnow()), r["id"]))
    db.commit()
    flash(tr("New box noted: the count starts again.", "اتسجلت علبة جديدة: العد بدأ من الأول."), "success")
    return redirect(url_for("account.dashboard") + "#reminders")


@bp.route("/reminders/<int:reminder_id>/toggle", methods=["POST"])
@security.login_required
def toggle(reminder_id):
    r = _own(reminder_id)
    db.execute("UPDATE reminders SET active = ? WHERE id = ?", (0 if r["active"] else 1, r["id"]))
    db.commit()
    return redirect(url_for("account.dashboard") + "#reminders")


@bp.route("/reminders/<int:reminder_id>/delete", methods=["POST"])
@security.login_required
def delete(reminder_id):
    r = _own(reminder_id)
    db.execute("DELETE FROM reminders WHERE id = ?", (r["id"],))
    security.audit("reminder_deleted")
    db.commit()
    flash(tr("Reminder deleted.", "اتمسح التذكير."), "success")
    return redirect(url_for("account.dashboard") + "#reminders")


# ------------------------------------------------------------ notifications (Web Push)
@bp.route("/push/key")
@security.login_required
def push_key():
    if not reminders.push_available():
        return jsonify({"available": False})
    return jsonify({"available": True, "key": reminders.vapid_keys()[1]})


@bp.route("/push/subscribe", methods=["POST"])
@security.login_required
def push_subscribe():
    data = request.get_json(silent=True) or {}
    endpoint = str(data.get("endpoint", ""))[:1000]
    keys = data.get("keys") or {}
    p256dh, auth = str(keys.get("p256dh", ""))[:200], str(keys.get("auth", ""))[:100]
    if not endpoint.startswith("https://") or not p256dh or not auth:
        return jsonify({"ok": False}), 400
    db.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at) VALUES (?, ?, ?, ?, ?) "
               "ON CONFLICT(endpoint) DO UPDATE SET user_id = excluded.user_id, p256dh = excluded.p256dh, "
               "auth = excluded.auth", (g.user["id"], endpoint, p256dh, auth, db.now()))
    db.commit()
    return jsonify({"ok": True})


@bp.route("/push/unsubscribe", methods=["POST"])
@security.login_required
def push_unsubscribe():
    endpoint = str((request.get_json(silent=True) or {}).get("endpoint", ""))[:1000]
    db.execute("DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?", (g.user["id"], endpoint))
    db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------ installable app (PWA)
@bp.route("/manifest.webmanifest")
def manifest():
    data = {
        "name": "بديل: بدائل الأدوية", "short_name": "بديل", "lang": "ar", "dir": "rtl",
        "description": "ابحث عن بديل مطابق لأي دواء، وفكّرني بمواعيد أدويتي.",
        "start_url": "/me" if g.get("user") else "/", "scope": "/", "display": "standalone",
        "background_color": "#070a13", "theme_color": "#070a13",
        "icons": [
            {"src": url_for("static", filename="icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": url_for("static", filename="icons/icon-maskable-512.png"), "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }
    response = jsonify(data)
    response.mimetype = "application/manifest+json"
    return response


@bp.route("/sw.js")
def service_worker():
    # Served from the site root so it may show notifications for every page.
    response = send_from_directory(os.path.join(current_app.root_path, "static", "js"), "sw.js",
                                   mimetype="application/javascript", max_age=0)
    response.headers["Cache-Control"] = "no-cache"
    return response
