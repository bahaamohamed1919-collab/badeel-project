"""Tests for the outside data sources (DDInter interactions, openFDA leaflets).

The small files written here follow the real file formats, but their contents
are made up for the tests: the severities and leaflet texts below are not
medical facts.
"""
import json
import os
import pathlib
import tempfile
import zipfile

from badeel import db
from badeel.services import coverage, interactions, labels, sources
from badeel.services.normalize import moiety_key, moiety_set_key

try:                                   # python -m unittest (from the project folder)
    from tests.test_app import Base
except ImportError:                    # python -m unittest discover -s tests
    from test_app import Base

DDINTER_CSV = (
    "DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level\n"
    "DDInter1,Ibuprofen,DDInter2,Acetylsalicylic acid,Moderate\n"
    "DDInter2,Acetylsalicylic acid,DDInter1,Ibuprofen,Major\n"        # same pair again
    "DDInter3,Diclofenac,DDInter4,Metformin,Minor\n"
    "DDInter5,Ciprofloxacin,DDInter6,Unlisteddrug,Unknown\n"
    "DDInter1,Ibuprofen,DDInter1,Ibuprofen,Major\n"                   # same drug: ignored
)


def leaflet(substances, effective, dosage=True, pediatric=None, brand="BRAND"):
    record = {
        "id": f"id-{effective}", "set_id": f"set-{effective}", "effective_time": effective,
        "openfda": {"substance_name": substances, "brand_name": [brand]},
        "indications_and_usage": ["1 INDICATIONS AND USAGE Test indication text."],
    }
    if dosage:
        record["dosage_and_administration"] = ["2 DOSAGE AND ADMINISTRATION Test dose text."]
    if pediatric:
        record["pediatric_use"] = [pediatric]
    return record


class MatchingTests(Base):
    def test_moiety_key_removes_salts_and_uses_aliases(self):
        self.assertEqual(moiety_key("Diclofenac Sodium"), "diclofenac")
        self.assertEqual(moiety_key("DICLOFENAC POTASSIUM"), "diclofenac")
        self.assertEqual(moiety_key("Metformin hydrochloride"), "metformin")
        self.assertEqual(moiety_key("Amoxicillin trihydrate"), "amoxicillin")
        self.assertEqual(moiety_key("Clavulanate potassium"), "clavulanic acid")
        self.assertEqual(moiety_key("Acetaminophen"), "paracetamol")
        self.assertEqual(moiety_key("sodium"), "sodium")                  # never emptied
        self.assertEqual(moiety_set_key(["Clavulanate Potassium", "AMOXICILLIN"]),
                         "amoxicillin|clavulanic acid")


