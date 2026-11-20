"""Draw a random sample of products for a person to check against EDA records.

    python checks/make_review_sample.py [N] [SEED]      (default 100 products, seed 2026)

Writes data/verification/random_sample_<N>.csv (opens in Excel). The same
seed always gives the same sample, so the paper can say exactly which
products were checked. Fill the empty columns, then run:
    python checks/verification_score.py data/verification/random_sample_100.csv
"""
import csv
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from badeel import create_app, db      # noqa: E402

FILL = ["found_in_eda (yes/no)", "name_ok (yes/no)", "ingredients_ok (yes/no)",
        "strength_ok (yes/no)", "form_ok (yes/no)", "eda_price_egp", "price_ok (yes/no)",
        "eda_link_or_reference", "notes", "checked_by", "checked_on (YYYY-MM-DD)"]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    app = create_app()
    with app.app_context():
        drugs = db.query("SELECT * FROM drugs ORDER BY id")
    sample = sorted(random.Random(seed).sample(list(drugs), min(n, len(drugs))), key=lambda d: d["id"])
    out = os.path.join(ROOT, "data", "verification", f"random_sample_{n}.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sample_no", "product_id", "trade_name", "trade_name_ar", "ingredients",
                    "strength", "form", "company", "price_egp"] + FILL)
        for i, d in enumerate(sample, 1):
            w.writerow([i, d["id"], d["trade_name"], d["trade_name_ar"], d["ingredients_display"],
                        d["strength_display"], d["form"], d["company"], d["price"]] + [""] * len(FILL))
    print(f"{len(sample)} products (seed {seed}) written to {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
