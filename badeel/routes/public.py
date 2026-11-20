"""Pages anyone can open: home, search, drug page, ingredient page, about."""
from flask import (Blueprint, abort, g, jsonify, redirect, render_template, request,
                   session, url_for)

from .. import db, security
from ..services import conditions, interactions, labels, recommender, search as search_service
from ..services.normalize import canon_ingredient, display_name

bp = Blueprint("public", __name__)


def _fetch_in_order(ids):
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    rows = db.query(
        f"SELECT d.*, (SELECT COUNT(*) FROM drugs x WHERE x.composition_key = d.composition_key "
        f"AND x.form = d.form AND x.id != d.id AND d.strength_known = 1) AS alt_count "
        f"FROM drugs d WHERE d.id IN ({marks})", ids)
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def user_allergies():
    if not g.user:
        return set()
    text = security.decrypt(g.user["allergies_enc"])
    return {canon_ingredient(a) for a in text.replace("،", ",").split(",") if a.strip()}


@bp.route("/")
def home():
    stats = db.one("SELECT (SELECT COUNT(*) FROM drugs) AS drugs, "
                   "(SELECT COUNT(*) FROM ingredients) AS ingredients")
    # A real match from the database, shown as a worked example on the home page.
    example = []
    group = db.one(
        "SELECT composition_key, form FROM drugs WHERE strength_known = 1 AND price IS NOT NULL "
        "GROUP BY composition_key, form HAVING COUNT(*) > 1 ORDER BY COUNT(*) DESC, "
        "composition_key LIMIT 1")
    if group:
        example = db.query(
            "SELECT * FROM drugs WHERE composition_key = ? AND form = ? ORDER BY price DESC LIMIT 3",
            (group["composition_key"], group["form"]))
    return render_template("home.html", stats=stats, example=example)


@bp.route("/search")
def search():
    q = request.args.get("q", "").strip()[:100]
    results = []
    if q:
        results = _fetch_in_order([i for i, _ in search_service.search(q, limit=30)])
        if g.user:
            last = db.one("SELECT query FROM search_history WHERE user_id = ? "
                          "ORDER BY id DESC LIMIT 1", (g.user["id"],))
            if not last or last["query"] != q:
                db.execute("INSERT INTO search_history (user_id, query, created_at) "
                           "VALUES (?, ?, ?)", (g.user["id"], q, db.now()))
                db.commit()
    return render_template("search.html", q=q, results=results)


@bp.route("/api/suggest")
def suggest():
    """Autocomplete for the search box (called by static/js/app.js)."""
    q = request.args.get("q", "").strip()[:60]
    rows = _fetch_in_order([i for i, _ in search_service.search(q, limit=7)]) if len(q) >= 2 else []
    return jsonify([{
        "url": url_for("public.drug", drug_id=r["id"]),
        "name": r["trade_name"], "name_ar": r["trade_name_ar"] or "",
        "detail": " ".join(filter(None, [r["ingredients_display"], r["strength_display"]])),
    } for r in rows])


@bp.route("/drug/<int:drug_id>")
def drug(drug_id):
    d = db.one("SELECT * FROM drugs WHERE id = ?", (drug_id,))
    if not d:
        abort(404)
    alternatives = recommender.get_alternatives(d)
    ingredients = db.query(
        "SELECT i.id, i.name, di.strength_text FROM drug_ingredients di "
        "JOIN ingredients i ON i.id = di.ingredient_id WHERE di.drug_id = ? ORDER BY i.name",
        (drug_id,))
    allergy_hits = sorted(user_allergies() & set(d["ingredient_key"].split("|")))
    is_favorite = bool(g.user and db.one(
        "SELECT 1 FROM favorites WHERE user_id = ? AND drug_id = ?", (g.user["id"], drug_id)))
    saved_interactions = interactions.with_saved_medicines(d, g.user["id"]) if g.user else []
    disease = conditions.for_drug(d)
    condition_warnings = conditions.warnings_for(d, conditions.user_groups(g.user))
    return render_template(
        "drug.html", d=d, alt=alternatives, ingredients=ingredients,
        allergy_hits=[display_name(a) for a in allergy_hits], is_favorite=is_favorite,
        display_name=display_name, leaflet=labels.for_drug(d),
        leaflet_sections=labels.SECTION_LABELS, saved_interactions=saved_interactions,
        interaction_count=interactions.count_for(d), severity_labels=interactions.SEVERITY_LABELS,
        disease=disease, condition_warnings=condition_warnings,
        concept_group=conditions.CONCEPT_TO_GROUP)


@bp.route("/ingredient/<int:ingredient_id>")
def ingredient(ingredient_id):
    ing = db.one("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,))
    if not ing:
        abort(404)
    drugs = db.query(
        "SELECT d.* FROM drugs d JOIN drug_ingredients di ON di.drug_id = d.id "
        "WHERE di.ingredient_id = ? ORDER BY d.form, d.strength_display, d.price IS NULL, d.price",
        (ingredient_id,))
    return render_template("ingredient.html", name=display_name(ing["name"]), drugs=drugs)


@bp.route("/disease")
def disease():
    """Products whose ingredients are listed as treating a disease."""
    group = conditions.GROUPS.get(request.args.get("group", ""))
    name = request.args.get("name", "").strip()[:200]
    if group:
        concepts, title = group["concepts"], (group["en"], group["ar"])
    elif name:
        concepts, title = [name], (name, name)
    else:
        abort(404)
    ingredients, products = conditions.products_treating(concepts)
    return render_template("disease.html", title=title, concepts=concepts, group=group,
                           ingredients=[display_name(i) for i in ingredients], drugs=products)


@bp.route("/about")
def about():
    return render_template("about.html")


@bp.route("/lang/<code>")
def set_lang(code):
    if code in ("ar", "en"):
        session["lang"] = code
    return redirect(security.safe_next(request.args.get("next")) or url_for("public.home"))
