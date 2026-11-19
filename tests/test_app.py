"""Automated tests.  Run:  python -m unittest -v

Each test class gets its own temporary database, so tests never touch the
real one.
"""
import io
import os
import re
import shutil
import tempfile
import unittest

from badeel import create_app, db, security
from badeel.services import importer, recommender, search
from badeel.services.normalize import (canon_form, canon_ingredient, composition_keys,
                                       parse_composition)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASSWORD = "Test-pass-1234-long"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.app = create_app({"TESTING": True, "INSTANCE": cls.tmp,
                              "DATABASE": os.path.join(cls.tmp, "test.db")})
        with cls.app.app_context():
            with open(os.path.join(ROOT, "data", "sample_drugs.csv"), "rb") as f:
                cls.report = importer.import_csv(f.read())
            for name, email, role in [("Admin", "admin@test.local", "admin"),
                                      ("Pharm", "pharm@test.local", "pharmacist"),
                                      ("Pat", "pat@test.local", "patient")]:
                db.execute(
                    "INSERT INTO users (name, email, password_hash, role, status, created_at) "
                    "VALUES (?, ?, ?, ?, 'active', ?)",
                    (name, email, security.hash_password(PASSWORD), role, db.now()))
            db.commit()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.client = self.app.test_client()

    def token(self, path="/login"):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def login(self, email):
        return self.client.post("/login", data={
            "email": email, "password": PASSWORD, "csrf_token": self.token()})

    def drug(self, name):
        with self.app.app_context():
            return dict(db.one("SELECT * FROM drugs WHERE trade_name = ?", (name,)))


class NormalizeTests(unittest.TestCase):
    def key(self, text, strength=""):
        return composition_keys(parse_composition(text, strength))[1]

    def test_units_are_converted(self):
        self.assertEqual(self.key("Paracetamol 500 mg"), self.key("paracetamol 0.5 g"))
        self.assertEqual(self.key("X 500 mcg"), self.key("X 0.5 mg"))
        self.assertEqual(self.key("X 0,5 mg"), self.key("X 0.5 mg"))

    def test_concentration_per_ml(self):
        self.assertEqual(self.key("Ibuprofen 100 mg/5 ml"), self.key("Ibuprofen 20mg/ml"))
        self.assertNotEqual(self.key("Ibuprofen 100 mg/5 ml"), self.key("Ibuprofen 100 mg"))

    def test_aliases_and_salts(self):
        self.assertEqual(canon_ingredient("Acetaminophen"), "paracetamol")
        self.assertEqual(canon_ingredient("Amoxicillin (as trihydrate)"), "amoxicillin")
        self.assertEqual(canon_ingredient("Metformin HCl"), "metformin")
        self.assertNotEqual(canon_ingredient("Diclofenac sodium"),
                            canon_ingredient("Diclofenac potassium"))

    def test_combination_order_does_not_matter(self):
        self.assertEqual(self.key("Amoxicillin 875 mg + Clavulanic acid 125 mg"),
                         self.key("Clavulanate 125mg + Amoxycillin 875mg"))

    def test_strength_column(self):
        self.assertEqual(self.key("Paracetamol", "500 mg"), self.key("Paracetamol 500 mg"))
        self.assertEqual(self.key("Amoxicillin + Clavulanic acid", "875/125 mg"),
                         self.key("Amoxicillin 875 mg + Clavulanic acid 125 mg"))

    def test_missing_strength_is_flagged(self):
        self.assertFalse(composition_keys(parse_composition("Paracetamol"))[2])

    def test_forms(self):
        self.assertEqual(canon_form("F.C. Tabs"), "tablet")
        self.assertEqual(canon_form("أقراص"), "tablet")
        self.assertEqual(canon_form("Caplets"), "tablet")
        self.assertEqual(canon_form("Oral Suspension"), "suspension")
        self.assertEqual(canon_form("Tablets", "Glucophage XR"), "tablet (extended release)")
        self.assertNotEqual(canon_form("Tablets"), canon_form("Capsules"))


