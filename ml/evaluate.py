"""Evaluation script: produces the numbers for the report and the discussion.

    python ml/evaluate.py

It measures two things on whatever data is currently in the database:

1. SEARCH. Every drug name is misspelled on purpose (one random letter
   deleted, swapped, replaced or inserted) and we check whether the right drug
   still comes back, with the search exactly as the website runs it. Reported:
   Top-1, Top-3, MRR, compared with a plain SQL "LIKE" search. Then the
   cross-validated results of the trained ranking model (ml/train.py), which
   are the fair numbers because they test on brands the model never saw.

2. ALTERNATIVE MATCHING. data/gold_pairs.csv holds pairs of drugs labelled by
   hand as alternative (1) or not (0). We compare the engine's decision with
   the label. Reported: Accuracy, Precision, Recall, F1 and the confusion
   matrix (false positive = recommending a wrong drug, the dangerous error).
"""
import csv
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from badeel import create_app, db                                   # noqa: E402
from badeel.services import ranker, recommender, search             # noqa: E402
from badeel.services.normalize import norm_text                     # noqa: E402

LETTERS = "abcdefghijklmnopqrstuvwxyz"


def misspell(word, rng):
    """One random typo in the alphabetic part of the name."""
    positions = [i for i, c in enumerate(word) if c.isalpha()]
    if len(positions) < 4:
        return word
    i = rng.choice(positions[1:])                 # people rarely miss the first letter
    kind = rng.choice(["delete", "swap", "replace", "insert"])
    if kind == "delete":
        return word[:i] + word[i + 1:]
    if kind == "swap" and i + 1 < len(word):
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if kind == "replace":
        return word[:i] + rng.choice(LETTERS) + word[i + 1:]
    return word[:i] + rng.choice(LETTERS) + word[i:]


def evaluate_search(rounds=5, seed=42):
    rng = random.Random(seed)                     # fixed seed -> same numbers every run
    drugs = db.query("SELECT id, trade_name FROM drugs")
    top1 = top3 = like_hits = total = 0
    rr_sum = 0.0
    started = time.perf_counter()
    for _ in range(rounds):
        for d in drugs:
            typo = misspell(d["trade_name"].lower(), rng)
            if typo == d["trade_name"].lower():
                continue
            total += 1
            ranked = [i for i, _ in search.search(typo, limit=10)]
            if d["id"] in ranked:
                rank = ranked.index(d["id"]) + 1
                rr_sum += 1 / rank
                top1 += rank == 1
                top3 += rank <= 3
            like = db.query("SELECT id FROM drugs WHERE lower(trade_name) LIKE ? LIMIT 10",
                            (f"%{typo}%",))
            like_hits += d["id"] in [r["id"] for r in like]
    elapsed_ms = (time.perf_counter() - started) / max(total, 1) * 1000

    model = ranker.model_info(os.path.dirname(app.config["DATABASE"]))
    print("1) SEARCH WITH SPELLING MISTAKES  (live website search, "
          + ("with the trained model)" if model else "TF-IDF only, no model trained)"))
    print(f"   drugs in database        : {len(drugs)}")
    print(f"   misspelled queries tested: {total}")
    if total:
        print(f"   Top-1 accuracy           : {top1 / total:.1%}")
        print(f"   Top-3 accuracy           : {top3 / total:.1%}")
        print(f"   MRR                      : {rr_sum / total:.3f}")
        print(f"   Baseline SQL LIKE found  : {like_hits / total:.1%}")
        print(f"   Average time per query   : {elapsed_ms:.1f} ms (includes the baseline query)")
        if model:
            print("   (in-sample: the model was trained on these same names, so 1b is the fair test)")
    if model:
        cv = model["cv"]
        b, m = cv["baseline"]["all"], cv["model"]["all"]
        print("\n1b) TRAINED RANKING MODEL  (grouped 5-fold cross-validation, unseen brands)")
        print(f"   generated queries        : {m['n']}")
        print(f"   Top-1 without model      : {b['top1']:.1%}")
        print(f"   Top-1 with model         : {m['top1']:.1%}  (+/- {m['top1_std']:.1%})")
        print(f"   Top-3 / MRR with model   : {m['top3']:.1%} / {m['mrr']:.3f}")
        print("   Details per kind of mistake: python ml/train.py")
    else:
        print("\n   No trained model yet. Train it with: python ml/train.py")


def evaluate_matching():
    path = os.path.join(ROOT, "data", "gold_pairs.csv")
    print("\n2) ALTERNATIVE MATCHING AGAINST HAND-LABELLED PAIRS")
    if not os.path.exists(path):
        print("   data/gold_pairs.csv not found, skipped.")
        return
    tp = fp = tn = fn = missing = 0
    wrong = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            a = db.one("SELECT * FROM drugs WHERE lower(trade_name) = ?", (norm_text(row["drug_a"]),))
            b = db.one("SELECT * FROM drugs WHERE lower(trade_name) = ?", (norm_text(row["drug_b"]),))
            if not a or not b:
                missing += 1
                continue
            predicted = recommender.are_exact_alternatives(a, b)
            actual = row["is_alternative"].strip() == "1"
            tp += predicted and actual
            fp += predicted and not actual
            tn += (not predicted) and (not actual)
            fn += (not predicted) and actual
            if predicted != actual:
                wrong.append((row["drug_a"], row["drug_b"], actual, predicted))
    n = tp + fp + tn + fn
    if not n:
        print("   None of the labelled drugs are in the database "
              "(the gold file matches the demo data). Label pairs from your own data.")
        return
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    print(f"   labelled pairs evaluated : {n}  (not found in database: {missing})")
    print(f"   TP={tp}  FP={fp}  TN={tn}  FN={fn}")
    print(f"   Accuracy : {(tp + tn) / n:.1%}")
    print(f"   Precision: {precision:.1%}   (FP = a wrong drug recommended)")
    print(f"   Recall   : {recall:.1%}   (FN = a valid alternative missed)")
    print(f"   F1-score : {f1:.3f}")
    for a, b, actual, predicted in wrong:
        print(f"   WRONG: {a} / {b}: label={int(actual)} engine={int(predicted)}")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        if not db.one("SELECT COUNT(*) AS n FROM drugs")["n"]:
            sys.exit("The database is empty. Run: python manage.py init")
        evaluate_search()
        evaluate_matching()
