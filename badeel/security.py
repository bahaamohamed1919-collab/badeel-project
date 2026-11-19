"""All security building blocks in one place.

- Passwords: stored only as salted hashes (werkzeug, scrypt).
- Sessions:  signed cookie, HttpOnly + SameSite, 8-hour lifetime.
- CSRF:      every POST must carry a secret token that only our pages know.
- Roles:     decorators that block a page unless the user has the right role.
- Encryption: sensitive patient fields are encrypted at rest (Fernet = AES).
- Brute force: account lock + per-IP limit on failed logins.
- Logging:   security_events (attacks) and audit_log (who changed what).
"""
import hmac
import os
import re
import secrets
from functools import wraps

from cryptography.fernet import Fernet, InvalidToken
from flask import abort, current_app, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import db

MAX_FAILED_LOGINS = 5         # per account, then it is locked
LOCK_MINUTES = 15
MAX_FAILED_PER_IP = 15        # per IP within LOCK_MINUTES

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


# ----------------------------------------------------------------- secrets
def load_or_create_key(path, generator):
    """Secrets live in instance/ (never in Git). Created on first run."""
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read().strip()
    key = generator()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


# --------------------------------------------------------------- passwords
def hash_password(password):
    return generate_password_hash(password)            # scrypt + random salt


def verify_password(password_hash, password):
    return check_password_hash(password_hash, password)


# Passwords follow NIST SP 800-63B-4 (2025) for single-factor login:
# at least 15 characters, no forced mix of character types, and a check
# against passwords that attackers try first.
MIN_PASSWORD = 15
MAX_PASSWORD = 128
COMMON_PASSWORDS = {
    "123456789012345", "1234567890123456", "passwordpassword", "password1234567",
    "qwertyuiopasdfg", "qwertyuiop123456", "iloveyou12345678", "adminadmin12345",
    "administrator123", "111111111111111", "000000000000000", "abcdefghijklmno",
    "welcome123456789", "letmein123456789", "badeelbadeel123", "password123456789",
}


def password_problem(password, *context):
    """Returns None when the password is acceptable, else the reason code."""
    if len(password) < MIN_PASSWORD:
        return "short"
    if len(password) > MAX_PASSWORD:
        return "long"
    low = password.lower()
    if low in COMMON_PASSWORDS or len(set(low)) <= 3:
        return "common"
    for value in context:                 # must not be built from the e-mail or the name
        value = (value or "").lower().split("@")[0]
        if len(value) >= 4 and value in low:
            return "personal"
    return None


def password_message(problem, tr):
    return {
        "short": tr(f"Password must be at least {MIN_PASSWORD} characters. A short sentence is easy "
                    "to remember, e.g. 'tea with mint at 9'.",
                    f"كلمة المرور لازم تكون {MIN_PASSWORD} حرف على الأقل. جملة قصيرة أسهل تفتكرها، "
                    "زي «شاي بالنعناع الساعة 9»."),
        "long": tr("Password is too long (128 characters at most).",
                   "كلمة المرور طويلة جدًا (128 حرف كحد أقصى)."),
        "common": tr("This password is too common. Choose another one.",
                     "كلمة المرور دي منتشرة ومتوقعة. اختار غيرها."),
        "personal": tr("The password must not contain your e-mail or name.",
                       "كلمة المرور ماينفعش يكون فيها إيميلك أو اسمك."),
    }[problem]


# -------------------------------------------------------------- encryption
def _fernet():
    return Fernet(current_app.config["DATA_KEY"])


def encrypt(text):
    if not text:
        return None
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token):
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


# -------------------------------------------------------------------- CSRF
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def check_csrf():
    """Runs before every request (registered in __init__.py)."""
    if request.method in ("GET", "HEAD", "OPTIONS") or request.blueprint == "trap":
        return
    expected = session.get("_csrf")
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
    if not expected or not hmac.compare_digest(expected, sent):
        log_event("csrf_rejected", f"{request.method} {request.path}")
        db.commit()
        abort(400)


# ------------------------------------------------------------ current user
def load_user():
    g.user = None
    uid = session.get("uid")
    if uid is not None:
        user = db.one("SELECT * FROM users WHERE id = ?", (uid,))
        if user and user["status"] == "active":
            g.user = user
        else:
            session.clear()          # deleted or disabled while logged in


def login_user(user):
    session.clear()                  # new session id -> no session fixation
    session["uid"] = user["id"]
    session.permanent = True
    csrf_token()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("auth.login", next=request.path))
            if g.user["role"] not in roles:
                log_event("forbidden", f"user {g.user['id']} -> {request.path}")
                db.commit()
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def safe_next(target):
    """Only allow redirects to our own pages (prevents open-redirect)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


# ----------------------------------------------------------------- logging
def client_ip():
    return request.remote_addr or "?"


def log_event(kind, detail=""):
    db.execute(
        "INSERT INTO security_events (type, ip, path, user_agent, detail, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (kind, client_ip(), request.path[:200],
         (request.headers.get("User-Agent") or "")[:200], str(detail)[:500], db.now()),
    )


def audit(action, detail=""):
    db.execute(
        "INSERT INTO audit_log (user_id, action, detail, created_at) VALUES (?, ?, ?, ?)",
        (g.user["id"] if g.get("user") else None, action, str(detail)[:500], db.now()),
    )


def ip_is_throttled():
    row = db.one(
        "SELECT COUNT(*) AS n FROM security_events "
        "WHERE type = 'login_failed' AND ip = ? AND created_at > ?",
        (client_ip(), db.now(-LOCK_MINUTES)),
    )
    return row["n"] >= MAX_FAILED_PER_IP


# ----------------------------------------------------------------- headers
def set_security_headers(response):
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if g.get("user"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response
