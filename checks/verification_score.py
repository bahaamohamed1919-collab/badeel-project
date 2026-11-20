"""Score a filled review file.

    python checks/verification_score.py data/verification/random_sample_100.csv
    python checks/verification_score.py data/verification/eda_otc_review.csv

For the random sample: share of 'yes' for each checked field, with a 95%
Wilson confidence interval (the range the true rate is likely to be in).
For the EDA review: the reviewers' verdicts on the rows marked NEEDS REVIEW,
and the agreement after the review.
Results are printed and saved next to the other results in docs/results/.
"""
import collections
import csv
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def wilson(k, n, z=1.96):
    """95% confidence interval for a proportion k/n (Wilson score interval)."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _rate(label, k, n):
    if not n:
        return f"  {label:<26}: not filled yet"
    lo, hi = wilson(k, n)
    return f"  {label:<26}: {k} of {n} = {k / n:.1%}  (95% CI {lo:.1%} to {hi:.1%})"


def _yes(value):
    return (value or "").strip().lower() in ("yes", "y", "نعم", "ايوه", "1", "true")


def _filled(value):
    return (value or "").strip() != ""


def score_sample(rows):
    col = {name.split(" (")[0]: name for name in rows[0]}
    lines = ["RANDOM SAMPLE CHECKED AGAINST EDA RECORDS", f"  Products in the file      : {len(rows)}"]
    found = [r for r in rows if _filled(r[col["found_in_eda"]])]
    in_eda = [r for r in found if _yes(r[col["found_in_eda"]])]
    lines.append(_rate("found in EDA records", len(in_eda), len(found)))
    for field in ("name_ok", "ingredients_ok", "strength_ok", "form_ok", "price_ok"):
        checked = [r for r in in_eda if _filled(r[col[field]])]
        lines.append(_rate(field.replace("_ok", " correct"), sum(_yes(r[col[field]]) for r in checked),
                           len(checked)))
    return lines


def score_eda_review(rows):
    verdict_col = next(c for c in rows[0] if c.startswith("reviewer_verdict"))
    review = [r for r in rows if r["status"] == "NEEDS REVIEW"]
    verdicts = collections.Counter((r[verdict_col] or "").strip().lower() or "not reviewed yet"
                                   for r in review)
    matched = [r for r in rows if r["badeel_trade_name"]]
    wrong = sum(1 for r in review if (r[verdict_col] or "").strip().lower() == "badeel_wrong")
    lines = ["EDA OTC CROSS-CHECK AFTER HUMAN REVIEW",
             f"  Rows marked NEEDS REVIEW  : {len(review)}"]
    for v, n in verdicts.most_common():
        lines.append(f"    {v:<24}: {n}")
    if verdicts.get("not reviewed yet", 0) == 0 and matched:
        lines.append(_rate("matched products correct", len(matched) - wrong, len(matched)))
    else:
        lines.append("  Agreement after review    : finish the review first")
    return lines


def main():
    path = sys.argv[1]
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("The file is empty.")
    lines = score_eda_review(rows) if "status" in rows[0] else score_sample(rows)
    text = "\n".join(lines)
    print(text)
    out = os.path.join(ROOT, "docs", "results",
                       "verification_" + os.path.splitext(os.path.basename(path))[0] + ".txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"\nSaved to {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
