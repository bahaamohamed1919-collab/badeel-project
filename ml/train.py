"""Train the search ranking model.     python ml/train.py
                                       python ml/train.py --compare

What it does (details in badeel/services/ranker.py):
  1. Generates misspelled queries from every drug name in the database
     (self-supervised: the right answer is known for free).
  2. Grouped 5-fold cross-validation: a brand family is never in training and
     testing at the same time, so the score shows how the model does on
     drug names it has never seen. Reports Top-1, Top-3 and MRR for the
     current search (baseline) and for the trained model, per kind of mistake.
  3. Trains the final model on all drugs and saves it to
     instance/search_model.json. The website uses it immediately.

--compare also trains a gradient-boosting model and a random forest with the
same folds, to justify the choice of logistic regression.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from badeel import create_app, db                                   # noqa: E402
from badeel.services import ranker, search                          # noqa: E402

NAMES = {"all": "all queries", "one_edit": "one typo", "two_edits": "two typos",
         "keyboard": "neighbouring key", "phonetic": "sound-alike spelling",
         "prefix": "only first letters typed", "arabic": "Arabic name with a typo"}


def report(cv):
    print(f"\n   {'kind of query':<26}{'queries':>8}{'baseline top-1':>16}{'model top-1':>13}"
          f"{'model top-3':>13}{'model MRR':>11}")
    for key, label in NAMES.items():
        if key not in cv["model"]:
            continue
        b, m = cv["baseline"][key], cv["model"][key]
        print(f"   {label:<26}{m['n']:>8}{b['top1']:>15.1%}{m['top1']:>13.1%}"
              f"{m['top3']:>13.1%}{m['mrr']:>11.3f}")
    b, m = cv["baseline"]["all"]["top1"], cv["model"]["all"]["top1"]
    if b < 1:
        print(f"\n   Errors reduced by {(m - b) / (1 - b):.0%} "
              f"(top-1 errors {1 - b:.1%} -> {1 - m:.1%}); "
              f"fold-to-fold spread +/- {cv['model']['all']['top1_std']:.1%}")


def compare():
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.model_selection import GroupKFold

    class Wrap:
        def __init__(self, model):
            self.model = model

        def probability(self, rows):
            return self.model.predict_proba(np.asarray(rows))[:, 1]

    index = search.index_for_training()
    queries = ranker.build_queries(index, list(range(len(index["fields"]))), 6, 7)
    groups = np.array([index["fields"][q["target"]]["en_stem"] for q in queries])
    makers = {
        "Logistic regression (used)": None,
        "Gradient boosting": lambda: HistGradientBoostingClassifier(max_iter=200, random_state=0),
        "Random forest": lambda: RandomForestClassifier(n_estimators=200, min_samples_leaf=3,
                                                        random_state=0, n_jobs=-1),
    }
    print("\n   MODEL COMPARISON (same 5 grouped folds)")
    for name, make in makers.items():
        top1, mrr = [], []
        for tr, te in GroupKFold(n_splits=5).split(queries, groups=groups):
            x, y = ranker._dataset(index, [queries[i] for i in tr], search.candidates, 30, True)
            model = ranker._fit(x, y) if make is None else Wrap(make().fit(x, y))
            r = ranker._score_queries(index, [queries[i] for i in te], search.candidates, 30, model)
            top1.append(r["model"]["all"]["top1"])
            mrr.append(r["model"]["all"]["mrr"])
        print(f"   {name:<28} top-1 {np.mean(top1):.1%} +/- {np.std(top1):.1%}   "
              f"MRR {np.mean(mrr):.3f}")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        if not db.one("SELECT COUNT(*) AS n FROM drugs")["n"]:
            sys.exit("The database is empty. Run: python manage.py init")
        print("TRAINING THE SEARCH RANKING MODEL")
        data = search.train_model()
        report(data["cv"])
        print("\n   Feature weights (positive = makes a candidate more likely to be the answer):")
        for name, w in sorted(zip(ranker.FEATURES, data["coef"]), key=lambda t: -abs(t[1])):
            print(f"     {name:<16}{w:+.2f}")
        print(f"\n   Trained on {data['drugs']} drugs, {data['queries']} generated queries, "
              f"{data['rows']} candidate rows, in {data['seconds']} s.")
        print("   Saved to instance/search_model.json. The website uses it immediately.")
        if "--compare" in sys.argv:
            compare()
