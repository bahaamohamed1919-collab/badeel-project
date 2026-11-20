"""Checking the drug list against official lists of the Egyptian Drug Authority (EDA).

The EDA publishes PDF lists. The OTC list ("medicines without a prescription",
January 2026) has one row per product: trade name, active ingredient, dosage
form, strength, indication, package. This module reads that PDF, finds each
EDA product in Badeel's drug list by its brand name, and compares the active
ingredients and the strengths.

The PDF is read twice:
- pdfplumber finds the table rows (clean trade names);
- pdftotext -raw gives the text of each row in drawing order, where long
  cells are not mixed with their neighbours.
"""
import difflib
import re
import shutil
import subprocess

from .normalize import STRENGTH_RE, canon_form, canon_strength, moiety_key, norm_text

EDA_OTC_URL = "https://edaegypt.gov.eg/media/u30pb3mf/otc-list-5-1-2026_.pdf"


# ----------------------------------------------------------- reading the PDF
def _raw_lines(path):
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext was not found (package poppler-utils).")
    out = subprocess.run([exe, "-raw", path, "-"], check=True, capture_output=True)
    return out.stdout.decode("utf-8", errors="replace").splitlines()


def _table_rows(path):
    import pdfplumber                       # only needed for this check
    rows = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    cells = [re.sub(r"\s+", " ", c or "").strip() for c in row]
                    if cells and cells[0] and cells[0].lower() != "trade name":
                        rows.append(cells)
    return rows


def read_otc_list(path):
    """List of EDA products: {trade_name, active, strength, text}."""
    rows, raw = _table_rows(path), _raw_lines(path)
    products, pointer = [], 0
    for cells in rows:
        trade = cells[0]
        start = None
        for i in range(pointer, min(pointer + 60, len(raw))):
            if raw[i].startswith(trade):
                start = i
                break
        if start is None:
            text = " ".join(cells)
            active = cells[1] if len(cells) > 1 else ""
        else:
            end = start + 1
            while end < len(raw) and end - start < 12 and not any(
                    raw[end].startswith(r[0]) for r in rows[len(products) + 1:len(products) + 2]):
                end += 1
            active = raw[start][len(trade):].strip()
            text = " ".join(raw[start:end])
            pointer = start + 1
        products.append({"trade_name": trade, "active": active,
                         "strength": cells[3] if len(cells) > 3 else "", "text": text})
    return products


# ---------------------------------------------------------------- matching
def brand(name):
    """'CONTROLOC 20MG 14 TAB.' and 'Controloc 20 mg' -> 'controloc'."""
    t = norm_text(name).replace("®", " ")
    t = re.split(r"\d", t, maxsplit=1)[0]
    t = re.sub(r"[^a-z؀-ۿ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def strengths_in(text):
    """Every strength written in a text, as (value, unit) after unit conversion."""
    found = set()
    for m in STRENGTH_RE.finditer(text or ""):
        try:
            value, unit = canon_strength(*m.groups())
        except (ValueError, ZeroDivisionError):
            continue
        found.add((round(value, 3), unit))
    return found


def ingredient_found(ingredient, text):
    """How this Badeel ingredient appears in the EDA text.

    'agree'    the same name (after synonyms and salts), e.g. 'pantoprazole'
               in 'Pantoprazole sesquihydrate';
    'spelling' a name that differs only by spelling (similarity >= 0.85),
               e.g. 'phenylepherine' for 'Phenylephrine';
    'differ'   not found.
    """
    words = norm_text(text)
    key = moiety_key(ingredient)
    if key and key in words:
        return "agree"
    parts = [re.sub(r"\s+\d.*", "", p).strip(" -()*")
             for p in re.split(r"[/+,;]|\band\b|\bequivalent to\b", words)]
    parts = [p for p in parts if p]
    # each piece can carry extra words ("vitamin b12 film coated tablets"):
    # try its shorter beginnings too
    for p in parts:
        words_in_part = p.split()
        if any(moiety_key(" ".join(words_in_part[:k])) == key for k in range(len(words_in_part), 0, -1)):
            return "agree"
    # compare with every run of 1 to 4 words, so 'sodium bicarbonte' meets 'sodium bicarbonate'
    tokens = re.findall(r"[a-z]+", words)
    n = len(key.split())
    for size in {n, n + 1, max(1, n - 1)}:
        for i in range(len(tokens) - size + 1):
            chunk = " ".join(tokens[i:i + size])
            if difflib.SequenceMatcher(None, key, moiety_key(chunk)).ratio() >= 0.85:
                return "spelling"
    return "differ"


def eda_form(eda):
    """Dosage form of the EDA product, read from the start of its row."""
    return canon_form(eda["active"] + " " + eda["text"][:160]).split(" (")[0]


def compare(eda, product, product_ingredients):
    """Compare one EDA product with one Badeel product.

    product: needs 'form'. product_ingredients: list of (name, value, unit).
    Returns {'ingredients': 'agree' | 'spelling' | 'differ',
             'strength': 'agree' | 'differ' | 'other form' | 'unknown'}.
    """
    text = eda["active"] + " " + eda["text"]
    results = [ingredient_found(n, text) for n, _, _ in product_ingredients]
    if results and all(r == "agree" for r in results):
        ingredients = "agree"
    elif results and all(r in ("agree", "spelling") for r in results):
        ingredients = "spelling"
    else:
        ingredients = "differ"

    if product.get("form", "").split(" (")[0] != eda_form(eda):
        return {"ingredients": ingredients, "strength": "other form"}
    eda_strengths = strengths_in(eda["strength"]) | strengths_in(text)
    ours = {(round(v, 3), u) for _, v, u in product_ingredients if v is not None}
    if not ours or not eda_strengths:
        strength = "unknown"
    else:
        strength = "agree" if ours <= eda_strengths else "differ"
    return {"ingredients": ingredients, "strength": strength}