class InteractionTests(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.csv = os.path.join(cls.tmp, "ddinter_downloads_code_M.csv")
        pathlib.Path(cls.csv).write_text(DDINTER_CSV, encoding="utf-8")
        with cls.app.app_context():
            cls.load = interactions.load_ddinter([cls.csv])

    def test_load_keeps_highest_severity_and_skips_self_pairs(self):
        self.assertEqual(self.load, {"rows_read": 4, "pairs": 3})
        with self.app.app_context():
            hits = interactions.between({"ibuprofen"}, {"acetylsalicylic acid"})
            self.assertEqual([h["severity"] for h in hits], ["major"])
            # the lookup works in both directions
            self.assertEqual(len(interactions.between({"acetylsalicylic acid"}, {"ibuprofen"})), 1)

    def test_salts_match_ddinter_names(self):
        with self.app.app_context():
            d = self.drug("Cataflam 50")            # diclofenac potassium
            self.assertEqual(interactions.drug_moieties(d), {"diclofenac"})
            self.assertEqual(interactions.count_for(d), 1)

    def test_reloading_replaces_rows(self):
        with self.app.app_context():
            again = interactions.load_ddinter([self.csv])
            self.assertEqual(again["pairs"], 3)
            self.assertEqual(db.one("SELECT COUNT(*) AS n FROM drug_interactions")["n"], 3)

    def test_rejects_wrong_file(self):
        with self.assertRaises(ValueError):
            list(interactions.parse_ddinter("name,price\nx,1\n"))

    def test_warning_for_saved_medicine(self):
        brufen, aspirin = self.drug("Brufen 400"), self.drug("Aspocid 75")
        self.login("pat@test.local")
        self.client.post(f"/favorite/{aspirin['id']}",
                         data={"csrf_token": self.token(f"/drug/{aspirin['id']}")})
        html = self.client.get(f"/drug/{brufen['id']}").get_data(as_text=True)
        self.assertIn('id="interactions"', html)
        self.assertIn("Aspocid 75", html)
        self.assertIn("sev-major", html)
        # a product with no interaction against the saved medicine shows no warning
        html = self.client.get(f"/drug/{self.drug('Zyrtec 10')['id']}").get_data(as_text=True)
        self.assertNotIn('id="interactions"', html)

    def test_visitor_sees_count_not_warning(self):
        html = self.client.get(f"/drug/{self.drug('Brufen 400')['id']}").get_data(as_text=True)
        self.assertNotIn('id="interactions"', html)
        self.assertIn("يوجد 1 تداخل دوائي مسجل", html)


class PediatricRuleTests(Base):
    def test_age_limit_in_years_and_months(self):
        self.assertEqual(labels.pediatric_note(
            "Safety and effectiveness in pediatric patients below the age of 6 months have "
            "not been established."), ("min_age", 6))
        self.assertEqual(labels.pediatric_note(
            "Safety and effectiveness in pediatric patients younger than 12 years of age "
            "have not been established."), ("min_age", 144))
        self.assertEqual(labels.pediatric_note(
            "This drug is not recommended for use in children under 2 years."), ("min_age", 24))

    def test_stricter_limit_wins(self):
        self.assertEqual(labels.pediatric_note(
            "Not recommended in children under 6 months. Safety and effectiveness in pediatric "
            "patients less than 2 years have not been established."), ("min_age", 24))

    def test_not_established_and_unknown(self):
        self.assertEqual(labels.pediatric_note(
            "Safety and effectiveness in pediatric patients have not been established."),
            ("not_established", None))
        self.assertEqual(labels.pediatric_note("Use in children is described in section 2."),
                         (None, None))
        self.assertEqual(labels.pediatric_note(None), (None, None))


class LeafletTests(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        records = [
            leaflet(["IBUPROFEN"], "20200101"),
            leaflet(["IBUPROFEN"], "20240101", pediatric=(
                "Safety and effectiveness in pediatric patients below the age of 6 months "
                "have not been established."), brand="NEWER"),
            leaflet(["IBUPROFEN"], "20250101", dosage=False),         # newest but incomplete
            leaflet(["AMOXICILLIN", "CLAVULANATE POTASSIUM"], "20230101", brand="COMBO"),
            leaflet(["NOT IN EGYPT LIST"], "20230101"),
            {"id": "no-openfda", "indications_and_usage": ["x"]},     # cannot be matched
        ]
        cls.zip = os.path.join(cls.tmp, "drug-label-0001-of-0001.json.zip")
        with zipfile.ZipFile(cls.zip, "w") as z:
            z.writestr("drug-label-0001-of-0001.json", json.dumps({"results": records}))
        with cls.app.app_context():
            cls.load = labels.load_openfda([cls.zip], log=lambda m: None)

    def test_best_leaflet_kept_per_ingredient_set(self):
        self.assertEqual(self.load, {"leaflets_read": 6, "ingredient_sets": 2})
        with self.app.app_context():
            row = labels.for_drug(self.drug("Brufen 400"))
            self.assertEqual(row["brand_name"], "NEWER")
            self.assertEqual((row["pediatric_note"], row["min_age_months"]), ("min_age", 6))
            combo = labels.for_drug(self.drug("Augmentin 1 g"))
            self.assertEqual(combo["brand_name"], "COMBO")

    def test_combination_never_uses_single_leaflet(self):
        with self.app.app_context():
            # paracetamol + caffeine has no leaflet even though other sets do
            self.assertIsNone(labels.for_drug(self.drug("Panadol Extra")))

    def test_drug_page_shows_leaflet_with_disclaimer(self):
        html = self.client.get(f"/drug/{self.drug('Brufen 400')['id']}").get_data(as_text=True)
        self.assertIn('id="h-leaflet"', html)
        self.assertIn("بديل لا يحدد الجرعات", html)
        self.assertIn("Test dose text", html)
        self.assertIn("dailymed.nlm.nih.gov", html)
        self.assertIn("6 شهر", html)
        html = self.client.get(f"/drug/{self.drug('Panadol Extra')['id']}").get_data(as_text=True)
        self.assertNotIn('id="h-leaflet"', html)

    def test_leaflet_text_is_escaped(self):
        with self.app.app_context():
            db.execute("UPDATE ingredient_labels SET indications = '<script>alert(1)</script>' "
                       "WHERE ingredient_key = 'ibuprofen'")
            db.commit()
        html = self.client.get(f"/drug/{self.drug('Brufen 400')['id']}").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;", html)

    def test_coverage_report(self):
        with self.app.app_context():
            r = coverage.report()
            self.assertEqual(r["ingredient_sets_with_leaflet"], 2)
            self.assertGreater(r["products_with_leaflet"], 0)
            self.assertIn("openFDA leaflets", coverage.as_text(r))


class DownloadTests(Base):
    """The download code, run against local files instead of the internet."""

    def test_fetch_ddinter_and_openfda(self):
        with tempfile.TemporaryDirectory() as site, tempfile.TemporaryDirectory() as raw:
            for code in sources.DDINTER_CODES:
                pathlib.Path(site, f"ddinter_downloads_code_{code}.csv").write_text(
                    DDINTER_CSV, encoding="utf-8")
            paths = sources.fetch_ddinter(pathlib.Path(site).as_uri(), raw, log=lambda m: None)
            self.assertEqual(len(paths), len(sources.DDINTER_CODES))
            source = json.loads(pathlib.Path(paths[0]).with_name("SOURCE.json").read_text())
            self.assertEqual(source["source"], "DDInter")
            self.assertIn("licence", source)

            part = pathlib.Path(site, "drug-label-0001-of-0001.json.zip")
            with zipfile.ZipFile(part, "w") as z:
                z.writestr("p.json", json.dumps({"results": [leaflet(["IBUPROFEN"], "20240101")]}))
            index = pathlib.Path(site, "download.json")
            index.write_text(json.dumps({"results": {"drug": {"label": {
                "partitions": [{"file": part.as_uri()}]}}}}))
            paths = sources.fetch_openfda_labels(index.as_uri(), raw, log=lambda m: None)
            self.assertEqual([pathlib.Path(p).name for p in paths], [part.name])
            # a second run uses the files already downloaded
            self.assertEqual(sources.fetch_openfda_labels(index.as_uri(), raw, log=lambda m: None),
                             paths)
