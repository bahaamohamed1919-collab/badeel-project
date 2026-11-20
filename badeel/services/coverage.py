"""How much of the drug list the outside sources cover.

These are the numbers for the data-enrichment table of the paper:
how many products, ingredients and ingredient sets could be matched to
DDInter and to an openFDA leaflet.
"""
from .. import db
from .normalize import moiety_key, moiety_set_key


def _pct(part, whole):
    return f"{part:,} of {whole:,} ({part / whole:.1%})" if whole else f"{part:,} of 0"


def report():
    drugs = db.query("SELECT id, ingredient_key FROM drugs")
    moieties = {moiety_key(n) for d in drugs for n in d["ingredient_key"].split("|") if n}
    in_ddi = {r["m"] for r in db.query(
        "SELECT ingredient_a AS m FROM drug_interactions "
        "UNION SELECT ingredient_b FROM drug_interactions")}
    label_keys = {r["ingredient_key"] for r in db.query("SELECT ingredient_key FROM ingredient_labels")}

    def keys(d):
        return moiety_set_key(d["ingredient_key"].split("|"))

    single = [d for d in drugs if "|" not in keys(d)]
    combo = [d for d in drugs if "|" in keys(d)]
    with_ddi = [d for d in drugs if any(moiety_key(n) in in_ddi for n in d["ingredient_key"].split("|"))]
    cond_ing = {r["ingredient"] for r in db.query("SELECT DISTINCT ingredient FROM ingredient_conditions")}
    with_ind = {r["ingredient"] for r in db.query(
        "SELECT DISTINCT ingredient FROM ingredient_conditions WHERE relation = 'indication'")}
    with_contra = {r["ingredient"] for r in db.query(
        "SELECT DISTINCT ingredient FROM ingredient_conditions WHERE relation = 'contraindication'")}

    def any_in(d, group):
        return any(moiety_key(n) in group for n in d["ingredient_key"].split("|"))

    notes = {r["pediatric_note"] or "none": r["n"] for r in db.query(
        "SELECT pediatric_note, COUNT(*) AS n FROM ingredient_labels GROUP BY pediatric_note")}

    return {
        "products": len(drugs),
        "ingredients": len(moieties),
        "ingredient_sets": len({keys(d) for d in drugs}),
        "interaction_pairs": db.one("SELECT COUNT(*) AS n FROM drug_interactions")["n"],
        "ingredients_in_ddinter": len(moieties & in_ddi),
        "products_with_interactions": len(with_ddi),
        "ingredient_sets_with_leaflet": len({keys(d) for d in drugs} & label_keys),
        "products_with_leaflet": sum(keys(d) in label_keys for d in drugs),
        "single_with_leaflet": sum(keys(d) in label_keys for d in single),
        "single": len(single),
        "combo_with_leaflet": sum(keys(d) in label_keys for d in combo),
        "combo": len(combo),
        "pediatric_notes": notes,
        "condition_rows": db.one("SELECT COUNT(*) AS n FROM ingredient_conditions")["n"],
        "ingredients_in_drugcentral": len(moieties & cond_ing),
        "products_with_indication": sum(any_in(d, with_ind) for d in drugs),
        "products_with_contraindication": sum(any_in(d, with_contra) for d in drugs),
        "conditions_loaded": db.get_setting("conditions_loaded"),
        "interactions_loaded": db.get_setting("interactions_loaded"),
        "labels_loaded": db.get_setting("labels_loaded"),
    }


def as_text(r):
    lines = [
        "DATA ENRICHMENT COVERAGE",
        f"  Products in the database            : {r['products']:,}",
        f"  Distinct ingredients (moieties)     : {r['ingredients']:,}",
        f"  Distinct ingredient sets            : {r['ingredient_sets']:,}",
        "",
        f"DDInter interactions (loaded {r['interactions_loaded'] or 'never'})",
        f"  Interaction pairs stored            : {r['interaction_pairs']:,}",
        f"  Ingredients found in DDInter        : {_pct(r['ingredients_in_ddinter'], r['ingredients'])}",
        f"  Products with at least one          : {_pct(r['products_with_interactions'], r['products'])}",
        "",
        f"openFDA leaflets (loaded {r['labels_loaded'] or 'never'})",
        f"  Ingredient sets with a leaflet      : {_pct(r['ingredient_sets_with_leaflet'], r['ingredient_sets'])}",
        f"  Products with a leaflet             : {_pct(r['products_with_leaflet'], r['products'])}",
        f"    single-ingredient products        : {_pct(r['single_with_leaflet'], r['single'])}",
        f"    combination products              : {_pct(r['combo_with_leaflet'], r['combo'])}",
        "  Children section, as read by the rules:",
    ]
    tail = [
        "",
        f"DrugCentral diseases (loaded {r['conditions_loaded'] or 'never'})",
        f"  Ingredient-disease rows stored      : {r['condition_rows']:,}",
        f"  Ingredients found in DrugCentral    : {_pct(r['ingredients_in_drugcentral'], r['ingredients'])}",
        f"  Products with a known use           : {_pct(r['products_with_indication'], r['products'])}",
        f"  Products with a contraindication    : {_pct(r['products_with_contraindication'], r['products'])}",
    ]
    for note, n in sorted(r["pediatric_notes"].items()):
        lines.append(f"    {note:<32}  : {n:,}")
    return "\n".join(lines + tail)
