"""Validating and saving drugs — used by the admin form and by CSV import.

Both paths go through validate_drug() and save_drug(), so a drug typed by
hand and a drug from a 20,000-row file are checked by exactly the same rules.
"""
import csv
import io

from .. import db
from . import market_names
from .normalize import (canon_form, composition_keys, display_name, norm_text,
                        parse_composition)

# Accepted spellings of each column header, so the team's real dataset can be
# imported even if its headers are named differently.
COLUMN_ALIASES = {
    "trade_name": ["trade_name", "name", "tradename", "brand", "brand_name", "drug_name",
                   "drugname", "product", "commercial_name", "commercial_name_en", "name_en",
                   "الاسم", "الاسم التجاري"],
    "trade_name_ar": ["trade_name_ar", "name_ar", "arabic_name", "arabic", "commercial_name_ar",
                      "الاسم بالعربي"],
    "active_ingredients": ["active_ingredients", "active_ingredient", "activeingredient",
                           "ingredients", "ingredient", "generic", "generic_name",
                           "scientific_name", "composition", "active", "المادة الفعالة"],
    "strength": ["strength", "concentration", "dose", "dosage", "التركيز"],
    "form": ["form", "dosage_form", "pharmaceutical_form", "type", "الشكل", "الشكل الدوائي"],
    "company": ["company", "manufacturer", "producer", "الشركة"],
    "price": ["price", "new_price", "price_egp", "السعر"],
    "route": ["route", "route_of_administration", "طريقة الاستخدام"],
    "pack_count": ["pack_count", "pack", "pack_size", "units_per_pack", "عدد الوحدات"],
    "drug_class": ["drug_class", "class", "category", "group", "therapeutic_class", "التصنيف"],
    "availability": ["availability", "status", "available", "التوافر"],
    "country": ["country", "market", "الدولة"],
}

_AVAILABILITY = {
    "available": "available", "yes": "available", "1": "available", "true": "available",
    "in stock": "available", "متوفر": "available",
    "shortage": "shortage", "no": "shortage", "0": "shortage", "false": "shortage",
    "out of stock": "shortage", "unavailable": "shortage", "ناقص": "shortage",
    "غير متوفر": "shortage",
    "": "unknown", "unknown": "unknown", "غير معروف": "unknown",
}


def validate_drug(raw):
    """Check one drug. Returns (fields, ingredients, error_message)."""
    get = lambda k: (raw.get(k) or "").strip()
    trade_name = get("trade_name")
    if not trade_name:
        return None, None, "trade_name is empty"
    if len(trade_name) > 150:
        return None, None, "trade_name is too long"

    items = parse_composition(get("active_ingredients"), get("strength"))
    if not items:
        return None, None, "active_ingredients is empty or unreadable"

    # The form comes from its own column; if there is none (Egyptian market
    # lists), it is read from the trade name, then from the route column.
    form_raw = get("form")
    if form_raw:
        form = canon_form(form_raw, trade_name)
    else:
        form = market_names.detect_form(trade_name, get("route"))
        form_raw = get("route") or None
    if not form:
        form = "unspecified"

    # Strength missing next to the ingredients and no strength column:
    # try the trade name ("CILOMEPATAL 100MG 20 TAB.").
    pack_strengths = None
    if all(i["value"] is None for i in items) and not get("strength") and form != "unspecified":
        found = market_names.extract_strengths(trade_name, len(items), form)
        if found and found["ordered"]:
            st = found["values"][0]
            items[0].update(value=st["value"], unit=st["unit"], text=st["text"])
        elif found:
            pack_strengths = found["values"]      # combination: numbers kept as a set

    price = None
    if get("price"):
        try:
            price = float(get("price").replace(",", ""))
        except ValueError:
            return None, None, f"price is not a number: {get('price')}"
        if price < 0:
            return None, None, "price is negative"

    pack = None
    if get("pack_count"):
        try:
            pack = int(float(get("pack_count")))
        except ValueError:
            return None, None, f"pack_count is not a number: {get('pack_count')}"
        if pack <= 0:
            pack = None
    else:
        pack = market_names.pack_count(trade_name)

    availability = _AVAILABILITY.get(norm_text(get("availability")))
    if availability is None:
        return None, None, f"availability not understood: {get('availability')}"

    ingredient_key, composition_key, known = composition_keys(items)
    if pack_strengths:
        # Same ingredients + the same set of numbers on the pack + same form.
        # Which number belongs to which ingredient is not assumed.
        values = sorted(f"{v['value']:g}{v['unit']}" for v in pack_strengths)
        composition_key = f"{ingredient_key}@{'+'.join(values)}"
        known = True
    if form == "unspecified":
        known = False               # never offer a product of unknown form as an exact match
    fields = {
        "trade_name": trade_name,
        "trade_name_ar": get("trade_name_ar") or None,
        "ingredients_display": " + ".join(display_name(i["name"]) for i in items),
        "strength_display": (" / ".join(v["text"] for v in pack_strengths) + " (as on the pack)"
                             if pack_strengths else
                             " + ".join(i["text"] or "?" for i in items) if any(
                                 i["text"] for i in items) else None),
        "form": form,
        "form_raw": form_raw,
        "company": get("company") or None,
        "price": price,
        "pack_count": pack,
        "drug_class": get("drug_class") or None,
        "country": get("country") or None,
        "availability": availability,
        "ingredient_key": ingredient_key,
        "composition_key": composition_key,
        "strength_known": 1 if known else 0,
    }
    return fields, items, None


