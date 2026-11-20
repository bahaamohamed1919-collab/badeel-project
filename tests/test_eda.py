"""Tests for the EDA cross-check (name matching, comparison, scoring)."""
import csv
import io
import os
import sys
import unittest

from badeel.services import eda

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "checks"))
import verification_score  # noqa: E402


def row(trade, active, strength=""):
    return {"trade_name": trade, "active": active, "strength": strength, "text": f"{trade} {active}"}


class BrandTests(unittest.TestCase):
    def test_brand_ignores_strength_pack_and_marks(self):
        self.assertEqual(eda.brand("CONTROLOC 20MG 14 TAB."), "controloc")
        self.assertEqual(eda.brand("Controloc 20 mg"), "controloc")
        self.assertEqual(eda.brand("Buscopan®"), "buscopan")
        self.assertEqual(eda.brand("MEGAFEN-N 100MG/5ML SUSP."), "megafen n")


class IngredientTests(unittest.TestCase):
    def test_salt_and_synonym(self):
        text = "Pantoprazole sesquihydrate 22.55 mg equivalent to Pantoprazole 20 mg"
        self.assertEqual(eda.ingredient_found("Pantoprazole", text), "agree")
        self.assertEqual(eda.ingredient_found("Paracetamol", "Acetaminophen Oral Syrup 160 mg / 5 ml"), "agree")

    def test_vitamin_names_with_extra_words(self):
        text = "Vitamin B1 /Vitamin B6 /Vitamin B12 Film coated tablets 100 mg"
        for name in ("Thiamine", "Pyridoxine", "Cyanocobalamin"):
            self.assertEqual(eda.ingredient_found(name, text), "agree", name)

    def test_spelling_is_separated(self):
        self.assertEqual(eda.ingredient_found("Phenylepherine", "Paracetamol /Phenylephrine Hydrochloride"),
                         "spelling")
        self.assertEqual(eda.ingredient_found("Sodium Bicarbonte", "Citric Acid /Sodium Bicarbonate"),
                         "spelling")

    def test_different_ingredient(self):
        self.assertEqual(eda.ingredient_found("Ibuprofen", "Paracetamol 500 mg"), "differ")


class CompareTests(unittest.TestCase):
    def test_same_product(self):
        r = eda.compare(row("Panadol 500 mg", "Paracetamol 500 mg Film coated tablets", "500 mg"),
                        {"form": "tablet"}, [("Paracetamol", 500.0, "mg")])
        self.assertEqual(r, {"ingredients": "agree", "strength": "agree"})

    def test_strength_differs(self):
        r = eda.compare(row("Panadol 500 mg", "Paracetamol 500 mg tablets", "500 mg"),
                        {"form": "tablet"}, [("Paracetamol", 1000.0, "mg")])
        self.assertEqual(r["strength"], "differ")

    def test_other_form_is_not_compared(self):
        r = eda.compare(row("Zyrtec", "Cetirizine dihydrochloride Oral drops 10 mg/ml", "10 mg/ml"),
                        {"form": "syrup"}, [("Cetirizine", 1.0, "mg/ml")])
        self.assertEqual(r["strength"], "other form")

    def test_unit_conversion(self):
        self.assertIn((500.0, "mg"), eda.strengths_in("0.5 g"))
        self.assertIn((20.0, "mg/ml"), eda.strengths_in("100 mg / 5 ml"))


class ScoreTests(unittest.TestCase):
    def test_wilson_interval(self):
        lo, hi = verification_score.wilson(95, 100)
        self.assertAlmostEqual(lo, 0.888, places=2)
        self.assertAlmostEqual(hi, 0.978, places=2)
        self.assertEqual(verification_score.wilson(0, 0), (0.0, 0.0))

    def test_sample_scoring(self):
        text = ("sample_no,found_in_eda (yes/no),name_ok (yes/no),ingredients_ok (yes/no),"
                "strength_ok (yes/no),form_ok (yes/no),price_ok (yes/no)\n"
                "1,yes,yes,yes,no,yes,\n2,yes,yes,yes,yes,yes,yes\n3,no,,,,,\n4,,,,,,\n")
        lines = verification_score.score_sample(list(csv.DictReader(io.StringIO(text))))
        joined = "\n".join(lines)
        self.assertIn("found in EDA records      : 2 of 3", joined)
        self.assertIn("strength correct          : 1 of 2", joined)
        self.assertIn("price correct             : 1 of 1", joined)

    def test_review_scoring_waits_for_review(self):
        header = "eda_trade_name,badeel_trade_name,status,reviewer_verdict (x)\n"
        text = header + "A,A1,NEEDS REVIEW,\nB,B1,,\n"
        joined = "\n".join(verification_score.score_eda_review(list(csv.DictReader(io.StringIO(text)))))
        self.assertIn("finish the review first", joined)
        text = header + "A,A1,NEEDS REVIEW,badeel_wrong\nB,B1,,\nC,C1,NEEDS REVIEW,correct\n"
        joined = "\n".join(verification_score.score_eda_review(list(csv.DictReader(io.StringIO(text)))))
        self.assertIn("matched products correct  : 2 of 3", joined)
