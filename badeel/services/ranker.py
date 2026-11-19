"""Trained search model: learns to rank the right drug first when the name is misspelled.

How it works
------------
1. TF-IDF (search.py) quickly picks about 30 candidate drugs for what was typed.
2. For each candidate we compute 12 features that describe HOW the typed text
   resembles the drug name: edit-distance similarity, shared beginning, same
   first letter, same number (400 vs 600), length ratio, and so on.
3. A logistic-regression model, trained on examples, turns those features into
   a probability that this candidate is the drug the user meant.

Where the training data comes from (self-supervised)
----------------------------------------------------
Nobody has to label anything. We take every drug name in the database and
misspell it on purpose in the ways people really make mistakes: a missing or
extra letter, two letters swapped, a neighbouring key on the keyboard,
sound-alike spellings (ph/f, c/k, س/ص, ت/ط), only the first letters typed, and
Arabic spelling variants. Each misspelling comes with its correct answer, so
we know the label for free.

The features describe the RELATIONSHIP between the typed text and a name, not
the names themselves. That is why the model also works on drugs it never saw
during training, which we check with grouped cross-validation (groups = brand
families, so a brand is never in training and testing at the same time).

Safety: this model only orders search results. It never decides which drug is
an alternative; that stays a fixed rule in recommender.py.

The trained model is stored as plain JSON numbers (no pickle), so loading it
can never execute code.
"""
import json
import os
import random
import re
import time
from datetime import datetime, timezone

import numpy as np

from .normalize import norm_text

FEATURES = [
    "tfidf",            # TF-IDF cosine similarity (from search.py)
    "tfidf_rank",       # 1 / position in the TF-IDF list
    "name_sim",         # edit-distance similarity to the full name
    "stem_sim",         # edit-distance similarity to the name without numbers
    "prefix",           # share of the typed text that matches the start of the name
    "starts_with",      # the name starts with exactly what was typed
    "first_letter",     # same first letter
    "contains",         # typed text appears inside the name or ingredients
    "length_ratio",     # shorter length / longer length
    "number_match",     # typed a number and the name has it (Brufen 400)
    "number_mismatch",  # typed a number and the name has a different one
    "is_arabic",        # the query is in Arabic
]

_ARABIC = re.compile(r"[؀-ۿ]")
_UNITS = re.compile(r"\b(mg|mcg|g|gm|ml|iu|مجم|ملجم|جم|مل)\b")


def is_arabic(text):
    return bool(_ARABIC.search(text or ""))


def stem(name):
    """'panadol 500' -> 'panadol';  'بروفين 400' -> 'بروفين'."""
    s = _UNITS.sub(" ", re.sub(r"[\d.,/%+()-]+", " ", name or ""))
    return re.sub(r"\s+", " ", s).strip()


def levenshtein(a, b):
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def similarity(a, b):
    if not a or not b:
        return 0.0
    return 1.0 - levenshtein(a, b) / max(len(a), len(b))


def common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def drug_fields(trade_name, trade_name_ar, doc):
    en, ar = norm_text(trade_name), norm_text(trade_name_ar)
    return {"en": en, "ar": ar, "en_stem": stem(en), "ar_stem": stem(ar), "doc": doc}


def features(q, f, tfidf_score, rank):
    arabic = is_arabic(q)
    name, name_stem = (f["ar"], f["ar_stem"]) if arabic and f["ar"] else (f["en"], f["en_stem"])
    q_stem = stem(q) or q
    q_numbers = set(re.findall(r"\d+", q))
    name_numbers = set(re.findall(r"\d+", f["en"] + " " + f["ar"]))
    return [
        tfidf_score,
        1.0 / rank,
        similarity(q, name),
        similarity(q_stem, name_stem),
        common_prefix(q_stem, name_stem) / max(len(q_stem), 1),
        1.0 if name.startswith(q) else 0.0,
        1.0 if name and q[0] == name[0] else 0.0,
        1.0 if q in f["doc"] else 0.0,
        min(len(q_stem), len(name_stem)) / max(len(q_stem), len(name_stem), 1),
        1.0 if q_numbers and q_numbers <= name_numbers else 0.0,
        1.0 if q_numbers and not q_numbers <= name_numbers else 0.0,
        1.0 if arabic else 0.0,
    ]


