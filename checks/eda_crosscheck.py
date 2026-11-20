"""Compare the drug list with the official EDA OTC list.

    python checks/eda_crosscheck.py [EDA_PDF]

Uses the database of the site (set BADEEL_INSTANCE to use another one, e.g.
the one with the full Egyptian list). Writes:
  docs/results/eda_crosscheck.txt            the numbers for the paper
  data/verification/eda_otc_review.csv      every EDA product with the automatic
                                             result; rows marked NEEDS REVIEW have
                                             empty columns for a person to fill
Score the review file after it is filled:  python checks/verification_score.py
"""
import collections
import csv
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from badeel import create_app, db                      # noqa: E402
from badeel.services import eda                         # noqa: E402

DEFAULT_PDF = os.path.join(ROOT, "data", "raw", "eda", "otc-list-5-1-2026.pdf")
OUT_TXT = os.path.join(ROOT, "docs", "results", "eda_crosscheck.txt")
OUT_CSV = os.path.join(ROOT, "data", "verification", "eda_otc_review.csv")

REVIEW_COLUMNS = ["reviewer_verdict (badeel_wrong / matching_wrong / pdf_unclear / correct)",
                  "reviewer_note", "reviewed_by"]


def load_products():
    ingredients = collections.defaultdict(list)
    for r in db.query("SELECT di.drug_id, i.name, di.strength_value, di.strength_unit "
                      "FROM drug_ingredients di JOIN ingredients i ON i.id = di.ingredient_id"):
        ingredients[r["drug_id"]].append((r["name"], r["strength_value"], r["strength_unit"]))
    by_brand = collections.defaultdict(list)
    for d in db.query("SELECT id, trade_name, ingredients_display, strength_display, form FROM drugs"):
        by_brand[eda.brand(d["trade_name"])].append(dict(d))
    return by_brand, ingredients


def find(b, by_brand):
    """Exact brand first; otherwise a brand that starts with the same longer word."""
    if b in by_brand:
        return by_brand[b], "exact"
    first = b.split()[0] if b else ""
    if len(first) >= 5:
        hits = [d for k, v in by_brand.items() if k.split()[:1] == [first] for d in v]
        if hits:
            return hits, "first word"
    return [], "not found"


def main():
    pdf = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PDF
    if not os.path.exists(pdf):
        os.makedirs(os.path.dirname(pdf), exist_ok=True)
        print(f"Downloading {eda.EDA_OTC_URL}")
        urllib.request.urlretrieve(eda.EDA_OTC_URL, pdf)
    products = eda.read_otc_list(pdf)

    app = create_app()
    with app.app_context():
        by_brand, ingredients = load_products()
        total_products = db.one("SELECT COUNT(*) AS n FROM drugs")["n"]

    rank_ing = {"agree": 2, "spelling": 1, "differ": 0}
    rank_str = {"agree": 3, "unknown": 2, "other form": 1, "differ": 0}
    rows, stats = [], collections.Counter()
    for p in products:
        candidates, how = find(eda.brand(p["trade_name"]), by_brand)
        stats[how] += 1
        best = None
        for c in candidates:
            r = eda.compare(p, c, ingredients[c["id"]])
            score = (rank_ing[r["ingredients"]], rank_str[r["strength"]])
            if best is None or score > best[0]:
                best = (score, c, r)
        if best:
            _, c, result = best
            stats[(how, "ing", result["ingredients"])] += 1
            stats[(how, "str", result["strength"])] += 1
        needs = (not best) or result["ingredients"] == "differ" or result["strength"] == "differ"
        rows.append([
            p["trade_name"], p["active"][:200], p["strength"][:80], how,
            c["trade_name"] if best else "", c["ingredients_display"] if best else "",
            c["strength_display"] if best else "",
            result["ingredients"] if best else "", result["strength"] if best else "",
            "NEEDS REVIEW" if needs else "", "", "", ""])

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:     # utf-8-sig opens in Excel
        w = csv.writer(f)
        w.writerow(["eda_trade_name", "eda_active", "eda_strength", "match", "badeel_trade_name",
                    "badeel_ingredients", "badeel_strength", "auto_ingredients", "auto_strength",
                    "status"] + REVIEW_COLUMNS)
        w.writerows(rows)

    n = len(products)

    def pct(a, b):
        return f"{a} of {b} ({a / b:.1%})" if b else f"{a} of 0"

    def block(hows, title):
        m = sum(stats[h] for h in hows)
        ing = {k: sum(stats[(h, "ing", k)] for h in hows) for k in ("agree", "spelling", "differ")}
        st = {k: sum(stats[(h, "str", k)] for h in hows) for k in ("agree", "differ", "other form", "unknown")}
        compared = st["agree"] + st["differ"]
        return [
            f"  {title} ({m} products):",
            f"    same active ingredients               : {pct(ing['agree'], m)}",
            f"    same, but spelled differently          : {pct(ing['spelling'], m)}",
            f"    different (to review)                  : {pct(ing['differ'], m)}",
            f"    same ingredients incl. spelling        : {pct(ing['agree'] + ing['spelling'], m)}",
            f"    strength agrees, same form             : {pct(st['agree'], compared)}",
            f"    strength differs, same form (to review): {pct(st['differ'], compared)}",
            f"    our product is another form of the brand: {st['other form']}",
            f"    strength not readable                  : {st['unknown']}",
        ]

    text = "\n".join([
        "CROSS-CHECK WITH THE EDA OTC LIST (January 2026)",
        f"  Source PDF                         : {os.path.basename(pdf)}",
        f"  Products in the drug list          : {total_products:,}",
        f"  Products in the EDA list           : {n}",
        f"  Found by exact brand name          : {pct(stats['exact'], n)}",
        f"  Found by first word only           : {pct(stats['first word'], n)}",
        f"  Not found                          : {pct(stats['not found'], n)}",
        "",
        *block(["exact"], "Exact brand matches"),
        "",
        *block(["exact", "first word"], "All matches"),
        "",
        f"  Rows that need a person to review  : {sum(r[9] == 'NEEDS REVIEW' for r in rows)}"
        f"  (see {os.path.relpath(OUT_CSV, ROOT)})",
        "  These are automatic results: a disagreement can come from the matching or from",
        "  reading the PDF, not only from the drug list. The review decides which.",
    ])
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
