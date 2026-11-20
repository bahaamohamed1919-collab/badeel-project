"""Tests for the disease data (DrugCentral) and the patient's conditions.

The small extract below follows the real pg_restore output format, but the
rows are made up for the tests: they are not medical facts.
"""
import json
import os
import pathlib
import shutil
import unittest

from badeel import db, security
from badeel.services import conditions, coverage
from badeel.services.normalize import moiety_key

try:
    from tests.test_app import Base
except ImportError:
    from test_app import Base

DUMP_TEXT = "\n".join([
    "--",
    "-- Data for Name: omop_relationship; Type: TABLE DATA; Schema: public; Owner: root",
    "COPY public.omop_relationship (id, struct_id, concept_id, relationship_name, concept_name, "
    "umls_cui, snomed_full_name, cui_semantic_type, snomed_conceptid) FROM stdin;",
    "1\t10\t100\tindication\tPain\tC0030193\tPain\tT184\t22253000",
    "2\t10\t101\tcontraindication\tPeptic ulcer\tC0030920\tPeptic ulcer\tT047\t13200003",
    "3\t10\t102\tcontraindication\tKidney disease\tC0022658\tKidney disease\tT047\t\\N",
    "4\t20\t103\tindication\tDiabetes mellitus type 2\tC0011860\tDM2\tT047\t44054006",
    "5\t30\t104\tdiagnosis\tSomething\tC1\tx\tT0\t\\N",
    "6\t40\t105\tcontraindication\tHyperkalemia\tC0020461\tHyperkalemia\tT047\t\\N",
    "\\.",
    "",
    "COPY public.synonyms (syn_id, id, name, preferred_name, parent_id, lname) FROM stdin;",
    "1\t10\tibuprofen\t1\t\\N\tibuprofen",
    "2\t10\tIbuprofen sodium\t\\N\t\\N\tibuprofen sodium",
    "3\t20\tmetformin hydrochloride\t1\t\\N\tmetformin hydrochloride",
    "4\t40\tpotassium chloride\t1\t\\N\tpotassium chloride",
    "\\.",
])