class MarketNameTests(unittest.TestCase):
    """Reading strength and form from Egyptian trade names."""

    def test_forms(self):
        from badeel.services.market_names import detect_form
        self.assertEqual(detect_form("CAPOTEN 25 MG 20 TABS."), "tablet")        # not capsules
        self.assertEqual(detect_form("EPANUTIN 100MG 50CAPS."), "capsule")
        self.assertEqual(detect_form("BRUFEN 600 MG 20 EFF. GR. IN SACHETS"), "effervescent")
        self.assertEqual(detect_form("VENLATROPE 50 MG 20 EXT.REL.TABS."),
                         "tablet (extended release)")
        self.assertEqual(detect_form("UROGILBLAD 100 MG TOP. GEL 30 SACHETS"), "gel")
        self.assertIsNone(detect_form("ALOE VERA WEISER 5 HAIR AMPOULES 10 ML"))
        self.assertIsNone(detect_form("SOME TEA 30 BAGS", "EFF"))

    def test_strengths(self):
        from badeel.services.market_names import extract_strengths as ex
        self.assertEqual(ex("BRUFEN 100MG/5ML SYRUP 150ML", 1, "syrup")["values"][0]["value"], 20)
        self.assertIsNone(ex("REGETAL CREAM 50 GM", 1, "cream"))       # 50 g is the tube
        self.assertIsNone(ex("AUGMENTIN 1 GM 14 F.C.TABS.", 2, "tablet"))  # total, not split
        self.assertEqual(ex("BREVA D3 50.000 I.U. 4 TABS.", 1, "tablet")["values"][0]["value"],
                         50000)
        combo = ex("AMILO PLUS 5/160MG 10 TAB.", 2, "tablet")
        self.assertFalse(combo["ordered"])                              # never assigned 1-by-1

    def test_combination_key_ignores_order(self):
        from badeel.services import importer
        a, _, _ = importer.validate_drug({"trade_name": "X 5/160MG 10 TAB.",
                                          "active_ingredients": "AMLODIPINE+VALSARTAN"})
        b, _, _ = importer.validate_drug({"trade_name": "Y 160/5MG 30 TAB.",
                                          "active_ingredients": "VALSARTAN+AMLODIPINE"})
        self.assertEqual(a["composition_key"], b["composition_key"])
        self.assertEqual(a["strength_known"], 1)


class RecommenderTests(Base):
    def names(self, drug_name, group="exact"):
        with self.app.app_context():
            alt = recommender.get_alternatives(self.drug(drug_name))
            return {a["trade_name"] for a in alt[group]}

    def test_sample_data_loaded(self):
        self.assertEqual(self.report["skipped"], 0, self.report["errors"])
        self.assertGreater(self.report["added"], 50)

    def test_exact_alternatives(self):
        self.assertEqual(self.names("Panadol 500"),
                         {"Abimol 500", "Paramol 500", "Cetal 500", "Pyral 500"})

    def test_combination_and_strength_are_respected(self):
        exact = self.names("Augmentin 1 g")
        self.assertEqual(exact, {"Hibiotic 1 g", "Megamox 1 g", "Curam 1 g"})
        self.assertIn("Augmentin 625", self.names("Augmentin 1 g", "related"))
        self.assertNotIn("Panadol Extra", self.names("Panadol 500"))

    def test_salt_form_and_release_differences(self):
        self.assertNotIn("Voltaren 50", self.names("Cataflam 50"))
        self.assertNotIn("Catafast 50", self.names("Cataflam 50"))
        self.assertNotIn("Glucophage XR 500", self.names("Glucophage 500"))
        self.assertIn("Cidophage 500", self.names("Glucophage 500"))

    def test_same_class_is_separate(self):
        self.assertIn("Nexium 40", self.names("Controloc 40", "same_class"))
        self.assertNotIn("Nexium 40", self.names("Controloc 40"))

    def test_available_first_then_cheapest(self):
        with self.app.app_context():
            exact = recommender.get_alternatives(self.drug("Panadol 500"))["exact"]
        self.assertEqual(exact[0]["trade_name"], "Paramol 500")      # available + cheapest
        self.assertEqual(exact[-1]["trade_name"], "Pyral 500")       # availability unknown

    def test_prices_compared_per_unit(self):
        with self.app.app_context():
            for name, price in (("Unitofen 400 MG 30 TABS.", 30), ("Packofen 400 MG 10 TABS.", 15)):
                fields, items, _ = importer.validate_drug({"trade_name": name,
                                                           "active_ingredients": "Ketoprofen",
                                                           "price": str(price)})
                importer.save_drug(fields, items)
            db.commit()
            base = dict(db.one("SELECT * FROM drugs WHERE trade_name LIKE 'Unitofen%'"))
            alt = recommender.get_alternatives(base)["exact"][0]
            self.assertEqual(alt["trade_name"], "Packofen 400 MG 10 TABS.")
            self.assertIsNone(alt["saving"])          # 15 for 10 is dearer than 30 for 30
            base = dict(db.one("SELECT * FROM drugs WHERE trade_name LIKE 'Packofen%'"))
            alt = recommender.get_alternatives(base)["exact"][0]
            self.assertEqual((alt["saving"], alt["saving_per_unit"]), (33, True))

    def test_search_handles_typos_arabic_and_aliases(self):
        with self.app.app_context():
            def top(q):
                hits = search.search(q, limit=3)
                return [db.one("SELECT trade_name FROM drugs WHERE id = ?", (i,))["trade_name"]
                        for i, _ in hits]
            self.assertIn("Augmentin", top("ogmentin")[0])
            self.assertIn("Panadol", top("بنادول")[0])
            self.assertTrue(any("Panadol" in n or "Abimol" in n or "Cetal" in n
                                for n in top("acetaminophen")))
            self.assertEqual(search.search("zzzzqqqq"), [])


