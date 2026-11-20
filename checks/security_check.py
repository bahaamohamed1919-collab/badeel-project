"""Automated attack simulation.   python checks/security_check.py

Launches real attacks against a throw-away copy of the site (temporary
database, deleted at the end) and reports, for each one, whether it was
BLOCKED and whether it was DETECTED (written to the security log).

It never touches your real database, so running it before a presentation
cannot lock your accounts or fill your security log.

Measures the Cyber Security metrics named in the project proposal:
  - Attack prevention rate  = attacks the site was protected against / attacks tried
  - Attack detection rate   = attacks logged  / attacks that should be logged
"""
import io
import os
import re
import secrets
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from badeel import create_app, db, security                        # noqa: E402
from badeel.routes.trap import TRAP_PATHS                          # noqa: E402
from badeel.services import importer                               # noqa: E402

results = []          # (category, attack, protected, should_log, logged)


def record(category, attack, blocked, should_log=False, logged=False):
    results.append((category, attack, bool(blocked), should_log, bool(logged)))


class Lab:
    """A temporary copy of the application with one admin and one victim."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="badeel-attack-")
        self.app = create_app({"TESTING": True, "INSTANCE": self.tmp,
                               "DATABASE": os.path.join(self.tmp, "lab.db")})
        self.password = "Victim-" + secrets.token_hex(4) + "7"
        with self.app.app_context():
            with open(os.path.join(ROOT, "data", "sample_drugs.csv"), "rb") as f:
                importer.import_csv(f.read())
            for name, email, role in (("Admin", "admin@lab.test", "admin"),
                                      ("Victim", "victim@lab.test", "patient")):
                db.execute("INSERT INTO users (name, email, password_hash, role, status, "
                           "created_at) VALUES (?, ?, ?, ?, 'active', ?)",
                           (name, email, security.hash_password(self.password), role, db.now()))
            db.commit()

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def client(self):
        return self.app.test_client()

    def events(self, kind):
        with self.app.app_context():
            return db.one("SELECT COUNT(*) AS n FROM security_events WHERE type = ?",
                          (kind,))["n"]

    def scalar(self, sql, args=()):
        with self.app.app_context():
            row = db.one(sql, args)
            return row[0] if row else None

    @staticmethod
    def token(client, path="/login"):
        html = client.get(path).get_data(as_text=True)
        m = re.search(r'name="csrf_token" value="([^"]+)"', html)
        return m.group(1) if m else ""

    def login(self, client, email, password):
        return client.post("/login", data={"email": email, "password": password,
                                           "csrf_token": self.token(client)})

    @staticmethod
    def logged_in(client):
        with client.session_transaction() as s:
            return "uid" in s


# ---------------------------------------------------------------- attacks
def sql_injection(lab):
    payloads = ["' OR '1'='1", "admin@lab.test' --", "' OR 1=1 --",
                '" OR ""="', "x' UNION SELECT 1,2,3,4,5,6,7,8,9,10 --"]
    for p in payloads:
        c = lab.client()
        before = lab.events("login_failed")
        lab.login(c, p, p)
        record("SQL injection", f"login bypass: {p}", not lab.logged_in(c),
               True, lab.events("login_failed") > before)
    c = lab.client()
    count = lab.scalar("SELECT COUNT(*) FROM drugs")
    for p in ["'; DROP TABLE drugs; --", "%' OR 1=1 --", "1' AND SLEEP(5) --"]:
        r1 = c.get("/search", query_string={"q": p})
        r2 = c.get("/api/suggest", query_string={"q": p})
        intact = lab.scalar("SELECT COUNT(*) FROM drugs") == count
        record("SQL injection", f"search box: {p}",
               r1.status_code == 200 and r2.status_code == 200 and intact)


def xss(lab):
    c = lab.client()
    for p in ["<script>alert(1)</script>", '"><img src=x onerror=alert(1)>',
              "<svg onload=alert(1)>"]:
        html = c.get("/search", query_string={"q": p}).get_data(as_text=True)
        record("Cross-site scripting (XSS)", f"reflected: {p}", p not in html)
    # Stored XSS: a malicious name that the admin will later see.
    evil = "<script>alert('xss')</script>"
    c = lab.client()
    c.post("/register", data={"name": evil, "email": "evil@lab.test", "role": "patient",
                              "password": lab.password, "confirm": lab.password,
                              "csrf_token": lab.token(c, "/register")})
    admin = lab.client()
    lab.login(admin, "admin@lab.test", lab.password)
    html = admin.get("/admin/users").get_data(as_text=True)
    record("Cross-site scripting (XSS)", "stored: script in a user name shown to admin",
           "evil@lab.test" in html and evil not in html)
    csp = admin.get("/").headers.get("Content-Security-Policy", "")
    record("Cross-site scripting (XSS)", "Content-Security-Policy blocks outside scripts",
           "default-src 'self'" in csp and "unsafe-inline" not in csp)


def csrf(lab):
    victim = lab.client()
    lab.login(victim, "victim@lab.test", lab.password)
    cases = [
        ("change profile with no token", {"action": "profile", "name": "Hacked"}),
        ("change profile with a fake token", {"action": "profile", "name": "Hacked",
                                              "csrf_token": "forged-token"}),
    ]
    other = lab.client()
    cases.append(("change profile with another visitor's token",
                  {"action": "profile", "name": "Hacked", "csrf_token": lab.token(other)}))
    for name, data in cases:
        before = lab.events("csrf_rejected")
        r = victim.post("/account", data=data)
        unchanged = lab.scalar("SELECT name FROM users WHERE email = 'victim@lab.test'") == "Victim"
        record("Cross-site request forgery (CSRF)", name, r.status_code == 400 and unchanged,
               True, lab.events("csrf_rejected") > before)


def access_control(lab):
    anon = lab.client()
    r = anon.get("/admin/")
    record("Broken access control", "visitor opens the admin panel",
           r.status_code == 302 and "/login" in r.headers.get("Location", ""))
    patient = lab.client()
    lab.login(patient, "victim@lab.test", lab.password)
    for path in ("/admin/", "/admin/users", "/admin/import", "/admin/security", "/pharmacist"):
        before = lab.events("forbidden")
        r = patient.get(path)
        record("Broken access control", f"patient opens {path}", r.status_code == 403,
               True, lab.events("forbidden") > before)
    before = lab.events("forbidden")
    r = patient.post("/admin/train-model", data={"csrf_token": lab.token(patient, "/account")})
    record("Broken access control", "patient retrains the search model", r.status_code == 403,
           True, lab.events("forbidden") > before)
    drug_id = lab.scalar("SELECT id FROM drugs LIMIT 1")
    before = lab.events("forbidden")
    r = patient.post(f"/drug/{drug_id}/status", data={
        "availability": "shortage", "price": "1", "csrf_token": lab.token(patient, "/account")})
    record("Broken access control", "patient changes a drug price", r.status_code == 403,
           True, lab.events("forbidden") > before)
    c = lab.client()
    c.post("/register", data={"name": "Climber", "email": "climber@lab.test", "role": "admin",
                              "password": lab.password, "confirm": lab.password,
                              "csrf_token": lab.token(c, "/register")})
    record("Broken access control", "register directly as admin",
           lab.scalar("SELECT role FROM users WHERE email = 'climber@lab.test'") != "admin")
    c = lab.client()
    c.post("/register", data={"name": "Fake Pharm", "email": "fakepharm@lab.test",
                              "role": "pharmacist", "password": lab.password,
                              "confirm": lab.password, "csrf_token": lab.token(c, "/register")})
    lab.login(c, "fakepharm@lab.test", lab.password)
    record("Broken access control", "unapproved pharmacist logs in", not lab.logged_in(c))
    forged = lab.client()
    forged.set_cookie("session", "eyJ1aWQiOjF9.Zm9yZ2Vk.c2lnbmF0dXJl")   # {"uid":1} unsigned
    r = forged.get("/admin/")
    record("Broken access control", "forged session cookie claiming to be the admin",
           r.status_code == 302)


def brute_force(lab):
    c = lab.client()
    for i in range(security.MAX_FAILED_LOGINS):
        lab.login(c, "victim@lab.test", f"guess-{i}-password")
    lab.login(c, "victim@lab.test", lab.password)          # the right password, too late
    record("Brute force", f"{security.MAX_FAILED_LOGINS} wrong passwords, then the right one",
           not lab.logged_in(c), True, lab.events("account_locked") > 0)
    blocked_status = None
    for i in range(security.MAX_FAILED_PER_IP + 2):
        r = lab.login(c, f"user{i}@lab.test", "wrong-password-1")
        if r.status_code == 429:
            blocked_status = 429
            break
    record("Brute force", "many accounts tried from one address (password spraying)",
           blocked_status == 429, True, lab.events("login_failed") >= security.MAX_FAILED_PER_IP)


def weak_passwords(lab):
    c = lab.client()
    c.post("/register", data={"name": "Lazy", "email": "lazy@lab.test", "role": "patient",
                              "password": "passwordpassword", "confirm": "passwordpassword",
                              "csrf_token": lab.token(c, "/register")})
    record("Brute force", "register with a well-known password",
           lab.scalar("SELECT 1 FROM users WHERE email = 'lazy@lab.test'") is None)


def enumeration(lab):
    def attempt(email):
        c = lab.client()
        start = time.perf_counter()
        r = lab.login(c, email, "wrong-password-1")
        elapsed = time.perf_counter() - start
        # the per-session CSRF token differs on every session, not per e-mail: remove it
        # from the form field and from the <meta> tag before comparing
        text = re.sub(r'name="csrf_token" value="[^"]+"', "", r.get_data(as_text=True))
        text = re.sub(r'name="csrf-token" content="[^"]+"', "", text)
        text = re.sub(r'value="[^"]*@lab\.test"', "", text)
        return elapsed, text
    attempt("warmup@lab.test")
    t_real, page_real = attempt("victim@lab.test")
    t_fake, page_fake = attempt("nobody@lab.test")
    record("Account enumeration", "same page for a real and a fake e-mail",
           page_real == page_fake)
    ratio = max(t_real, t_fake) / max(min(t_real, t_fake), 1e-6)
    record("Account enumeration",
           f"same response time (real {t_real * 1000:.0f} ms / fake {t_fake * 1000:.0f} ms)",
           ratio < 3)


def honeypot(lab):
    c = lab.client()
    for path in TRAP_PATHS:
        before = lab.events("honeypot_hit")
        r = c.get(path, headers={"User-Agent": "sqlmap/1.8 (scanner)"})
        record("Scanner and honeypot", f"scan {path}", r.status_code == 200 and b"Log In" in r.data,
               True, lab.events("honeypot_hit") > before)
    before = lab.events("honeypot_login")
    c.post("/wp-login.php", data={"username": "admin", "password": "SuperSecret123"})
    with lab.app.app_context():
        detail = db.one("SELECT detail FROM security_events WHERE type = 'honeypot_login' "
                        "ORDER BY id DESC LIMIT 1")
    record("Scanner and honeypot", "attacker types credentials into the fake login",
           detail and "SuperSecret123" not in detail["detail"], True,
           lab.events("honeypot_login") > before)


def sensitive_files(lab):
    c = lab.client()
    for path in ("/instance/badeel.db", "/instance/data.key", "/static/../instance/data.key",
                 "/static/..%2f..%2finstance%2fdata.key", "/badeel/schema.sql", "/manage.py",
                 "/requirements.txt"):
        r = c.get(path)
        record("Sensitive file exposure", f"download {path}", r.status_code == 404)


def transport_and_storage(lab):
    c = lab.client()
    r = lab.login(c, "victim@lab.test", lab.password)
    cookie = r.headers.get("Set-Cookie", "")
    record("Session security", "session cookie hidden from JavaScript (HttpOnly)",
           "HttpOnly" in cookie)
    record("Session security", "session cookie not sent by other sites (SameSite)",
           "SameSite=Lax" in cookie)
    page = c.get("/")
    for header, expected in (("X-Frame-Options", "DENY"), ("X-Content-Type-Options", "nosniff")):
        record("Session security", f"{header} header (clickjacking / sniffing)",
               page.headers.get(header) == expected)
    r = c.get("/lang/en", query_string={"next": "//evil.example/phish"})
    record("Session security", "open redirect to another website",
           "evil.example" not in r.headers.get("Location", ""))
    c.post("/account", data={"action": "profile", "name": "Victim",
                             "allergies": "Amoxicillin, Ibuprofen", "consent": "yes",
                             "csrf_token": lab.token(c, "/account")})
    row_hash = lab.scalar("SELECT password_hash FROM users WHERE email = 'victim@lab.test'")
    row_enc = lab.scalar("SELECT allergies_enc FROM users WHERE email = 'victim@lab.test'")
    record("Data protection", "password stored as a salted hash, not as text",
           row_hash.startswith("scrypt:") and lab.password not in row_hash)
    record("Data protection", "allergies unreadable in the database (encrypted)",
           row_enc and "Amoxicillin" not in row_enc)
    admin = lab.client()
    lab.login(admin, "admin@lab.test", lab.password)
    big = io.BytesIO(b"a" * (11 * 1024 * 1024))
    r = admin.post("/admin/import", data={"file": (big, "big.csv"), "mode": "append",
                                          "csrf_token": lab.token(admin, "/account")},
                   content_type="multipart/form-data")
    record("Data protection", "upload an 11 MB file to fill the server", r.status_code == 413)


# ----------------------------------------------------------------- report
def main():
    started = time.perf_counter()
    for attack in (sql_injection, xss, csrf, access_control, brute_force, weak_passwords,
                   enumeration,
                   honeypot, sensitive_files, transport_and_storage):
        lab = Lab()                     # fresh copy: one attack cannot affect the next
        try:
            attack(lab)
        finally:
            lab.close()
    seconds = time.perf_counter() - started

    print("\nBADEEL ATTACK SIMULATION  (temporary copy of the site, real database untouched)\n")
    category = None
    for cat, attack, blocked, should_log, logged in results:
        if cat != category:
            category = cat
            print(f"\n  {cat}")
        status = "PROTECTED" if blocked else "VULNERABLE"
        log = ("logged" if logged else "NOT LOGGED") if should_log else ""
        print(f"    [{status:<10}] {log:<10} {attack}")

    total = len(results)
    blocked = sum(r[2] for r in results)
    to_log = [r for r in results if r[3]]
    logged = sum(r[4] for r in to_log)
    print("\n  -------------------------------------------------------------")
    print(f"  Attacks tried            : {total}")
    print(f"  Attack prevention rate   : {blocked}/{total} = {blocked / total:.0%}"
          "   (the site was protected)")
    print(f"  Attack detection rate    : {logged}/{len(to_log)} = {logged / len(to_log):.0%}"
          "   (attacks that must appear in the security log)")
    print(f"  Time                     : {seconds:.1f} s\n")
    print("  This is an automated check of known attack types, not a full penetration")
    print("  test. A manual test with Burp Suite is still the next step.\n")
    sys.exit(0 if blocked == total and logged == len(to_log) else 1)


if __name__ == "__main__":
    main()
