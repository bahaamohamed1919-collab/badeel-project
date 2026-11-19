"""Smart search: finds the drug even when the name is misspelled.

Two stages:

1. TF-IDF over character n-grams + cosine similarity (scikit-learn).
   Every drug becomes a "document" (trade name + Arabic name + ingredients),
   cut into overlapping pieces of 2-4 letters ("pan", "ana", "nad", ...).
   "Panadol" and the typo "Pandol" share most pieces, so their vectors point
   in almost the same direction. This stage picks about 30 candidates fast.

2. The trained ranking model (ranker.py) re-orders those candidates, using
   features learned from thousands of generated spelling mistakes. If no model
   has been trained yet, stage 1's order is used as it is.
"""
import os

import numpy as np
from flask import current_app
from sklearn.feature_extraction.text import TfidfVectorizer

from .. import db
from . import ranker
from .normalize import ALIASES, norm_text

_state = {"key": None, "vectorizer": None, "matrix": None, "ids": [], "fields": []}

CANDIDATES = 30


def _ensure_index():
    """(Re)build the index only when the drug data has changed."""
    key = (current_app.config["DATABASE"], db.get_setting("data_version", "0"))
    if _state["key"] == key:
        return
    rows = db.query("SELECT id, trade_name, trade_name_ar, ingredient_key FROM drugs ORDER BY id")
    ids, fields, docs = [], [], []
    for r in rows:
        doc = " ".join(filter(None, [
            norm_text(r["trade_name"]), norm_text(r["trade_name_ar"]),
            r["ingredient_key"].replace("|", " "),
        ]))
        ids.append(r["id"])
        docs.append(doc)
        fields.append(ranker.drug_fields(r["trade_name"], r["trade_name_ar"], doc))
    vectorizer = matrix = None
    if docs:
        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
        matrix = vectorizer.fit_transform(docs)
    _state.update(key=key, vectorizer=vectorizer, matrix=matrix, ids=ids, fields=fields)


def candidates(q, k=CANDIDATES):
    """Stage 1. Returns [(position_in_index, raw_tfidf, baseline_score), ...] best first.

    The baseline score is the TF-IDF similarity plus two small bonuses, so a
    name that starts with exactly what was typed comes first."""
    if _state["matrix"] is None:
        return []
    raw = (_state["matrix"] @ _state["vectorizer"].transform([q]).T).toarray().ravel()
    score = raw.copy()
    for i, f in enumerate(_state["fields"]):
        if f["en"].startswith(q) or (f["ar"] and f["ar"].startswith(q)):
            score[i] += 0.6
        elif q in f["doc"]:
            score[i] += 0.25
    order = np.argsort(-score, kind="stable")[:k]
    return [(int(i), float(raw[i]), float(score[i])) for i in order if score[i] > 0]


def _instance_dir():
    return os.path.dirname(current_app.config["DATABASE"])


def search(text, limit=30, min_score=0.12, use_model=True):
    """Return [(drug_id, score), ...] best first."""
    _ensure_index()
    q = norm_text(text)
    if not q or _state["matrix"] is None:
        return []
    q = ALIASES.get(q, q)                     # "acetaminophen" -> "paracetamol"

    ranked = candidates(q)
    model = ranker.load_model(_instance_dir()) if use_model else None
    if model is None or not ranked:
        return [(_state["ids"][i], s) for i, _, s in ranked[:limit] if s >= min_score]

    rows = [ranker.features(q, _state["fields"][i], raw, pos + 1)
            for pos, (i, raw, _) in enumerate(ranked)]
    probability = model.probability(rows)
    # Keep what stage 1 already trusted, plus what the model is fairly sure about.
    kept = [(probability[j], ranked[j][0]) for j in range(len(ranked))
            if ranked[j][2] >= min_score or probability[j] >= 0.5]
    kept.sort(key=lambda t: -t[0])
    return [(_state["ids"][i], float(p)) for p, i in kept[:limit]]


def index_for_training():
    """The current index in the shape ranker.train() expects."""
    _ensure_index()
    return {"fields": _state["fields"]}


def train_model(log=print, **kwargs):
    index = index_for_training()
    if len(index["fields"]) > 3000:
        # A national drug list: train on a random 1,500 brands, 2 typos of each kind,
        # with every product still a candidate. Same setting as Chapter 1 (1.6.6);
        # 6 typos per kind on 2,000 brands would take four times longer for the same result.
        kwargs.setdefault("max_drugs", 1500)
        kwargs.setdefault("per_kind", 2)
    return ranker.train(index, candidates, _instance_dir(),
                        data_version=db.get_setting("data_version", "0"), log=log, **kwargs)
