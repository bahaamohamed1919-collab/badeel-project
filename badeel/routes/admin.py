"""Admin panel: drugs, CSV import, users, security log, audit log."""
import os

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, send_file, url_for)

from .. import db, security
from ..services import importer, ranker, search
from ..services.normalize import DATA_DIR, FORM_LABELS

bp = Blueprint("admin", __name__, url_prefix="/admin")
PER_PAGE = 25


def tr(en, ar):
    return ar if g.lang == "ar" else en


@bp.before_request
@security.role_required("admin")
def admin_only():
    """Every page in this file requires the admin role."""


@bp.route("/")
def dashboard():
    stats = db.one(
        "SELECT (SELECT COUNT(*) FROM drugs) AS drugs,"
        " (SELECT COUNT(*) FROM ingredients) AS ingredients,"
        " (SELECT COUNT(*) FROM users) AS users,"
        " (SELECT COUNT(*) FROM users WHERE status = 'pending') AS pending,"
        " (SELECT COUNT(*) FROM drugs WHERE availability = 'shortage') AS shortages,"
        " (SELECT COUNT(*) FROM drugs WHERE strength_known = 0) AS no_strength,"
        " (SELECT COUNT(*) FROM security_events WHERE created_at > ?) AS events_24h",
        (db.now(-24 * 60),))
    no_alt = db.one(
        "SELECT COUNT(*) AS n FROM (SELECT 1 FROM drugs WHERE strength_known = 1 "
        "GROUP BY composition_key, form HAVING COUNT(*) = 1)")["n"]
    top_searches = db.query(
        "SELECT lower(query) AS q, COUNT(*) AS n FROM search_history "
        "GROUP BY lower(query) ORDER BY n DESC LIMIT 8")
    events = db.query("SELECT * FROM security_events ORDER BY id DESC LIMIT 6")
    model = ranker.model_info(os.path.dirname(current_app.config["DATABASE"]))
    model_stale = bool(model and model["data_version"] != db.get_setting("data_version", "0"))
    return render_template("admin/dashboard.html", stats=stats, no_alt=no_alt,
                           top_searches=top_searches, events=events, model=model,
                           model_stale=model_stale)


@bp.route("/train-model", methods=["POST"])
def train_model():
    if db.one("SELECT COUNT(*) AS n FROM drugs")["n"] < 10:
        flash(tr("Add at least 10 drugs before training.",
                 "أضف 10 أدوية على الأقل قبل التدريب."), "error")
        return redirect(url_for("admin.dashboard"))
    data = search.train_model(log=lambda m: None)
    cv = data["cv"]
    security.audit("model_trained", f"{data['drugs']} drugs, top-1 "
                   f"{cv['baseline']['all']['top1']:.3f} -> {cv['model']['all']['top1']:.3f}")
    db.commit()
    flash(tr("Search model trained.", "تم تدريب موديل البحث."), "success")
    return redirect(url_for("admin.dashboard"))