class ModelTests(Base):
    def test_trained_model_ranks_and_is_safe_json(self):
        import json
        with self.app.app_context():
            data = search.train_model(log=lambda m: None, folds=3, per_kind=2)
            self.assertGreaterEqual(data["cv"]["model"]["all"]["top1"], 0.8)
            path = os.path.join(self.tmp, "search_model.json")
            with open(path, encoding="utf-8") as f:
                stored = json.load(f)                     # plain numbers, no pickle
            self.assertEqual(len(stored["coef"]), len(stored["features"]))

            def top(q):
                hit = search.search(q, limit=1)
                return db.one("SELECT trade_name FROM drugs WHERE id = ?", (hit[0][0],))["trade_name"]
            self.assertIn("Augmentin", top("ogmentin"))
            self.assertIn("Brufen 600", top("brufen 600"))      # the number decides
            self.assertIn("Panadol", top("بنادول"))
            self.assertEqual(search.search("zzzzqqqq"), [])
            os.remove(path)

    def test_admin_can_train_from_dashboard(self):
        client = self.app.test_client()
        html = client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        client.post("/login", data={"email": "admin@test.local", "password": PASSWORD,
                                    "csrf_token": token})
        self.assertIn("درّب موديل البحث", client.get("/admin/").get_data(as_text=True))
        with self.app.app_context():
            self.assertTrue(db.one("SELECT 1 FROM drugs"))


