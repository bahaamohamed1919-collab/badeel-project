"""Reading strength and dosage form out of an Egyptian market product name.

Egyptian drug lists often have no separate strength or form column. Both are
written inside the trade name, together with the pack size:

    "CILOMEPATAL 100MG 20 TAB."            strength 100 mg, form tablet, pack 20
    "BRUFEN 100MG/5ML SYRUP 150ML"         strength 20 mg/ml, form syrup, bottle 150 ml
    "ADWIVALSAR-CO 160/12.5MG 10 F.C.TAB." two strengths: 160 mg and 12.5 mg
    "VENLATROPE 50 MG 20 EXT.REL.TABS."    extended-release tablet

The rules are deliberately cautious. When a name could be read in two ways,
we return "unknown" and the product is never offered as an exact alternative:
    - a bottle or tube size (150 ML, 50 GM CREAM) is never taken as a strength;
    - a combination product written with one total (AUGMENTIN 1 GM) is not split,
      because the name does not say how much of each ingredient it holds;
    - a form word must be a whole word, so CAPOTEN is not read as "capsules".
"""
import re

from .normalize import canon_strength

# ------------------------------------------------------------------ forms
# (form, phrases). Checked in this order on the name split into words.
FORM_PHRASES = [
    ("effervescent", ["EFF", "EFFERVESCENT", "EFFERV"]),
    ("eye drops", ["EYE DROPS", "EYE DROP", "EYE/EAR DROPS", "OPHTHALMIC"]),
    ("eye ointment", ["EYE OINT", "EYE OINTMENT", "OPHTHALMIC OINT"]),
    ("ear drops", ["EAR DROPS", "EAR DROP", "OTIC"]),
    ("nasal spray", ["NASAL SPRAY"]),
    ("nasal drops", ["NASAL DROPS", "NOSE DROPS"]),
    ("inhaler", ["INHALER", "EVOHALER", "DISKUS", "TURBUHALER", "INHALATION", "INH"]),
    ("injection", ["VIAL", "VIALS", "AMP", "AMPS", "AMPOULE", "AMPOULES", "INJ", "INJECTION",
                   "INF", "INFUSION", "I V", "I M", "S C", "SYRINGE", "SYRINGES",
                   "PREFILLED"]),
    ("vaginal suppository", ["VAG SUPP", "VAGINAL SUPP", "OVULES", "OVULE"]),
    ("vaginal tablet", ["VAG TAB", "VAG TABS", "VAGINAL TAB", "VAGINAL TABS",
                        "VAGINAL TABLETS"]),
    ("suppository", ["SUPP", "SUPPOSITORY", "SUPPOSITORIES"]),
    ("suspension", ["SUSP", "SUSPENSION"]),
    ("oral drops", ["ORAL DROPS", "INFANT DROPS", "PAED DROPS", "PEDIATRIC DROPS"]),
    ("syrup", ["SYRUP", "SYR", "ELIXIR"]),
    ("oral solution", ["ORAL SOL", "ORAL SOLN", "ORAL SOLUTION"]),
    ("orodispersible film", ["FILM", "FILMS", "ORAL FILM", "ORAL FILMS"]),
    ("lozenge", ["LOZENGE", "LOZENGES", "LOZ"]),
    ("chewable tablet", ["CHEW TAB", "CHEW TABS", "CHEWABLE TAB", "CHEWABLE TABS",
                         "CHEWABLE TABLETS"]),
    ("orodispersible tablet", ["ODT", "ORODISPERSIBLE", "DISPERSIBLE TABS",
                               "DISPERSIBLE TAB"]),
    ("sublingual tablet", ["SUBLINGUAL"]),
    ("capsule", ["CAP", "CAPS", "CAPSULE", "CAPSULES"]),
    ("tablet", ["TAB", "TABS", "TABLET", "TABLETS", "F C TAB", "F C TABS", "FCT", "F C T",
                "CAPLET", "CAPLETS"]),
    ("cream", ["CREAM"]),
    ("ointment", ["OINT", "OINTMENT"]),
    ("gel", ["GEL"]),
    ("lotion", ["LOTION"]),
    ("shampoo", ["SHAMPOO"]),
    ("sachet", ["SACHET", "SACHETS"]),
    ("spray", ["SPRAY"]),
    ("drops", ["DROPS", "DROP"]),
]