# ------------------------------------------------------------------ drugs
@bp.route("/drugs")
def drugs():
    q = request.args.get("q", "").strip()[:80]
    page = max(request.args.get("page", 1, type=int), 1)
    where, args = "", []
    if q:
        where = ("WHERE trade_name LIKE ? OR trade_name_ar LIKE ? OR ingredient_key LIKE ? "
                 "OR company LIKE ?")
        args = [f"%{q}%"] * 4
    total = db.one(f"SELECT COUNT(*) AS n FROM drugs {where}", args)["n"]
    rows = db.query(f"SELECT * FROM drugs {where} ORDER BY trade_name LIMIT ? OFFSET ?",
                    args + [PER_PAGE, (page - 1) * PER_PAGE])
    return render_template("admin/drugs.html", rows=rows, q=q, page=page, total=total,
                           pages=max((total + PER_PAGE - 1) // PER_PAGE, 1))


def _drug_form(drug_id=None):
    existing = db.one("SELECT * FROM drugs WHERE id = ?", (drug_id,)) if drug_id else None
    if drug_id and not existing:
        abort(404)
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in
                ("trade_name", "trade_name_ar", "active_ingredients", "form", "company",
                 "price", "drug_class", "availability")}
        fields, items, error = importer.validate_drug(form)
        if error:
            flash(tr("Could not save: ", "تعذر الحفظ: ") + error, "error")
        else:
            new_id = importer.save_drug(fields, items, drug_id)
            db.bump_data_version()
            security.audit("drug_updated" if drug_id else "drug_created",
                           f"{fields['trade_name']} (#{new_id})")
            db.commit()
            flash(tr("Drug saved.", "تم حفظ الدواء."), "success")
            return redirect(url_for("public.drug", drug_id=new_id))
    elif existing:
        # Rebuild "Name 500 mg + Name 125 mg" from the stored ingredient rows.
        parts = db.query(
            "SELECT i.name, di.strength_text FROM drug_ingredients di JOIN ingredients i "
            "ON i.id = di.ingredient_id WHERE di.drug_id = ? ORDER BY di.rowid", (drug_id,))
        form = {
            "trade_name": existing["trade_name"], "trade_name_ar": existing["trade_name_ar"] or "",
            "active_ingredients": " + ".join(
                f"{p['name'].title()} {p['strength_text'] or ''}".strip() for p in parts),
            "form": existing["form_raw"] or existing["form"],
            "company": existing["company"] or "",
            "price": "" if existing["price"] is None else f"{existing['price']:g}",
            "drug_class": existing["drug_class"] or "", "availability": existing["availability"],
        }
    else:
        form = {"availability": "unknown"}
    return render_template("admin/drug_form.html", form=form, drug_id=drug_id,
                           forms=sorted(FORM_LABELS))


@bp.route("/drugs/new", methods=["GET", "POST"])
def drug_new():
    return _drug_form()


@bp.route("/drugs/<int:drug_id>/edit", methods=["GET", "POST"])
def drug_edit(drug_id):
    return _drug_form(drug_id)


@bp.route("/drugs/<int:drug_id>/delete", methods=["POST"])
def drug_delete(drug_id):
    d = db.one("SELECT trade_name FROM drugs WHERE id = ?", (drug_id,))
    if not d:
        abort(404)
    db.execute("DELETE FROM drugs WHERE id = ?", (drug_id,))
    db.execute("DELETE FROM ingredients WHERE id NOT IN "
               "(SELECT ingredient_id FROM drug_ingredients)")
    db.bump_data_version()
    security.audit("drug_deleted", f"{d['trade_name']} (#{drug_id})")
    db.commit()
    flash(tr("Drug deleted.", "تم حذف الدواء."), "success")
    return redirect(url_for("admin.drugs"))


# ----------------------------------------------------------------- import
@bp.route("/import", methods=["GET", "POST"])
def import_data():
    report = None
    if request.method == "POST":
        upload = request.files.get("file")
        replace = request.form.get("mode") == "replace"
        if not upload or not upload.filename.lower().endswith(".csv"):
            flash(tr("Choose a .csv file.", "اختر ملف ‎.csv"), "error")
        else:
            report = importer.import_csv(upload.read(), replace=replace)
            if report["fatal"]:
                db.get_db().rollback()
            else:
                if replace:
                    db.set_setting("demo_data", "0")
                security.audit("csv_import",
                               f"{upload.filename}: +{report['added']} added, "
                               f"{report['updated']} updated, {report['skipped']} skipped"
                               f"{' (replace)' if replace else ''}")
                db.commit()
    return render_template("admin/import.html", report=report)


@bp.route("/import/template")
def import_template():
    return send_file(os.path.join(DATA_DIR, "template.csv"), as_attachment=True,
                     download_name="badeel_template.csv", mimetype="text/csv")


# ------------------------------------------------------------------ users
@bp.route("/users")
def users():
    rows = db.query("SELECT * FROM users ORDER BY status = 'pending' DESC, created_at DESC")
    return render_template("admin/users.html", rows=rows)


@bp.route("/users/<int:user_id>", methods=["POST"])
def user_update(user_id):
    target = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not target:
        abort(404)
    status = request.form.get("status", target["status"])
    role = request.form.get("role", target["role"])
    if status not in ("active", "pending", "disabled") or role not in (
            "patient", "pharmacist", "admin"):
        abort(400)
    if target["id"] == g.user["id"] and (status != "active" or role != "admin"):
        flash(tr("You cannot disable or demote your own account.",
                 "لا يمكنك إيقاف حسابك أو تغيير صلاحيتك."), "error")
    else:
        db.execute("UPDATE users SET status = ?, role = ?, failed_logins = 0, "
                   "locked_until = NULL WHERE id = ?", (status, role, user_id))
        security.audit("user_updated",
                       f"{target['email']}: {target['role']}/{target['status']} -> {role}/{status}")
        db.commit()
        flash(tr("User updated.", "تم تحديث المستخدم."), "success")
    return redirect(url_for("admin.users"))


# ------------------------------------------------------------------- logs
@bp.route("/security")
def security_log():
    kind = request.args.get("type", "")
    types = db.query("SELECT type, COUNT(*) AS n FROM security_events GROUP BY type ORDER BY n DESC")
    if kind:
        events = db.query("SELECT * FROM security_events WHERE type = ? ORDER BY id DESC LIMIT 200",
                          (kind,))
    else:
        events = db.query("SELECT * FROM security_events ORDER BY id DESC LIMIT 200")
    # first/last seen per address: the gap is how long an attacker stayed engaged.
    top_ips = db.query(
        "SELECT ip, COUNT(*) AS n, MIN(created_at) AS first, MAX(created_at) AS last, "
        "CAST(ROUND((julianday(MAX(created_at)) - julianday(MIN(created_at))) * 86400) AS INTEGER) "
        "AS seconds FROM security_events GROUP BY ip ORDER BY n DESC LIMIT 8")
    return render_template("admin/security.html", events=events, types=types, kind=kind,
                           top_ips=top_ips)


@bp.route("/audit")
def audit_log():
    rows = db.query(
        "SELECT a.*, u.name AS user_name, u.email AS user_email FROM audit_log a "
        "LEFT JOIN users u ON u.id = a.user_id ORDER BY a.id DESC LIMIT 200")
    return render_template("admin/audit.html", rows=rows)
