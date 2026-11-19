"""Package leaflet information (from openFDA drug labels).

openFDA publishes the U.S. package leaflets (structured product labels) as
JSON, one record per leaflet, with one field per section:
    indications_and_usage, dosage_and_administration, pediatric_use, ...

Badeel keeps one leaflet per set of active ingredients, so the leaflet for
"ibuprofen" is shown on every Egyptian ibuprofen product. The leaflet is
shown as information to read with a pharmacist: Badeel never works out a
dose for a patient.
"""
import json
import math
import re
import zipfile

from .. import db
from .normalize import moiety_set_key

MAX_SECTION = 20000

# Badeel column -> openFDA fields, first one present wins
# (prescription leaflets first, then the "Drug Facts" fields of OTC leaflets).
SECTIONS = {
    "indications": ["indications_and_usage", "purpose"],
    "dosage": ["dosage_and_administration"],
    "pediatric": ["pediatric_use"],
    "geriatric": ["geriatric_use"],
    "pregnancy": ["pregnancy", "pregnancy_or_breast_feeding"],
    "lactation": ["lactation", "nursing_mothers"],
    "contraindications": ["contraindications", "do_not_use"],
    "warnings": ["warnings_and_cautions", "warnings", "precautions"],
    "boxed_warning": ["boxed_warning"],
}

SECTION_LABELS = [
    ("boxed_warning", "Boxed warning", "تحذير مهم (في إطار)"),
    ("indications", "What it is used for", "دواعي الاستعمال"),
    ("dosage", "Dosage in the leaflet", "الجرعة كما في النشرة"),
    ("contraindications", "Do not use (contraindications)", "موانع الاستعمال"),
    ("pediatric", "Children", "الأطفال"),
    ("geriatric", "Older adults", "كبار السن"),
    ("pregnancy", "Pregnancy", "الحمل"),
    ("lactation", "Breastfeeding", "الرضاعة"),
    ("warnings", "Warnings and precautions", "التحذيرات والاحتياطات"),
]


def _text(record, fields):
    for field in fields:
        value = record.get(field)
        if value:
            text = " ".join(value) if isinstance(value, list) else str(value)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:MAX_SECTION]
    return None


def label_ingredients(record):
    """Active ingredient names of a leaflet."""
    openfda = record.get("openfda") or {}
    names = openfda.get("substance_name")
    if not names:
        names = []
        for generic in openfda.get("generic_name") or []:
            names += re.split(r"\s+and\s+|\s*,\s*", generic, flags=re.I)
    return [n for n in names if n and n.strip()]


# --------------------------------------------------------------- age
_AGE = r"(\d+(?:\.\d+)?)\s*(years?|months?|weeks?|days?)"
_SAFETY = r"(?:safety and (?:effectiveness|efficacy)|effectiveness and safety|safety and efficacy)"
_BELOW = r"(?:below|under|younger than|less than)\s+(?:the age of\s+)?"
_NOT_EST_AGE = re.compile(
    _SAFETY + r"[^.]{0,120}?(?:pediatric patients|children|infants)[^.]{0,40}?"
    + _BELOW + _AGE + r"[^.]{0,80}?(?:have|has) not been established")
_NOT_REC_AGE = re.compile(
    r"not recommended (?:for use )?in (?:pediatric patients|children|infants)[^.]{0,20}?"
    + _BELOW + _AGE)
_NOT_EST = re.compile(
    _SAFETY + r"[^.]{0,120}?(?:pediatric patients|children)[^.]{0,40}?(?:have|has) not been established")


def _months(number, unit):
    n = float(number)
    if unit.startswith("year"):
        return int(round(n * 12))
    if unit.startswith("week"):
        return int(math.ceil(n / 4.345))
    if unit.startswith("day"):
        return int(math.ceil(n / 30.44))
    return int(round(n))


def pediatric_note(text):
    """Read the children section of a leaflet.

    Returns (note, min_age_months):
      ('min_age', 72)          the leaflet gives an age below which use is not
                               established or not recommended (here 6 years);
      ('not_established', None) safety in children is not established at all;
      (None, None)             nothing that these rules recognise.
    Only fixed sentence patterns of U.S. leaflets are read, so a None result
    does not mean the medicine is safe for children.
    """
    if not text:
        return None, None
    t = re.sub(r"\s+", " ", text.lower())
    ages = [_months(n, u) for n, u in _NOT_EST_AGE.findall(t) + _NOT_REC_AGE.findall(t)]
    if ages:
        return "min_age", max(ages)      # the stricter limit when several are given
    if _NOT_EST.search(t):
        return "not_established", None
    return None, None


# ------------------------------------------------------------ loading
def parse_label(record):
    names = label_ingredients(record)
    if not names:
        return None
    row = {col: _text(record, fields) for col, fields in SECTIONS.items()}
    openfda = record.get("openfda") or {}
    row.update(
        ingredient_key=moiety_set_key(names),
        label_id=record.get("id"),
        set_id=record.get("set_id"),
        effective_date=record.get("effective_time"),
        brand_name=(openfda.get("brand_name") or [None])[0],
    )
    row["pediatric_note"], row["min_age_months"] = pediatric_note(row["pediatric"])
    return row


def _score(row):
    """Prefer complete leaflets, then the most recent one."""
    return (bool(row["dosage"]), bool(row["indications"]), bool(row["pediatric"]),
            row["effective_date"] or "")


def _records(path):
    """openFDA files are zipped JSON ({"results": [...]}); plain .json also works."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for member in z.namelist():
                if member.endswith(".json"):
                    with z.open(member) as f:
                        yield from json.load(f).get("results", [])
    else:
        with open(path, encoding="utf-8") as f:
            yield from json.load(f).get("results", [])


def wanted_keys():
    """Ingredient sets of the products in the database."""
    return {moiety_set_key(r["ingredient_key"].split("|"))
            for r in db.query("SELECT DISTINCT ingredient_key FROM drugs")}


def load_openfda(paths, only_wanted=True, log=print):
    """Keep the best leaflet for each ingredient set found in the drug list."""
    wanted = wanted_keys() if only_wanted else None
    best, read = {}, 0
    for path in paths:
        for record in _records(path):
            read += 1
            row = parse_label(record)
            if not row or (wanted is not None and row["ingredient_key"] not in wanted):
                continue
            current = best.get(row["ingredient_key"])
            if current is None or _score(row) > _score(current):
                best[row["ingredient_key"]] = row
        log(f"  {path}: {read} leaflets read, {len(best)} ingredient sets kept")
    columns = ["ingredient_key", "label_id", "set_id", "effective_date", "brand_name",
               *SECTIONS, "pediatric_note", "min_age_months"]
    db.execute("DELETE FROM ingredient_labels WHERE source = 'openFDA'")
    db.get_db().executemany(
        f"INSERT OR REPLACE INTO ingredient_labels (source, {', '.join(columns)}) "
        f"VALUES ('openFDA', {', '.join('?' * len(columns))})",
        [[row[c] for c in columns] for row in best.values()])
    db.set_setting("labels_loaded", db.now())
    db.commit()
    return {"leaflets_read": read, "ingredient_sets": len(best)}


def for_drug(drug):
    """The leaflet for exactly this product's set of ingredients, or None.
    A combination product never falls back to a single-ingredient leaflet."""
    key = moiety_set_key(drug["ingredient_key"].split("|"))
    return db.one("SELECT * FROM ingredient_labels WHERE ingredient_key = ?", (key,))
