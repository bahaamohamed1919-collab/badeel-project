"""Application factory: builds and configures the Flask app."""
import os
import secrets
from datetime import timedelta

from cryptography.fernet import Fernet
from flask import Flask, g, render_template, request, session

from . import db, security
from .services.normalize import form_label

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _photo_enabled():
    from .services import ocr
    return ocr.available()


def create_app(test_config=None):
    app = Flask(__name__)
    instance = os.environ.get("BADEEL_INSTANCE", os.path.join(ROOT, "instance"))
    if test_config and "INSTANCE" in test_config:
        instance = test_config["INSTANCE"]
    os.makedirs(instance, exist_ok=True)

    app.config.update(
        DATABASE=os.path.join(instance, "badeel.db"),
        SECRET_KEY=security.load_or_create_key(
            os.path.join(instance, "session.key"), lambda: secrets.token_hex(32).encode()),
        DATA_KEY=security.load_or_create_key(
            os.path.join(instance, "data.key"), Fernet.generate_key),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,                 # uploads: 10 MB max
        SESSION_COOKIE_HTTPONLY=True,                        # JS cannot read the cookie
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("BADEEL_HTTPS") == "1",   # set when online
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        CURRENCY=("EGP", "ج.م"),
    )
    if test_config:
        app.config.update(test_config)

    # Behind a hosting proxy (PythonAnywhere, nginx ...) the visitor's address is
    # in X-Forwarded-For; without this every visitor looks like the proxy, and
    # the per-address login limit would lock everyone out together. Only set
    # BADEEL_TRUST_PROXY=1 when such a proxy is really in front: otherwise
    # anyone could fake the header.
    if os.environ.get("BADEEL_TRUST_PROXY") == "1" or app.config.get("TRUST_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    app.teardown_appcontext(db.close_db)
    with app.app_context():
        db.init_db()

    # ---- runs before every request
    @app.before_request
    def before():
        g.lang = session.get("lang", "ar")
        security.load_user()
        return security.check_csrf()

    app.after_request(security.set_security_headers)

    # ---- helpers available in every template
    def tr(en, ar):
        return ar if g.get("lang", "ar") == "ar" else en

    def money(value):
        if value is None:
            return tr("No price", "بدون سعر")
        en, ar = app.config["CURRENCY"]
        return f"{value:,.2f} {tr(en, ar)}"

    @app.context_processor
    def inject():
        return {
            "_": tr, "lang": g.get("lang", "ar"), "user": g.get("user"),
            "csrf_token": security.csrf_token, "money": money,
            "form_label": lambda f: form_label(f, g.get("lang", "ar")),
            "demo_data": db.get_setting("demo_data") == "1",
            "photo_enabled": _photo_enabled(),
            "public_notice": os.environ.get("BADEEL_PUBLIC_NOTICE") == "1" or app.config.get("PUBLIC_NOTICE"),
            "current_path": request.full_path.rstrip("?"),
        }

    from .routes import account, admin, auth, pharmacist, public, reminders, trap
    for module in (public, auth, account, pharmacist, admin, reminders, trap):
        app.register_blueprint(module.bp)

    def error_page(code, en, ar):
        def handler(_e):
            return render_template("error.html", code=code, message=tr(en, ar)), code
        app.register_error_handler(code, handler)

    error_page(400, "The request was rejected. Reload the page and try again.",
               "تم رفض الطلب. أعد تحميل الصفحة وحاول مرة أخرى.")
    error_page(403, "You do not have permission to open this page.",
               "ليس لديك صلاحية لفتح هذه الصفحة.")
    error_page(404, "This page does not exist.", "هذه الصفحة غير موجودة.")
    error_page(413, "The file is larger than 10 MB.", "حجم الملف أكبر من 10 ميجابايت.")
    error_page(500, "Something went wrong on our side.", "حدث خطأ في الخادم.")
    return app