# ------------------------------------------------------------- the model
class Model:
    """Standardise the features, then logistic regression."""

    def __init__(self, data):
        self.data = data
        self.mean = np.array(data["mean"])
        self.scale = np.array(data["scale"])
        self.coef = np.array(data["coef"])
        self.intercept = float(data["intercept"])

    def probability(self, rows):
        x = (np.asarray(rows, dtype=float) - self.mean) / self.scale
        return 1.0 / (1.0 + np.exp(-(x @ self.coef + self.intercept)))


def model_path(instance_dir):
    return os.path.join(instance_dir, "search_model.json")


_cache = {"path": None, "mtime": None, "model": None}


def load_model(instance_dir):
    """Cached; reloads automatically when the file is retrained."""
    path = model_path(instance_dir)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if _cache["path"] != path or _cache["mtime"] != mtime:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("features") != FEATURES:
                return None                       # trained with another feature set
            _cache.update(path=path, mtime=mtime, model=Model(data))
        except (OSError, ValueError, KeyError):
            return None
    return _cache["model"]


def model_info(instance_dir):
    path = model_path(instance_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return {k: data.get(k) for k in ("trained_at", "drugs", "queries", "rows", "data_version",
                                     "cv", "seconds")}


# ------------------------------------------------- self-supervised data
LETTERS = "abcdefghijklmnopqrstuvwxyz"
AR_LETTERS = "ابتثجحخدذرزسشصضطظعغفقكلمنهوي"
KEYBOARD = {
    "q": "wa", "w": "qes", "e": "wrd", "r": "etf", "t": "ryg", "y": "tuh", "u": "yij",
    "i": "uok", "o": "ipl", "p": "ol", "a": "qsz", "s": "awdz", "d": "sefx", "f": "drgc",
    "g": "fthv", "h": "gyjb", "j": "hukn", "k": "jilm", "l": "kop", "z": "asx", "x": "zdc",
    "c": "xfv", "v": "cgb", "b": "vhn", "n": "bjm", "m": "nk",
}
PHONETIC_EN = [("ph", "f"), ("f", "ph"), ("c", "k"), ("k", "c"), ("x", "ks"), ("y", "i"),
               ("i", "y"), ("ou", "o"), ("th", "t"), ("ll", "l"), ("ss", "s"), ("ine", "in"),
               ("one", "on"), ("ole", "ol"), ("q", "k"), ("z", "s"), ("s", "z"), ("e", "a")]
PHONETIC_AR = [("س", "ص"), ("ص", "س"), ("ت", "ط"), ("ط", "ت"), ("ز", "ذ"), ("ذ", "ز"),
               ("ك", "ق"), ("ق", "ك"), ("د", "ض"), ("ض", "د"), ("ه", "ح"), ("ث", "س")]

KINDS = ["one_edit", "two_edits", "keyboard", "phonetic", "prefix", "arabic"]


def _edit(word, rng, alphabet):
    letters = [i for i, c in enumerate(word) if c.isalpha()]
    if len(letters) < 3:
        return word
    i = rng.choice(letters[1:]) if rng.random() > 0.1 else letters[0]
    kind = rng.choice(["delete", "insert", "replace", "swap"])
    if kind == "delete":
        return word[:i] + word[i + 1:]
    if kind == "insert":
        return word[:i] + rng.choice(alphabet) + word[i:]
    if kind == "replace":
        return word[:i] + rng.choice(alphabet) + word[i + 1:]
    if i + 1 < len(word):
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    return word[:i]


def _keyboard(word, rng):
    spots = [i for i, c in enumerate(word) if c in KEYBOARD and i > 0]
    if not spots:
        return word
    i = rng.choice(spots)
    return word[:i] + rng.choice(KEYBOARD[word[i]]) + word[i + 1:]


def _phonetic(word, rng, rules):
    options = [(a, b) for a, b in rules if a in word[1:]]
    if not options:
        return None
    a, b = rng.choice(options)
    spots = [m.start() for m in re.finditer(re.escape(a), word) if m.start() > 0]
    i = rng.choice(spots)
    return word[:i] + b + word[i + len(a):]


def make_query(f, kind, rng):
    """Returns (query, answer_type) or None. answer_type 'exact' means only this
    drug is correct; 'stem' means any drug of the same brand name is correct."""
    if kind == "arabic":
        if not f["ar_stem"] or len(f["ar_stem"]) < 3:
            return None
        base, answer = (f["ar"], "exact") if rng.random() < 0.4 else (f["ar_stem"], "stem")
        out = _phonetic(base, rng, PHONETIC_AR) if rng.random() < 0.4 else None
        if out is None:
            out = _edit(base, rng, AR_LETTERS)
        return out, answer
    if len(f["en_stem"]) < 3:
        return None
    base, answer = (f["en"], "exact") if rng.random() < 0.4 else (f["en_stem"], "stem")
    if kind == "one_edit":
        out = _edit(base, rng, LETTERS)
    elif kind == "two_edits":
        out = _edit(_edit(base, rng, LETTERS), rng, LETTERS)
    elif kind == "keyboard":
        out = _keyboard(base, rng)
    elif kind == "phonetic":
        out = _phonetic(base, rng, PHONETIC_EN) or _edit(base, rng, LETTERS)
    else:                                                   # prefix: still typing
        s = f["en_stem"]
        if len(s) < 5:
            return None
        out, answer = s[:rng.randint(4, len(s) - 1)], "stem"
    if not out or out == base:
        return None
    return out, answer


def correct_set(index, target, answer, key="en_stem"):
    """Which drugs count as a right answer for a generated query."""
    if answer == "exact":
        return {target}
    value = index["fields"][target][key]
    return {i for i, g in enumerate(index["fields"]) if value and g[key] == value} | {target}


def build_queries(index, targets, per_kind, seed):
    rng = random.Random(seed)
    queries = []
    for t in targets:
        f = index["fields"][t]
        for kind in KINDS:
            made = 0
            for _ in range(per_kind * 4):
                if made >= per_kind:
                    break
                result = make_query(f, kind, rng)
                if not result:
                    continue
                q, answer = result
                q = norm_text(q)
                if not q:
                    continue
                ok = correct_set(index, t, answer, "ar_stem" if kind == "arabic" else "en_stem")
                queries.append({"q": q, "kind": kind, "target": t, "ok": ok})
                made += 1
    return queries


def candidate_rows(index, q, candidates_fn, k):
    """Candidates and their features. Cached per query while training, because
    cross-validation looks at every query several times."""
    cache = index.setdefault("_cache", {})
    if q not in cache:
        ranked = candidates_fn(q, k)                 # [(index, raw tfidf, baseline score)]
        rows = [features(q, index["fields"][i], raw, pos + 1)
                for pos, (i, raw, _) in enumerate(ranked)]
        cache[q] = (ranked, rows)
    return cache[q]


# ---------------------------------------------------------------- training
def _fit(x, y):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler().fit(x)
    scale = np.where(scaler.scale_ == 0, 1.0, scaler.scale_)
    lr = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced")
    lr.fit((x - scaler.mean_) / scale, y)
    return Model({"mean": scaler.mean_.tolist(), "scale": scale.tolist(),
                  "coef": lr.coef_[0].tolist(), "intercept": float(lr.intercept_[0])})


def _dataset(index, queries, candidates_fn, k, include_missing):
    x, y = [], []
    for item in queries:
        ranked, rows = candidate_rows(index, item["q"], candidates_fn, k)
        present = {i for i, _, _ in ranked}
        for (i, _, _), row in zip(ranked, rows):
            x.append(row)
            y.append(1 if i in item["ok"] else 0)
        if include_missing and not present & item["ok"]:
            # The right drug was not even a candidate: still teach the model what it looks like.
            t = item["target"]
            x.append(features(item["q"], index["fields"][t], 0.0, k + 1))
            y.append(1)
    return np.array(x, dtype=float), np.array(y)


def _rank_of_answer(order, ok):
    for pos, i in enumerate(order, 1):
        if i in ok:
            return pos
    return None


def _score_queries(index, queries, candidates_fn, k, model):
    stats = {}
    for item in queries:
        ranked, rows = candidate_rows(index, item["q"], candidates_fn, k)
        base_order = [i for i, _, _ in ranked]                  # already in baseline order
        if model is not None and rows:
            p = model.probability(rows)
            model_order = [base_order[j] for j in np.argsort(-p, kind="stable")]
        else:
            model_order = base_order
        for name, order in (("baseline", base_order), ("model", model_order)):
            r = _rank_of_answer(order, item["ok"])
            for bucket in ("all", item["kind"]):
                s = stats.setdefault(name, {}).setdefault(bucket, [0, 0, 0, 0.0])
                s[0] += 1
                s[1] += r == 1
                s[2] += r is not None and r <= 3
                s[3] += 1 / r if r else 0
    out = {}
    for name, buckets in stats.items():
        out[name] = {b: {"n": s[0], "top1": s[1] / s[0], "top3": s[2] / s[0], "mrr": s[3] / s[0]}
                     for b, s in buckets.items()}
    return out


def train(index, candidates_fn, instance_dir, data_version="0", per_kind=6, k=30, folds=5,
          seed=7, max_drugs=2000, log=print):
    """Grouped cross-validation, then a final model on all drugs, saved as JSON."""
    from sklearn.model_selection import GroupKFold
    started = time.perf_counter()
    n = len(index["fields"])
    if n < 10:
        raise ValueError("At least 10 drugs are needed to train the search model.")
    targets = list(range(n))
    if n > max_drugs:
        targets = random.Random(seed).sample(targets, max_drugs)
    queries = build_queries(index, targets, per_kind, seed)
    groups = np.array([index["fields"][item["target"]]["en_stem"] or str(item["target"])
                       for item in queries])
    folds = max(2, min(folds, len(set(groups))))
    log(f"  {len(targets)} drugs, {len(queries)} generated queries, {folds}-fold grouped CV")

    fold_results = []
    for fold, (tr, te) in enumerate(GroupKFold(n_splits=folds).split(queries, groups=groups), 1):
        train_q = [queries[i] for i in tr]
        test_q = [queries[i] for i in te]
        x, y = _dataset(index, train_q, candidates_fn, k, include_missing=True)
        model = _fit(x, y)
        fold_results.append(_score_queries(index, test_q, candidates_fn, k, model))
        log(f"  fold {fold}: baseline top-1 {fold_results[-1]['baseline']['all']['top1']:.1%}"
            f"  model top-1 {fold_results[-1]['model']['all']['top1']:.1%}")

    cv = {}
    for name in ("baseline", "model"):
        cv[name] = {}
        for bucket in ["all"] + KINDS:
            vals = [fr[name][bucket] for fr in fold_results if bucket in fr[name]]
            if not vals:
                continue
            cv[name][bucket] = {
                "n": sum(v["n"] for v in vals),
                **{m: float(np.mean([v[m] for v in vals])) for m in ("top1", "top3", "mrr")},
                "top1_std": float(np.std([v["top1"] for v in vals])),
            }

    x, y = _dataset(index, queries, candidates_fn, k, include_missing=True)
    final = _fit(x, y)
    data = {
        "features": FEATURES, **final.data,
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "drugs": len(targets), "queries": len(queries), "rows": int(len(y)),
        "positives": int(y.sum()), "data_version": str(data_version), "cv": cv,
        "seconds": round(time.perf_counter() - started, 1),
    }
    path = model_path(instance_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    index.pop("_cache", None)
    return data