def save_drug(fields, items, drug_id=None):
    """Insert or update a drug together with its ingredient rows."""
    ts = db.now()
    cols = list(fields)
    if drug_id is None:
        cur = db.execute(
            f"INSERT INTO drugs ({', '.join(cols)}, created_at, updated_at) "
            f"VALUES ({', '.join('?' for _ in cols)}, ?, ?)",
            [fields[c] for c in cols] + [ts, ts],
        )
        drug_id = cur.lastrowid
    else:
        db.execute(
            f"UPDATE drugs SET {', '.join(c + ' = ?' for c in cols)}, updated_at = ? WHERE id = ?",
            [fields[c] for c in cols] + [ts, drug_id],
        )
        db.execute("DELETE FROM drug_ingredients WHERE drug_id = ?", (drug_id,))

    for i in items:
        db.execute("INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (i["name"],))
        ing_id = db.one("SELECT id FROM ingredients WHERE name = ?", (i["name"],))["id"]
        db.execute(
            "INSERT INTO drug_ingredients (drug_id, ingredient_id, strength_value, "
            "strength_unit, strength_text) VALUES (?, ?, ?, ?, ?)",
            (drug_id, ing_id, i["value"], i["unit"], i["text"]),
        )
    return drug_id


def _map_headers(headers):
    mapping = {}
    for h in headers or []:
        key = norm_text(h).replace(" ", "_").replace("-", "_")
        for field, names in COLUMN_ALIASES.items():
            if key in [norm_text(n).replace(" ", "_") for n in names]:
                mapping[h] = field
    return mapping


def import_csv(data, replace=False):
    """Import a CSV file (bytes). Returns a report dict; bad rows are skipped
    and listed, good rows are saved. A row that already exists is updated."""
    report = {"added": 0, "updated": 0, "skipped": 0, "errors": [], "fatal": None}
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        report["fatal"] = "File is not UTF-8. In Excel choose 'CSV UTF-8' when saving."
        return report

    reader = csv.DictReader(io.StringIO(text))
    mapping = _map_headers(reader.fieldnames)
    missing = [f for f in ("trade_name", "active_ingredients")
               if f not in mapping.values()]
    if missing:
        report["fatal"] = "Missing required column(s): " + ", ".join(missing)
        return report

    if replace:
        db.execute("DELETE FROM drugs")
        db.execute("DELETE FROM ingredients")

    for line_no, row in enumerate(reader, start=2):
        raw = {mapping[h]: v for h, v in row.items() if h in mapping and v is not None}
        if not any((v or "").strip() for v in raw.values()):
            continue                                            # blank line
        fields, items, error = validate_drug(raw)
        if error:
            report["skipped"] += 1
            if len(report["errors"]) < 100:
                report["errors"].append((line_no, raw.get("trade_name", ""), error))
            continue
        existing = db.one(
            "SELECT id FROM drugs WHERE lower(trade_name) = lower(?) "
            "AND composition_key = ? AND form = ?",
            (fields["trade_name"], fields["composition_key"], fields["form"]),
        )
        save_drug(fields, items, existing["id"] if existing else None)
        report["updated" if existing else "added"] += 1

    if replace or report["added"] or report["updated"]:
        db.execute("DELETE FROM ingredients WHERE id NOT IN "
                   "(SELECT ingredient_id FROM drug_ingredients)")
        db.bump_data_version()
    db.commit()
    return report
