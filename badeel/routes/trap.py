"""Web honeypot.

Automated scanners always try the same addresses (/wp-login.php, /.env,
/phpmyadmin ...). None of them exist in this app, so any visit is an attacker
by definition. Instead of a plain 404 we answer with a fake login page, keep
the attacker busy, and record everything they do in security_events.
"""
from flask import Blueprint, render_template, request

from .. import db, security

bp = Blueprint("trap", __name__)

TRAP_PATHS = [
    "/wp-login.php", "/wp-admin", "/wp-admin/", "/administrator", "/admin.php",
    "/phpmyadmin", "/phpmyadmin/", "/pma", "/.env", "/.git/config", "/config.php",
    "/backup.sql", "/db.sql", "/xmlrpc.php", "/cgi-bin/", "/server-status", "/manager/html",
]


def trap():
    if request.method == "POST":
        # We record the user name tried and only the LENGTH of the password.
        security.log_event(
            "honeypot_login",
            f"user={request.form.get('username', '')[:60]} "
            f"password_length={len(request.form.get('password', ''))}")
    else:
        security.log_event("honeypot_hit", request.query_string.decode("utf-8", "replace")[:200])
    db.commit()
    return render_template("trap.html", failed=request.method == "POST"), 200


for _path in TRAP_PATHS:
    bp.add_url_rule(_path, endpoint="trap_" + str(TRAP_PATHS.index(_path)),
                    view_func=trap, methods=["GET", "POST"])