# Release that differs from a normal tablet or capsule.
EXTENDED = ["XR", "XL", "SR", "S R", "ER", "MR", "CR", "C R", "EXT REL", "EXTENDED",
            "RETARD", "PROLONGED", "MODIFIED R", "MODIFIED RELEASE", "SUSTAINED",
            "CONTROLLED", "DEPOT"]
DELAYED = ["E C", "EC", "ENTERIC", "DELAYED", "GASTRO RESISTANT", "D R"]

# Used only when the name has no form word. The source's "EFF" route mixes
# effervescent tablets, sachets and tea bags, so it is not used to guess.
ROUTE_FORMS = {
    "EYE": "eye drops", "INJECTION": "injection", "RECTAL": "suppository", "SPRAY": "spray",
}

TOPICAL = {"cream", "ointment", "gel", "lotion", "shampoo", "spray", "eye ointment"}
LIQUID = {"syrup", "suspension", "oral solution", "oral drops", "drops", "eye drops",
          "ear drops", "nasal drops", "nasal spray"}


def _words(name):
    """'F.C.TABS.' -> ' F C TABS '  (padded, so phrases match whole words only).
    A number stuck to a word is split off: '50CAPS' -> '50 CAPS'."""
    text = re.sub(r"(\d)([A-Z])", r"\1 \2", (name or "").upper())
    text = re.sub(r"[^A-Z0-9%؀-ۿ]+", " ", text)
    return f" {re.sub(r'\s+', ' ', text).strip()} "


def _has(words, phrase):
    return f" {phrase} " in words


def detect_form(name, route=""):
    """Returns the canonical form, or None when it cannot be told safely."""
    words = _words(name)
    base = None
    for form, phrases in FORM_PHRASES:
        if any(_has(words, p) for p in phrases):
            base = form
            break
    if base == "injection" and any(_has(words, w) for w in ("HAIR", "SCALP", "SKIN", "FACE")):
        base = None                     # "hair ampoules" are applied to the hair, not injected
    if base is None:
        base = ROUTE_FORMS.get((route or "").strip().upper())
    if base is None:
        return None
    if base in ("tablet", "capsule", "suppository", "injection", "chewable tablet"):
        if any(_has(words, p) for p in EXTENDED):
            return base + " (extended release)"
        if any(_has(words, p) for p in DELAYED):
            return base + " (delayed release)"
    return base


# --------------------------------------------------------------- strength
_NUM = r"(\d+(?:\.\d+)?)"
_MASS = r"(MG|MCG|UG|G|GM|IU|I\.U\.?|UNITS?)"
# 160/12.5MG   300/0.5 MG
_PAIR_SHARED = re.compile(_NUM + r"\s*/\s*" + _NUM + r"\s*" + _MASS + r"(?![A-Z])", re.I)
# 1GM/125MG   500 MG / 125 MG     (both sides are amounts, not "per ml")
_PAIR_OWN = re.compile(_NUM + r"\s*" + _MASS + r"\s*/\s*" + _NUM + r"\s*" + _MASS + r"(?![A-Z])",
                       re.I)
# 100MG/5ML   62.5MG/ML   2 MG/G
_CONC = re.compile(_NUM + r"\s*" + _MASS + r"\s*/\s*(\d+(?:\.\d+)?)?\s*(ML|G|GM|DOSE|PUFF)(?![A-Z])",
                   re.I)
_SINGLE = re.compile(_NUM + r"\s*(" + _MASS[1:-1] + r"|%)(?![A-Z/])", re.I)


def _unit(u):
    u = u.lower().replace(".", "")
    return {"ug": "mcg", "units": "iu", "unit": "iu"}.get(u, u)


