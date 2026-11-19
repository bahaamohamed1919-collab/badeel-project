"""Pages for a logged-in user: profile, allergies, favourites, search history."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db, security

bp = Blueprint("account", __name__)


def tr(en, ar):
    return ar if g.lang == "ar" else en


@bp.route("/account", methods=["GET", "POST"])
@security.login_required
def profile():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            name = request.form.get("name", "").strip()[:80]
            allergies = request.form.get("allergies", "").strip()[:500]
            consent = request.form.get("consent") == "yes"
            if len(name) < 2:
                flash(tr("Enter your name.", "اكتب اسمك."), "error")
            elif allergies and not consent:
                # Health data is sensitive personal data under Egypt's Law 151/2020:
                # it is stored only with the patient's explicit consent.
                flash(tr("Tick the consent box to save your allergies.",
                         "علّم على خانة الموافقة علشان نحفظ الحساسية."), "error")
            else:
                # Allergies are health data: stored encrypted, readable only by the app.
                db.execute("UPDATE users SET name = ?, allergies_enc = ?, consent_at = ? "
                           "WHERE id = ?",
                           (name, security.encrypt(allergies), db.now() if allergies else None,
                            g.user["id"]))
                security.audit("profile_saved", "allergies saved with consent" if allergies
                               else "allergies cleared")
                db.commit()
                flash(tr("Profile saved.", "تم حفظ البيانات."), "success")
        elif action == "password":
            new = request.form.get("new_password", "")
            if not security.verify_password(g.user["password_hash"],
                                            request.form.get("current_password", "")):
                flash(tr("Current password is wrong.", "كلمة المرور الحالية غير صحيحة."), "error")
            elif security.password_problem(new, g.user["email"], g.user["name"]):
                flash(security.password_message(
                    security.password_problem(new, g.user["email"], g.user["name"]), tr), "error")
            elif new != request.form.get("confirm", ""):
                flash(tr("The two passwords do not match.", "كلمتا المرور غير متطابقتين."), "error")
            else:
                db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                           (security.hash_password(new), g.user["id"]))
                security.audit("password_changed")
                db.commit()
                flash(tr("Password changed.", "تم تغيير كلمة المرور."), "success")
        return redirect(url_for("account.profile"))
    return render_template("account/profile.html",
                           allergies=security.decrypt(g.user["allergies_enc"]))


@bp.route("/favorites")
@security.login_required
def favorites():
    drugs = db.query(
        "SELECT d.* FROM favorites f JOIN drugs d ON d.id = f.drug_id "
        "WHERE f.user_id = ? ORDER BY f.created_at DESC", (g.user["id"],))
    return render_template("account/favorites.html", drugs=drugs)


@bp.route("/favorite/<int:drug_id>", methods=["POST"])
@security.login_required
def toggle_favorite(drug_id):
    if not db.one("SELECT 1 FROM drugs WHERE id = ?", (drug_id,)):
        abort(404)
    if db.one("SELECT 1 FROM favorites WHERE user_id = ? AND drug_id = ?",
              (g.user["id"], drug_id)):
        db.execute("DELETE FROM favorites WHERE user_id = ? AND drug_id = ?",
                   (g.user["id"], drug_id))
    else:
        db.execute("INSERT INTO favorites (user_id, drug_id, created_at) VALUES (?, ?, ?)",
                   (g.user["id"], drug_id, db.now()))
    db.commit()
    return redirect(security.safe_next(request.form.get("next"))
                    or url_for("public.drug", drug_id=drug_id))


@bp.route("/history")
@security.login_required
def history():
    rows = db.query("SELECT query, created_at FROM search_history WHERE user_id = ? "
                    "ORDER BY id DESC LIMIT 100", (g.user["id"],))
    return render_template("account/history.html", rows=rows)


@bp.route("/history/clear", methods=["POST"])
@security.login_required
def clear_history():
    db.execute("DELETE FROM search_history WHERE user_id = ?", (g.user["id"],))
    db.commit()
    flash(tr("Search history deleted.", "تم حذف سجل البحث."), "success")
    return redirect(url_for("account.history"))
