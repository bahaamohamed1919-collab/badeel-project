"""Turning messy drug text into something that can be compared safely.

Source data writes the same thing in many ways:
    "Paracetamol 500mg", "ACETAMINOPHEN 0.5 g", "paracetamol (500 mg)"
This module converts each of them to one canonical form, so the recommender
can compare drugs with a simple equality check instead of guessing.
"""
import csv
import os
import re
import unicodedata

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")

_AR_DIACRITICS = re.compile(r"[ً-ْٰـ]")


def norm_text(s):
    """Lower-case, trim, and unify Arabic letter variants (أ إ آ -> ا, ة -> ه, ى -> ي)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).lower().strip()
    s = _AR_DIACRITICS.sub("", s)
    s = re.sub("[إأآ]", "ا", s).replace("ى", "ي").replace("ة", "ه")
    return re.sub(r"\s+", " ", s)


# ---------------------------------------------------------------- aliases
def _load_aliases():
    """data/aliases.csv maps other names of an ingredient to one canonical name."""
    aliases = {}
    path = os.path.join(DATA_DIR, "aliases.csv")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                a, c = norm_text(row.get("alias")), norm_text(row.get("canonical"))
                if a and c:
                    aliases[a] = c
    return aliases


ALIASES = _load_aliases()


def canon_ingredient(name):
    """'Acetaminophen (as ...)' -> 'paracetamol'."""
    name = re.sub(r"\([^)]*\)", " ", name or "")      # drop "(as trihydrate)"
    name = norm_text(name).strip(" -:,.;")
    name = re.sub(r"\s+", " ", name)
    # "metformin hydrochloride" and "metformin hcl" are the same medicine as
    # "metformin". Other salts (sodium, potassium ...) are kept because they
    # can change how the drug behaves, e.g. diclofenac sodium vs potassium.
    name = re.sub(r"\s+(hydrochloride|hcl)$", "", name)
    return ALIASES.get(name, name)


# --------------------------------------------------------------- strength
_MASS_TO_MG = {"mg": 1.0, "g": 1000.0, "gm": 1000.0,
               "mcg": 0.001, "ug": 0.001, "µg": 0.001, "μg": 0.001}

STRENGTH_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(mcg|µg|μg|ug|mg|gm|g|i\.?u\.?|units?|ml|%)(?![a-z])"
    r"(?:\s*/\s*(\d+(?:[.,]\d+)?)?\s*(ml|l|gm|g|dose|actuation|puff|spray|tablet|tab)(?![a-z]))?",
    re.IGNORECASE,
)


def _num(text):
    if re.fullmatch(r"\d{1,3},\d{3}", text):     # 1,000 -> 1000
        return float(text.replace(",", ""))
    return float(text.replace(",", "."))          # 0,5 -> 0.5


def canon_strength(num, unit, den_num=None, den_unit=None):
    """Convert a strength to one unit system.

    500 mg, 0.5 g and 500000 mcg all become (500, 'mg').
    250 mg/5 ml becomes (50, 'mg/ml') so it equals 50 mg/ml written directly.
    """
    value, unit = _num(num), unit.lower()
    if unit in _MASS_TO_MG:
        value, cu = value * _MASS_TO_MG[unit], "mg"
    elif unit == "%":
        cu = "%"
    elif unit == "ml":
        cu = "ml"
    else:
        cu = "iu"
    if den_unit:
        d = _num(den_num) if den_num else 1.0
        du = den_unit.lower()
        if du == "l":
            d, du = d * 1000, "ml"
        du = {"gm": "g", "tab": "tablet", "actuation": "dose",
              "puff": "dose", "spray": "dose"}.get(du, du)
        if d:
            value = value / d
        cu = f"{cu}/{du}"
    return round(value, 6), cu


def fmt_strength(value, unit):
    return f"{value:g}{unit}"


def _parse_strength(text):
    m = STRENGTH_RE.search(text or "")
    if not m:
        return None
    value, unit = canon_strength(*m.groups())
    shown = re.sub(r"\s+", " ", m.group(0).strip().lower())
    shown = re.sub(r"(\d)([a-zµμ%])", r"\1 \2", shown, count=1)   # "500mg" -> "500 mg"
    return {"value": value, "unit": unit, "text": shown, "span": m.span()}


def parse_composition(text, strength_column=""):
    """'Amoxicillin 875 mg + Clavulanic acid 125 mg' -> list of ingredients.

    Each item: {name, value, unit, text}. value is None when no strength was
    found; such a drug is never offered as an exact alternative.
    """
    parts = [p for p in re.split(r"\s*(?:\+|;|&)\s*", text or "") if p.strip()]
    items = []
    for part in parts:
        st = _parse_strength(part)
        if st:
            a, b = st["span"]
            name = canon_ingredient(part[:a] + " " + part[b:])
        else:
            name = canon_ingredient(part)
        if not name:
            continue
        items.append({"name": name,
                      "value": st["value"] if st else None,
                      "unit": st["unit"] if st else None,
                      "text": st["text"] if st else None})

    # Strength given in its own column ("500 mg" or "875 mg + 125 mg" or "875/125 mg").
    if items and strength_column and all(i["value"] is None for i in items):
        col = strength_column.strip()
        pieces = [p for p in re.split(r"\s*\+\s*", col) if p]
        if len(pieces) != len(items):
            m = re.fullmatch(r"([\d.,]+(?:\s*/\s*[\d.,]+)+)\s*([a-zµμ%]+)", col, re.I)
            pieces = [f"{n.strip()} {m.group(2)}" for n in m.group(1).split("/")] if m else []
        if len(pieces) == len(items):
            for item, piece in zip(items, pieces):
                st = _parse_strength(piece)
                if st:
                    item.update(value=st["value"], unit=st["unit"], text=st["text"])

    # Merge accidental duplicates of the same ingredient.
    seen, unique = set(), []
    for i in items:
        if i["name"] not in seen:
            seen.add(i["name"])
            unique.append(i)
    return unique


def composition_keys(items):
    """Build the two comparison keys stored on every drug."""
    names = sorted(i["name"] for i in items)
    known = all(i["value"] is not None for i in items)
    comp = sorted(
        f"{i['name']}:{fmt_strength(i['value'], i['unit']) if i['value'] is not None else '?'}"
        for i in items
    )
    return "|".join(names), "|".join(comp), known


# ------------------------------------------------------------------- form
# Order matters: the first keyword found wins.
_FORMS = [
    ("effervescent", ["efferv", "فوار"]),
    ("sachet", ["sachet", "granule", "كيس", "اكياس"]),
    ("tablet", ["caplet"]),
    ("capsule", ["cap", "كبسول"]),
    ("tablet", ["tab", "قرص", "اقراص"]),
    ("suspension", ["susp", "معلق"]),
    ("syrup", ["syr", "elixir", "oral sol", "شراب"]),
    ("shampoo", ["shampoo", "شامبو"]),
    ("eye drops", ["eye", "ophth", "عين"]),
    ("ear drops", ["ear drop", "otic", "اذن"]),
    ("nasal spray", ["nasal", "انف"]),
    ("inhaler", ["inhal", "استنشاق"]),
    ("injection", ["inj", "amp", "vial", "infus", "حقن", "امبول", "فيال"]),
    ("suppository", ["supp", "لبوس", "اقماع"]),
    ("cream", ["cream", "كريم"]),
    ("ointment", ["oint", "مرهم"]),
    ("gel", ["gel", "جل"]),
    ("lotion", ["lotion", "لوشن"]),
    ("spray", ["spray", "بخاخ"]),
    ("drops", ["drop", "نقط", "قطره"]),
]

# Modified-release products must not be swapped with normal ones.
_MR_RE = re.compile(
    r"\b(xr|sr|er|mr|cr|retard|extended|prolonged|sustained|modified|controlled|depot)\b|ممتد"
)

FORM_LABELS = {
    "tablet": ("Tablets", "أقراص"), "capsule": ("Capsules", "كبسولات"),
    "effervescent": ("Effervescent", "فوار"), "sachet": ("Sachets", "أكياس"),
    "suspension": ("Suspension", "معلق"), "syrup": ("Syrup", "شراب"),
    "shampoo": ("Shampoo", "شامبو"), "eye drops": ("Eye drops", "قطرة للعين"),
    "ear drops": ("Ear drops", "قطرة للأذن"), "nasal spray": ("Nasal spray", "بخاخ للأنف"),
    "inhaler": ("Inhaler", "بخاخ استنشاق"), "injection": ("Injection", "حقن"),
    "suppository": ("Suppositories", "لبوس"), "cream": ("Cream", "كريم"),
    "ointment": ("Ointment", "مرهم"), "gel": ("Gel", "جل"), "lotion": ("Lotion", "لوشن"),
    "spray": ("Spray", "بخاخ"), "drops": ("Drops", "نقط"),
    "eye ointment": ("Eye ointment", "مرهم للعين"), "nasal drops": ("Nasal drops", "نقط للأنف"),
    "oral drops": ("Oral drops", "نقط بالفم"), "oral solution": ("Oral solution", "محلول بالفم"),
    "chewable tablet": ("Chewable tablets", "أقراص مضغ"),
    "orodispersible tablet": ("Orodispersible tablets", "أقراص تذوب في الفم"),
    "sublingual tablet": ("Sublingual tablets", "أقراص تحت اللسان"),
    "vaginal suppository": ("Vaginal suppositories", "لبوس مهبلي"),
    "vaginal tablet": ("Vaginal tablets", "أقراص مهبلية"),
    "orodispersible film": ("Orodispersible films", "أفلام تذوب في الفم"),
    "lozenge": ("Lozenges", "أقراص استحلاب"),
    "unspecified": ("Form not recorded", "الشكل غير مسجل"),
}
_RELEASE = {" (extended release)": (", extended release", " ممتدة المفعول"),
            " (delayed release)": (", delayed release", " مؤجلة المفعول")}


def canon_form(form_text, trade_name=""):
    """'F.C. Tabs' -> 'tablet';  'Tablets XR' -> 'tablet (extended release)'."""
    text = norm_text(form_text)
    base = text
    for canonical, keywords in _FORMS:
        if any(k in text for k in keywords):
            base = canonical
            break
    if _MR_RE.search(text) or _MR_RE.search(norm_text(trade_name)):
        base += " (extended release)"
    return base


def form_label(form, lang="en"):
    suffix = next((s for s in _RELEASE if form.endswith(s)), None)
    base = form[: -len(suffix)] if suffix else form
    en, ar = FORM_LABELS.get(base, (base.capitalize(), base))
    if suffix:
        en, ar = en + _RELEASE[suffix][0], ar + _RELEASE[suffix][1]
    return ar if lang == "ar" else en


def display_name(name):
    return " ".join(w.capitalize() for w in name.split())


# ------------------------------------------------------- external sources
# Salt and hydrate words that do not change which medicine it is when we look
# up interactions or a package leaflet. They are only removed for matching
# with outside sources; the exact-alternative rule still keeps salts apart.
_SALT_WORDS = {
    "sodium", "potassium", "calcium", "magnesium", "hydrochloride", "hcl",
    "hydrobromide", "sulfate", "sulphate", "maleate", "mesylate", "besylate",
    "besilate", "citrate", "phosphate", "succinate", "tartrate", "fumarate",
    "acetate", "hyclate", "monohydrate", "dihydrate", "trihydrate", "anhydrous",
    "bromide", "nitrate", "lactate", "gluconate", "dipropionate", "propionate",
}


def moiety_key(name):
    """Name used to match Badeel ingredients with outside data sources.

    'Diclofenac Sodium' and 'DICLOFENAC POTASSIUM' both give 'diclofenac';
    'Amoxicillin trihydrate' gives 'amoxicillin'. Both sides of a match go
    through this same function, so they agree even when the chemistry is
    simplified (e.g. 'ferrous sulfate' -> 'ferrous').
    """
    words = canon_ingredient(name).split()
    # Only trailing words are removed: "sodium chloride" and "potassium
    # chloride" are different medicines and must not both become "chloride".
    while len(words) > 1 and words[-1] in _SALT_WORDS:
        words.pop()
    return ALIASES.get(" ".join(words), " ".join(words))


def moiety_set_key(names):
    """'amoxicillin|clavulanic acid' style key built from moiety names."""
    return "|".join(sorted({moiety_key(n) for n in names if n and n.strip()}))
