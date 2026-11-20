"""Tests for running behind a hosting proxy and for setting a server up from dataset files."""
import argparse
import json
import os
import shutil
import tempfile

from badeel import create_app, db
from badeel.services import export, interactions

try:
    from tests.test_app import Base
except ImportError:
    from test_app import Base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def last_failed_login_ip(app):
    with app.app_context():
        return db.one("SELECT ip FROM security_events WHERE type = 'login_failed' "
                      "ORDER BY id DESC LIMIT 1")["ip"]


class ProxyTests(Base):
    def _try_login(self, client):
        import re
        html = client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        client.post("/login", data={"email": "nobody@test.local", "password": "wrong-password-123456",
                                    "csrf_token": token},
                    headers={"X-Forwarded-For": "203.0.113.9"})

    def test_header_ignored_by_default(self):
        self._try_login(self.app.test_client())
        self.assertEqual(last_failed_login_ip(self.app), "127.0.0.1")   # the header cannot be faked

    def test_header_used_behind_proxy(self):
        tmp = tempfile.mkdtemp()
        try:
            app = create_app({"TESTING": True, "INSTANCE": tmp, "DATABASE": os.path.join(tmp, "t.db"),
                              "TRUST_PROXY": True})
            self._try_login(app.test_client())
            self.assertEqual(last_failed_login_ip(app), "203.0.113.9")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_public_notice(self):
        self.assertNotIn("notice-bar", self.client.get("/").get_data(as_text=True))
        tmp = tempfile.mkdtemp()
        try:
            app = create_app({"TESTING": True, "INSTANCE": tmp, "DATABASE": os.path.join(tmp, "t.db"),
                              "PUBLIC_NOTICE": True})
            self.assertIn("notice-bar", app.test_client().get("/").get_data(as_text=True))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ImportEnrichmentTests(Base):
    def test_round_trip(self):
        with self.app.app_context():
            db.execute("INSERT INTO drug_interactions VALUES ('ibuprofen', 'acetylsalicylic acid', 'major', 'DDInter')")
            db.execute("INSERT INTO ingredient_conditions VALUES ('ibuprofen', 'Peptic ulcer', 'contraindication', 'C1', 'DrugCentral')")
            db.execute("INSERT INTO ingredient_labels (ingredient_key, source, brand_name, dosage, pediatric_note, min_age_months) "
                       "VALUES ('ibuprofen', 'openFDA', 'X', 'Take one', 'min_age', 6)")
            db.commit()
            with tempfile.TemporaryDirectory() as out:
                export.export(out, os.path.join(ROOT, "data", "patient_conditions.csv"))
                for t in ("drug_interactions", "ingredient_conditions", "ingredient_labels"):
                    db.execute(f"DELETE FROM {t}")
                db.commit()
                counts = export.import_enrichment(out)
            self.assertEqual(counts, {"interactions": 1, "conditions": 1, "leaflets": 1})
            self.assertEqual(interactions.between({"ibuprofen"}, {"acetylsalicylic acid"})[0]["severity"], "major")
            row = db.one("SELECT * FROM ingredient_labels WHERE ingredient_key = 'ibuprofen'")
            self.assertEqual((row["min_age_months"], row["dosage"], row["boxed_warning"]), (6, "Take one", None))


class InstallModelTests(Base):
    def test_rejects_files_that_are_not_a_model(self):
        import sys
        sys.path.insert(0, ROOT)
        import manage
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"features": ["x"], "coef": [1]}, f)
        try:
            with self.app.app_context(), self.assertRaises(SystemExit):
                manage.cmd_install_model(argparse.Namespace(file=f.name))
        finally:
            os.unlink(f.name)
