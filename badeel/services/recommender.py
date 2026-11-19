"""The recommendation engine.

A wrong alternative can hurt a patient, so the core decision is a strict rule,
not a guess:

  1. EXACT       same ingredients + same strength of each + same form.
                 Safe to offer as a direct substitute.
  2. SAME DRUG,  same ingredients, but the strength or the form differs.
     DIFFERENT   Shown separately with the difference highlighted; the dose
                 must be adjusted by a pharmacist or doctor.
  3. SAME CLASS  a different ingredient from the same therapeutic class.
                 Shown only as "ask your doctor about".

Machine learning is used where a mistake is harmless (understanding what the
user typed, see search.py), never for deciding what is safe to swap.
"""
from .. import db

_ORDER = ("ORDER BY CASE availability WHEN 'available' THEN 0 WHEN 'unknown' THEN 1 ELSE 2 END, "
          "price IS NULL, price, trade_name")
_AVAIL = {"available": 0, "unknown": 1, "shortage": 2}


def unit_price(d):
    """Price of one tablet / capsule / ampoule when the pack size is known.
    Packs of 10 and 30 tablets cannot be compared by pack price."""
    if d["price"] is None or not d["pack_count"]:
        return None
    return d["price"] / d["pack_count"]


def _with_saving(rows, base):
    """Adds unit_price and the saving in % against the drug being viewed.
    Compared per unit when both pack sizes are known, else per pack only if
    neither pack size is known."""
    out = []
    base_unit = unit_price(base) if base else None
    for r in rows:
        d = dict(r)
        d["unit_price"] = unit_price(d)
        d["saving"] = None
        d["saving_per_unit"] = False
        if base is not None and base["price"]:
            if base_unit and d["unit_price"] is not None:
                if d["unit_price"] < base_unit:
                    d["saving"] = round((base_unit - d["unit_price"]) / base_unit * 100)
                    d["saving_per_unit"] = True
            elif not base["pack_count"] and not d["pack_count"] and d["price"] is not None:
                if d["price"] < base["price"]:
                    d["saving"] = round((base["price"] - d["price"]) / base["price"] * 100)
        out.append(d)
    # available first, then cheapest per unit (falls back to pack price), then name
    out.sort(key=lambda d: (_AVAIL.get(d["availability"], 1),
                            d["unit_price"] is None and d["price"] is None,
                            d["unit_price"] if d["unit_price"] is not None else
                            (d["price"] if d["price"] is not None else 0),
                            d["trade_name"]))
    return out


def get_alternatives(drug):
    exact = []
    if drug["strength_known"]:
        exact = db.query(
            f"SELECT * FROM drugs WHERE composition_key = ? AND form = ? AND id != ? {_ORDER}",
            (drug["composition_key"], drug["form"], drug["id"]),
        )
    exact_ids = {r["id"] for r in exact}

    related = [
        r for r in db.query(
            f"SELECT * FROM drugs WHERE ingredient_key = ? AND id != ? {_ORDER}",
            (drug["ingredient_key"], drug["id"]))
        if r["id"] not in exact_ids
    ]
    related = _with_saving(related, None)
    for r in related:
        r["same_strength"] = bool(drug["strength_known"] and r["strength_known"]
                                  and r["composition_key"] == drug["composition_key"])
        r["same_form"] = r["form"] == drug["form"]

    same_class = []
    if drug["drug_class"]:
        same_class = db.query(
            f"SELECT * FROM drugs WHERE lower(drug_class) = lower(?) AND ingredient_key != ? "
            f"{_ORDER} LIMIT 12",
            (drug["drug_class"], drug["ingredient_key"]),
        )

    return {
        "exact": _with_saving(exact, drug),
        "related": related,
        "same_class": [dict(r) for r in same_class],
    }


def are_exact_alternatives(a, b):
    """Used by the evaluation script and the tests."""
    return bool(a["id"] != b["id"] and a["strength_known"] and b["strength_known"]
                and a["composition_key"] == b["composition_key"] and a["form"] == b["form"])