def _value(num, unit, den_num=None, den_unit=None):
    if _unit(unit) in ("iu", "i u") and re.fullmatch(r"\d{1,3}\.\d{3}", num):
        num = num.replace(".", "")              # "50.000 I.U." means fifty thousand
    value, cu = canon_strength(num, _unit(unit), den_num, den_unit.lower() if den_unit else None)
    text = f"{num} {_unit(unit)}" + (f"/{den_num + ' ' if den_num else ''}{den_unit.lower()}"
                                     if den_unit else "")
    return {"value": value, "unit": cu, "text": text}


def extract_strengths(name, n_ingredients, form):
    """Strengths written in the name, or None if unsure.

    Returns {"values": [...], "ordered": bool}. For one ingredient the single
    value belongs to it. For a combination ("AMILO PLUS 5/160MG") the name
    does not say which number belongs to which ingredient, so the values are
    kept as a set ("ordered": False) and are never assigned one by one.
    """
    text = (name or "").upper()
    found = []
    if n_ingredients >= 2:
        m = _PAIR_OWN.search(text)
        if m:
            g = m.groups()
            found = [_value(g[0], g[1]), _value(g[2], g[3])]
        else:
            m = _PAIR_SHARED.search(text)
            if m:
                g = m.groups()
                found = [_value(g[0], g[2]), _value(g[1], g[2])]
    if not found:
        for m in _CONC.finditer(text):                   # concentrations first
            found.append(_value(m.group(1), m.group(2), m.group(3), m.group(4)))
    if not found:
        if form in TOPICAL or form in LIQUID:
            # In "50 GM CREAM" or "SYRUP 120 ML" the number is the pack size.
            found = [_value(m.group(1), m.group(2)) for m in _SINGLE.finditer(text)
                     if m.group(2) == "%"]
        else:
            found = [_value(m.group(1), m.group(2)) for m in _SINGLE.finditer(text)]

    distinct = []
    for item in found:
        if (item["value"], item["unit"]) not in [(d["value"], d["unit"]) for d in distinct]:
            distinct.append(item)
    if n_ingredients == 1 and len(distinct) == 1:
        return {"values": distinct, "ordered": True}
    if n_ingredients > 1 and len(found) == n_ingredients:
        return {"values": found, "ordered": False}
    return None


# ------------------------------------------------------------- pack size
_UNIT_WORDS = (r"TAB|TABS|TABLET|TABLETS|CAP|CAPS|CAPSULE|CAPSULES|SACHET|SACHETS|SUPP|"
               r"AMP|AMPS|AMPOULE|AMPOULES|VIAL|VIALS|LOZENGES|FILMS|OVULES|BITAB|PIECES")
_MODIFIERS = (r"(?:(?:F C|FC|FILM COATED|SCORED|COATED|SUGAR C|CHEW|CHEWABLE|EXT REL|MODIFIED R|"
              r"S G|H G|SOFT|HARD|GELATIN|ORO DISPERSIBLE|DISPERSIBLE|ORODISPERSIBLE|SUBLINGUAL|"
              r"VAG|VAGINAL|RECTAL|EFF|EFFERVESCENT|GR|IN|I V|I M|DUAL|DOUBLE|MR|SR|XR|ER|"
              r"ENTERIC|E C|DELAYED|DR) )*")
_PACK = re.compile(r" (\d+) " + _MODIFIERS + r"(?:" + _UNIT_WORDS + r") ")


def pack_count(name):
    """Number of units in the pack: '... 20 F.C.TABS.' -> 20,  '3*28 TABS' -> 84.
    Returns None when the name does not say (liquids, creams, unclear names)."""
    text = (name or "").upper()
    text = re.sub(r"(\d+)\s*[*X]\s*(\d+)", lambda m: str(int(m.group(1)) * int(m.group(2))), text)
    m = _PACK.search(_words(text))
    if not m:
        return None
    n = int(m.group(1))
    return n if 0 < n <= 1000 else None
