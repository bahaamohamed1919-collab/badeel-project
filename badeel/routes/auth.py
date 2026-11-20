"""Register, log in, log out."""
from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from .. import db, security

bp = Blueprint("auth", __name__)

# Each role lands on its own dashboard after logging in.
HOME_BY_ROLE = {"admin": "admin.dashboard", "pharmacist": "pharmacist.dashboard",
                "patient": "account.dashboard"}

# Verified against when the e-mail does not exist, so the response takes the
# same time either way and an attacker cannot tell which e-mails are registered.
_DUMMY_HASH = security.hash_password("not-a-real-password")


def tr(en, ar):
    return ar if g.lang == "ar" else en


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("public.home"))
    form = {"name": "", "email": "", "role": "patient"}
    if request.method == "POST":
        form = {"name": request.form.get("name", "").strip()[:80],
                "email": request.form.get("email", "").strip().lower()[:120],
                "role": request.form.get("role", "patient")}
        password = request.form.get("password", "")
        error = None

        if request.form.get("website"):
            # Hidden field that humans never see. Only bots fill it in.
            security.log_event("bot_signup", form["email"])
            db.commit()
            return redirect(url_for("auth.login"))

        problem = security.password_problem(password, form["email"], form["name"])
        if len(form["name"]) < 2:
            error = tr("Enter your name.", "اكتب اسمك.")
        elif not security.EMAIL_RE.match(form["email"]):
            error = tr("Enter a valid e-mail address.", "اكتب بريدًا إلكترونيًا صحيحًا.")
        elif form["role"] not in ("patient", "pharmacist"):
            error = tr("Choose an account type.", "اختر نوع الحساب.")
        elif problem:
            error = security.password_message(problem, tr)
        elif password != request.form.get("confirm", ""):
            error = tr("The two passwords do not match.", "كلمتا المرور غير متطابقتين.")
        elif db.one("SELECT 1 FROM users WHERE email = ?", (form["email"],)):
            error = tr("This e-mail already has an account. Log in instead.",
                       "هذا البريد مسجل بالفعل. سجّل الدخول.")

        if error:
            flash(error, "error")
        else:
            # Pharmacists can change availability and prices, so an admin approves them first.
            status = "pending" if form["role"] == "pharmacist" else "active"
            db.execute(
                "INSERT INTO users (name, email, password_hash, role, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (form["name"], form["email"], security.hash_password(password),
                 form["role"], status, db.now()))
            db.commit()
            if status == "pending":
                flash(tr("Account created. An admin must approve pharmacist accounts "
                         "before you can log in.",
                         "تم إنشاء الحساب. حسابات الصيادلة تحتاج موافقة الأدمن قبل الدخول."),
                      "info")
            else:
                flash(tr("Account created. Log in to continue.",
                         "تم إنشاء الحساب. سجّل الدخول للمتابعة."), "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("public.home"))
    next_url = security.safe_next(request.values.get("next"))
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()[:120]
        password = request.form.get("password", "")
        wrong = tr("Wrong e-mail or password.", "البريد أو كلمة المرور غير صحيحة.")

        if security.ip_is_throttled():
            flash(tr("Too many failed attempts. Try again in 15 minutes.",
                     "محاولات فاشلة كثيرة. حاول بعد 15 دقيقة."), "error")
            return render_template("auth/login.html", email=email, next_url=next_url), 429

        user = db.one("SELECT * FROM users WHERE email = ?", (email,))
        if user and user["locked_until"] and user["locked_until"] > db.now():
            security.log_event("login_locked", email)
            db.commit()
            flash(tr("This account is locked for 15 minutes after repeated failed logins.",
                     "تم قفل الحساب 15 دقيقة بسبب محاولات دخول فاشلة متكررة."), "error")
        elif not user:
            security.verify_password(_DUMMY_HASH, password)
            security.log_event("login_failed", email)
            db.commit()
            flash(wrong, "error")
        elif not security.verify_password(user["password_hash"], password):
            fails = user["failed_logins"] + 1
            locked = db.now(security.LOCK_MINUTES) if fails >= security.MAX_FAILED_LOGINS else None
            db.execute("UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
                       (0 if locked else fails, locked, user["id"]))
            security.log_event("login_failed", email)
            if locked:
                security.log_event("account_locked", email)
            db.commit()
            flash(wrong, "error")
        elif user["status"] == "pending":
            flash(tr("Your pharmacist account is waiting for admin approval.",
                     "حساب الصيدلي في انتظار موافقة الأدمن."), "info")
        elif user["status"] != "active":
            flash(tr("This account is disabled.", "هذا الحساب موقوف."), "error")
        else:
            db.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?",
                       (user["id"],))
            db.commit()
            lang = session.get("lang")
            security.login_user(user)
            if lang:
                session["lang"] = lang
            return redirect(next_url or url_for(HOME_BY_ROLE.get(user["role"], "public.home")))
    return render_template("auth/login.html", email=email, next_url=next_url)


@bp.route("/logout", methods=["POST"])
def logout():
    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    return redirect(url_for("public.home"))