class WebTests(Base):
    def test_public_pages(self):
        for path in ("/", "/about", "/login", "/register", "/search?q=panadol",
                     f"/drug/{self.drug('Panadol 500')['id']}", "/ingredient/1"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get("/drug/999999").status_code, 404)
        self.assertEqual(len(self.client.get("/api/suggest?q=pana").get_json()) > 0, True)

    def test_language_switch(self):
        self.assertIn('dir="rtl"', self.client.get("/").get_data(as_text=True))
        self.client.get("/lang/en")
        self.assertIn('dir="ltr"', self.client.get("/").get_data(as_text=True))
        # open-redirect attempt is ignored
        r = self.client.get("/lang/ar?next=//evil.example")
        self.assertEqual(r.headers["Location"], "/")

    def test_post_without_csrf_token_is_rejected(self):
        r = self.client.post("/login", data={"email": "pat@test.local", "password": PASSWORD})
        self.assertEqual(r.status_code, 400)

    def test_sql_injection_is_harmless(self):
        r = self.client.post("/login", data={"email": "' OR '1'='1", "password": "x",
                                             "csrf_token": self.token()})
        self.assertNotEqual(r.status_code, 302)
        self.assertEqual(self.client.get("/search?q=' OR 1=1 --").status_code, 200)

    def test_html_is_escaped(self):
        html = self.client.get("/search?q=<script>alert(1)</script>").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_security_headers(self):
        r = self.client.get("/")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")

    def test_roles(self):
        self.assertEqual(self.client.get("/admin/").status_code, 302)       # not logged in
        self.login("pat@test.local")
        self.assertEqual(self.client.get("/admin/").status_code, 403)
        self.assertEqual(self.client.get("/pharmacist").status_code, 403)
        drug_id = self.drug("Brufen 400")["id"]
        r = self.client.post(f"/drug/{drug_id}/status", data={
            "availability": "shortage", "price": "1", "csrf_token": self.token("/account")})
        self.assertEqual(r.status_code, 403)

    def test_register_and_pharmacist_needs_approval(self):
        data = {"name": "New Pharm", "email": "new@test.local", "role": "pharmacist",
                "password": PASSWORD, "confirm": PASSWORD, "csrf_token": self.token("/register")}
        self.assertEqual(self.client.post("/register", data=data).status_code, 302)
        self.login("new@test.local")
        self.assertEqual(self.client.get("/account").status_code, 302)      # still not logged in
        with self.app.app_context():
            row = db.one("SELECT * FROM users WHERE email = 'new@test.local'")
            self.assertEqual(row["status"], "pending")
            self.assertNotIn(PASSWORD, row["password_hash"])                # stored as a hash

    def test_password_rules_follow_nist(self):
        from badeel import security as sec
        self.assertEqual(sec.password_problem("short-pass-12"), "short")
        self.assertEqual(sec.password_problem("passwordpassword"), "common")
        self.assertEqual(sec.password_problem("aaaaaaaaaaaaaaaa"), "common")
        self.assertEqual(sec.password_problem("mona.salem my long pass", "mona.salem@x.com"),
                         "personal")
        self.assertIsNone(sec.password_problem("tea with mint at 9 pm"))   # no forced symbols

    def test_weak_password_rejected(self):
        data = {"name": "Weak", "email": "weak@test.local", "role": "patient",
                "password": "abc", "confirm": "abc", "csrf_token": self.token("/register")}
        self.client.post("/register", data=data)
        with self.app.app_context():
            self.assertIsNone(db.one("SELECT 1 FROM users WHERE email = 'weak@test.local'"))

    def test_account_locks_after_failed_logins(self):
        with self.app.app_context():
            db.execute("INSERT INTO users (name, email, password_hash, role, status, created_at) "
                       "VALUES ('Lock', 'lock@test.local', ?, 'patient', 'active', ?)",
                       (security.hash_password(PASSWORD), db.now()))
            db.commit()
        for _ in range(security.MAX_FAILED_LOGINS):
            self.client.post("/login", data={"email": "lock@test.local", "password": "wrong-pass-1",
                                             "csrf_token": self.token()})
        r = self.login("lock@test.local")                # correct password, but locked
        self.assertNotEqual(r.status_code, 302)
        with self.app.app_context():
            self.assertTrue(db.one("SELECT 1 FROM security_events WHERE type = 'account_locked'"))

    def test_allergies_are_encrypted_and_warn(self):
        self.login("pat@test.local")
        # Without explicit consent, health data is not stored.
        self.client.post("/account", data={"action": "profile", "name": "Pat",
                                           "allergies": "Acetaminophen, Ibuprofen",
                                           "csrf_token": self.token("/account")})
        with self.app.app_context():
            self.assertIsNone(db.one("SELECT allergies_enc FROM users "
                                     "WHERE email = 'pat@test.local'")[0])
        self.client.post("/account", data={"action": "profile", "name": "Pat",
                                           "allergies": "Acetaminophen, Ibuprofen",
                                           "consent": "yes",
                                           "csrf_token": self.token("/account")})
        with self.app.app_context():
            stored = db.one("SELECT allergies_enc FROM users WHERE email = 'pat@test.local'")[0]
        self.assertNotIn("Ibuprofen", stored)
        self.assertNotIn("Acetaminophen", stored)
        html = self.client.get(f"/drug/{self.drug('Panadol 500')['id']}").get_data(as_text=True)
        self.assertIn('class="alert danger"', html)       # acetaminophen == paracetamol
        html = self.client.get(f"/drug/{self.drug('Concor 5')['id']}").get_data(as_text=True)
        self.assertNotIn('class="alert danger"', html)

    def test_favorites_and_history(self):
        self.login("pat@test.local")
        drug_id = self.drug("Concor 5")["id"]
        self.client.get("/search?q=concor")
        self.assertIn("concor", self.client.get("/history").get_data(as_text=True))
        self.client.post(f"/favorite/{drug_id}", data={"csrf_token": self.token("/account")})
        self.assertIn("Concor 5", self.client.get("/favorites").get_data(as_text=True))

    def test_pharmacist_updates_status(self):
        self.login("pharm@test.local")
        drug_id = self.drug("Marcofen 400")["id"]
        r = self.client.post(f"/drug/{drug_id}/status", data={
            "availability": "shortage", "price": "33.5", "csrf_token": self.token("/account")})
        self.assertEqual(r.status_code, 302)
        d = self.drug("Marcofen 400")
        self.assertEqual((d["availability"], d["price"]), ("shortage", 33.5))
        with self.app.app_context():
            self.assertTrue(db.one("SELECT 1 FROM audit_log WHERE action = 'drug_status'"))
        self.assertEqual(self.client.get("/admin/").status_code, 403)

    def test_admin_pages_and_drug_crud(self):
        self.login("admin@test.local")
        for path in ("/admin/", "/admin/drugs", "/admin/drugs?q=pan", "/admin/drugs/new",
                     "/admin/import", "/admin/users", "/admin/security", "/admin/audit",
                     "/admin/import/template", "/pharmacist"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        token = self.token("/account")
        r = self.client.post("/admin/drugs/new", data={
            "trade_name": "Testol 500", "active_ingredients": "Paracetamol 500mg",
            "form": "tab", "price": "9", "availability": "available", "csrf_token": token})
        self.assertEqual(r.status_code, 302)
        new = self.drug("Testol 500")
        with self.app.app_context():
            exact = recommender.get_alternatives(self.drug("Panadol 500"))["exact"]
            self.assertEqual(exact[0]["trade_name"], "Testol 500")
            self.assertTrue(search.search("testol"))            # index rebuilt itself
        self.assertEqual(self.client.get(f"/admin/drugs/{new['id']}/edit").status_code, 200)
        self.client.post(f"/admin/drugs/{new['id']}/delete", data={"csrf_token": token})
        with self.app.app_context():
            self.assertIsNone(db.one("SELECT 1 FROM drugs WHERE trade_name = 'Testol 500'"))

    def test_admin_csv_import_reports_bad_rows(self):
        self.login("admin@test.local")
        csv_text = ("Name,Generic,Dosage Form,Price\n"
                    "Importol,Cetirizine 10 mg,Tablet,11\n"
                    ",Cetirizine 10 mg,Tablet,5\n"
                    "Badprice,Cetirizine 10 mg,Tablet,abc\n")
        r = self.client.post("/admin/import", data={
            "file": (io.BytesIO(csv_text.encode()), "x.csv"), "mode": "append",
            "csrf_token": self.token("/account")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.drug("Importol")["form"], "tablet")
        with self.app.app_context():
            names = {a["trade_name"] for a in
                     recommender.get_alternatives(self.drug("Zyrtec 10"))["exact"]}
        self.assertIn("Importol", names)

    def test_admin_cannot_demote_self(self):
        self.login("admin@test.local")
        with self.app.app_context():
            admin_id = db.one("SELECT id FROM users WHERE email = 'admin@test.local'")["id"]
        self.client.post(f"/admin/users/{admin_id}", data={
            "role": "patient", "status": "active", "csrf_token": self.token("/account")})
        with self.app.app_context():
            self.assertEqual(db.one("SELECT role FROM users WHERE id = ?", (admin_id,))["role"],
                             "admin")

    def test_honeypot_records_attackers(self):
        self.assertEqual(self.client.get("/wp-login.php").status_code, 200)
        self.client.post("/wp-login.php", data={"username": "root", "password": "hunter2"})
        self.client.get("/.env")
        with self.app.app_context():
            rows = db.query("SELECT type, detail FROM security_events WHERE type LIKE 'honeypot%'")
        self.assertEqual(len(rows), 3)
        self.assertFalse(any("hunter2" in (r["detail"] or "") for r in rows))


if __name__ == "__main__":
    unittest.main()
