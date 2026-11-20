"""Export the enriched drug data as a dataset folder (CSV files + README).

Each outside source goes in its own file under its own licence, because the
licences cannot be merged into one table (DDInter is CC BY-NC-SA 4.0,
DrugCentral is CC BY-SA 4.0). Every file is limited to the ingredients of the
products in the database, and they all join on the column `ingredient`
(normalize.moiety_key).
"""
import csv
import os

from .. import db
from .normalize import moiety_key

FILES = {
    "products.csv": "Egyptian drug list after Badeel's cleaning (one row per product).",
    "product_ingredients.csv": "Which ingredients each product contains, with strength.",
    "interactions.csv": "Drug-drug interactions between ingredients found in the products.",
    "conditions.csv": "Diseases each ingredient treats (indication) or is listed against (contraindication).",
    "leaflets.csv": "U.S. package leaflet sections for each ingredient set found in the products.",
    "patient_condition_groups.csv": "Simple condition groups used by the website, with Arabic labels.",
}


def _write(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        n = 0
        for row in rows:
            w.writerow(row)
            n += 1
    return n


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _none(value):
    return value if value not in ("", None) else None


def import_enrichment(data_dir):
    """Load interactions, conditions and leaflets from a folder written by export().

    Lets a server get the enriched data from the dataset/ folder of the
    repository instead of downloading about 3 GB of raw sources.
    """
    counts = {}
    rows = _read(os.path.join(data_dir, "interactions.csv"))
    db.execute("DELETE FROM drug_interactions")
    db.get_db().executemany(
        "INSERT OR REPLACE INTO drug_interactions (ingredient_a, ingredient_b, severity, source) "
        "VALUES (?, ?, ?, ?)",
        [(r["ingredient_a"], r["ingredient_b"], r["severity"], r["source"]) for r in rows])
    counts["interactions"] = len(rows)

    rows = _read(os.path.join(data_dir, "conditions.csv"))
    db.execute("DELETE FROM ingredient_conditions")
    db.get_db().executemany(
        "INSERT OR IGNORE INTO ingredient_conditions (ingredient, condition, relation, umls_cui, source) "
        "VALUES (?, ?, ?, ?, ?)",
        [(r["ingredient"], r["condition"], r["relation"], _none(r["umls_cui"]), r["source"]) for r in rows])
    counts["conditions"] = len(rows)

    rows = _read(os.path.join(data_dir, "leaflets.csv"))
    cols = ["ingredient_key", "brand_name", "effective_date", "set_id", "label_id", "pediatric_note",
            "min_age_months", "boxed_warning", "indications", "dosage", "contraindications",
            "pediatric", "geriatric", "pregnancy", "lactation", "warnings"]
    db.execute("DELETE FROM ingredient_labels")
    db.get_db().executemany(
        f"INSERT OR REPLACE INTO ingredient_labels (source, {', '.join(cols)}) "
        f"VALUES ('openFDA', {', '.join('?' * len(cols))})",
        [[(int(r[c]) if c == "min_age_months" and r[c] else _none(r[c])) for c in cols] for r in rows])
    counts["leaflets"] = len(rows)

    now = db.now()
    for key in ("interactions_loaded", "conditions_loaded", "labels_loaded"):
        db.set_setting(key, now + " (from dataset files)")
    db.commit()
    return counts


def export(out_dir, groups_csv):
    os.makedirs(out_dir, exist_ok=True)
    counts = {}

    drugs = db.query("SELECT * FROM drugs ORDER BY id")
    counts["products.csv"] = _write(
        os.path.join(out_dir, "products.csv"),
        ["product_id", "trade_name", "trade_name_ar", "ingredients", "strength", "form",
         "company", "drug_class", "price_egp", "pack_count", "price_per_unit_egp",
         "ingredient_key", "composition_key", "strength_known"],
        ([d["id"], d["trade_name"], d["trade_name_ar"], d["ingredients_display"],
          d["strength_display"], d["form"], d["company"], d["drug_class"], d["price"],
          d["pack_count"],
          round(d["price"] / d["pack_count"], 4) if d["price"] and d["pack_count"] else None,
          d["ingredient_key"], d["composition_key"], d["strength_known"]] for d in drugs))

    rows = db.query("SELECT di.drug_id, i.name, di.strength_value, di.strength_unit, di.strength_text "
                    "FROM drug_ingredients di JOIN ingredients i ON i.id = di.ingredient_id "
                    "ORDER BY di.drug_id, i.name")
    counts["product_ingredients.csv"] = _write(
        os.path.join(out_dir, "product_ingredients.csv"),
        ["product_id", "ingredient_name", "ingredient", "strength_value", "strength_unit", "strength_text"],
        ([r["drug_id"], r["name"], moiety_key(r["name"]), r["strength_value"], r["strength_unit"],
          r["strength_text"]] for r in rows))

    present = {moiety_key(r["name"]) for r in db.query("SELECT name FROM ingredients")}

    counts["interactions.csv"] = _write(
        os.path.join(out_dir, "interactions.csv"),
        ["ingredient_a", "ingredient_b", "severity", "source"],
        ([r["ingredient_a"], r["ingredient_b"], r["severity"], r["source"]]
         for r in db.query("SELECT * FROM drug_interactions ORDER BY ingredient_a, ingredient_b")
         if r["ingredient_a"] in present and r["ingredient_b"] in present))

    counts["conditions.csv"] = _write(
        os.path.join(out_dir, "conditions.csv"),
        ["ingredient", "condition", "relation", "umls_cui", "source"],
        ([r["ingredient"], r["condition"], r["relation"], r["umls_cui"], r["source"]]
         for r in db.query("SELECT * FROM ingredient_conditions ORDER BY ingredient, relation, condition")
         if r["ingredient"] in present))

    cols = ["ingredient_key", "brand_name", "effective_date", "set_id", "label_id",
            "pediatric_note", "min_age_months", "boxed_warning", "indications", "dosage",
            "contraindications", "pediatric", "geriatric", "pregnancy", "lactation", "warnings"]
    counts["leaflets.csv"] = _write(
        os.path.join(out_dir, "leaflets.csv"), cols,
        ([r[c] for c in cols] for r in db.query("SELECT * FROM ingredient_labels ORDER BY ingredient_key")))

    with open(groups_csv, encoding="utf-8") as src, \
            open(os.path.join(out_dir, "patient_condition_groups.csv"), "w", encoding="utf-8") as dst:
        text = src.read()
        dst.write(text)
    counts["patient_condition_groups.csv"] = text.count("\n") - 1
    return counts