class ConditionTests(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dump = os.path.join(cls.tmp, "drugcentral_extract.sql")
        pathlib.Path(cls.dump).write_text(DUMP_TEXT, encoding="utf-8")
        with cls.app.app_context():
            cls.load = conditions.load_drugcentral([cls.dump])

    def test_parse_and_load(self):
        # diagnosis rows are ignored; both names of struct 10 give "ibuprofen"
        self.assertEqual(self.load, {"relations": 5, "ingredients": 3, "conditions": 5})
        with self.app.app_context():
            uses = conditions.for_drug(self.drug("Brufen 400"))
            self.assertEqual(uses["indication"], ["Pain"])
            self.assertEqual(uses["contraindication"], ["Kidney disease", "Peptic ulcer"])
            self.assertEqual(conditions.for_drug(self.drug("Glucophage 500"))["indication"],
                             ["Diabetes mellitus type 2"])

    def test_sodium_and_potassium_chloride_stay_apart(self):
        self.assertEqual(moiety_key("potassium chloride"), "potassium chloride")
        self.assertNotEqual(moiety_key("sodium chloride"), moiety_key("potassium chloride"))

    def test_null_values(self):
        tables = conditions.parse_copy_blocks(DUMP_TEXT)
        self.assertIsNone(tables["omop_relationship"][2][8])
        self.assertEqual(len(tables["synonyms"]), 4)

    def test_wrong_file_rejected(self):
        bad = os.path.join(self.tmp, "bad.sql")
        pathlib.Path(bad).write_text("nothing here", encoding="utf-8")
        with self.app.app_context(), self.assertRaises(ValueError):
            conditions.load_drugcentral([bad])

    def test_groups_cover_real_terms(self):
        self.assertIn("pregnancy", conditions.GROUPS)
        self.assertEqual(conditions.CONCEPT_TO_GROUP["Peptic ulcer"]["key"], "ulcer")
        for g in conditions.GROUPS.values():
            self.assertTrue(g["ar"] and g["en"] and g["concepts"], g["key"])

    def test_patient_conditions_need_consent_and_are_encrypted(self):
        self.login("pat@test.local")
        data = {"action": "profile", "name": "Pat", "conditions": ["ulcer", "kidney"],
                "csrf_token": self.token("/account")}
        self.client.post("/account", data=data)
        with self.app.app_context():
            row = db.one("SELECT conditions_enc FROM users WHERE email = 'pat@test.local'")
            self.assertIsNone(row["conditions_enc"])            # refused without consent
        data.update(consent="yes", csrf_token=self.token("/account"))
        self.client.post("/account", data=data)
        with self.app.app_context():
            row = db.one("SELECT * FROM users WHERE email = 'pat@test.local'")
            self.assertNotIn("ulcer", row["conditions_enc"])    # not readable in the database
            self.assertEqual(json.loads(security.decrypt(row["conditions_enc"])), ["ulcer", "kidney"])
            log = db.one("SELECT detail FROM audit_log WHERE action = 'profile_saved' "
                         "ORDER BY id DESC LIMIT 1")["detail"]
            self.assertNotIn("ulcer", log)                      # the log never names them

        html = self.client.get(f"/drug/{self.drug('Brufen 400')['id']}").get_data(as_text=True)
        self.assertIn('id="condition-warning"', html)
        self.assertIn("قرحة في المعدة", html)
        self.assertIn("أمراض الكلى", html)
        html = self.client.get(f"/drug/{self.drug('Zyrtec 10')['id']}").get_data(as_text=True)
        self.assertNotIn('id="condition-warning"', html)

        # unticking everything deletes the conditions
        self.client.post("/account", data={"action": "profile", "name": "Pat", "consent": "yes",
                                           "csrf_token": self.token("/account")})
        with self.app.app_context():
            row = db.one("SELECT conditions_enc FROM users WHERE email = 'pat@test.local'")
            self.assertIsNone(row["conditions_enc"])

    def test_unknown_group_is_ignored(self):
        self.login("pharm@test.local")
        self.client.post("/account", data={"action": "profile", "name": "Pharm", "consent": "yes",
                                           "conditions": ["<script>", "diabetes"],
                                           "csrf_token": self.token("/account")})
        with self.app.app_context():
            row = db.one("SELECT conditions_enc FROM users WHERE email = 'pharm@test.local'")
            self.assertEqual(json.loads(security.decrypt(row["conditions_enc"])), ["diabetes"])

    def test_visitor_sees_uses_not_warning(self):
        html = self.client.get(f"/drug/{self.drug('Brufen 400')['id']}").get_data(as_text=True)
        self.assertIn('id="h-uses"', html)
        self.assertIn("Pain", html)
        self.assertNotIn('id="condition-warning"', html)

    def test_disease_page(self):
        html = self.client.get("/disease?group=diabetes").get_data(as_text=True)
        self.assertIn("Glucophage 500", html)
        self.assertIn("Metformin", html)
        self.assertEqual(self.client.get("/disease?name=Pain").status_code, 200)
        self.assertEqual(self.client.get("/disease").status_code, 404)

    def test_coverage_numbers(self):
        with self.app.app_context():
            r = coverage.report()
            self.assertEqual(r["condition_rows"], 5)
            self.assertGreater(r["products_with_contraindication"], 0)
            self.assertIn("DrugCentral diseases", coverage.as_text(r))

    @unittest.skipUnless(shutil.which("pg_restore"), "pg_restore not installed")
    def test_missing_dump_file_reports_error(self):
        with self.app.app_context(), self.assertRaises(Exception):
            conditions.load_drugcentral([os.path.join(self.tmp, "missing.pgdump")])
