# Badeel enriched Egyptian drug dataset

Version 1.0, built on 2026-11-19 from the sources listed below.

The Egyptian drug list (22,757 products) is cleaned by Badeel and linked to
three open sources: drug-drug interactions, package leaflets, and the
diseases each active ingredient treats or must not be used with.

The files are for research and education. **They are not medical advice.**
The disclaimer at the end of this file applies to all of them.

## Files

| File | Rows | What one row is | Source | Licence |
|---|---:|---|---|---|
| `products.csv` | 22,757 | One product on the Egyptian market, after cleaning | Egyptian drug list | CC0 1.0 |
| `product_ingredients.csv` | 57,932 | One ingredient of one product, with its strength | Egyptian drug list | CC0 1.0 |
| `interactions.csv` | 72,490 | One interaction between two ingredients | DDInter 2.0 | CC BY-NC-SA 4.0 |
| `conditions.csv` | 32,291 | One ingredient and one disease it treats or is listed against | DrugCentral | CC BY-SA 4.0 |
| `leaflets.csv` | 1,007 | U.S. leaflet sections for one set of ingredients | openFDA drug labels | Public domain |
| `patient_condition_groups.csv` | 34 | One simple condition group, with Arabic label | Badeel project | CC0 1.0 |

`interactions.csv` and `conditions.csv` only keep ingredients found in the
Egyptian products. The full source files are larger.

## How the files join

```
products.product_id ──< product_ingredients.product_id
product_ingredients.ingredient ──< interactions.ingredient_a / ingredient_b
product_ingredients.ingredient ──< conditions.ingredient
products.ingredient_key ── leaflets.ingredient_key   (after moiety normalisation, see below)
```

The `ingredient` column is a normalised name (`moiety_key` in
`badeel/services/normalize.py`): lower case, synonyms unified
(`acetaminophen` → `paracetamol`), and trailing salt words removed only for
matching with outside sources (`diclofenac sodium` → `diclofenac`). The exact
ingredient as sold is kept in `product_ingredients.ingredient_name`.

## Columns

**products.csv**
`product_id`, `trade_name`, `trade_name_ar`, `ingredients`, `strength`,
`form` (normalised: tablet, syrup, ...), `company`, `drug_class`, `price_egp`,
`pack_count` (units in the pack when it could be read from the name),
`price_per_unit_egp`, `ingredient_key`, `composition_key` (ingredients with
strengths; two products with the same `composition_key` and `form` are exact
alternatives), `strength_known` (1 when every strength and the form are known).

**interactions.csv**
`ingredient_a`, `ingredient_b` (alphabetical order, so each pair appears
once), `severity` (`major`, `moderate`, `minor`, `unknown`), `source`.

**conditions.csv**
`ingredient`, `condition` (DrugCentral concept name, e.g. `Peptic ulcer`),
`relation` (`indication`, `contraindication`, `off_label`), `umls_cui`, `source`.

**leaflets.csv**
`ingredient_key`, `brand_name`, `effective_date` (YYYYMMDD), `set_id` (opens
the leaflet on DailyMed: `https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=<set_id>`),
`label_id`, `pediatric_note` (`min_age`, `not_established` or empty, read by
fixed sentence rules), `min_age_months`, and the sections `boxed_warning`,
`indications`, `dosage`, `contraindications`, `pediatric`, `geriatric`,
`pregnancy`, `lactation`, `warnings`.

**patient_condition_groups.csv**
`key`, `label_en`, `label_ar`, `concepts` (DrugCentral concept names joined by `;`).

## Numbers

| | |
|---|---|
| Products | 22,757 |
| Products with every strength and the form known (can get exact alternatives) | 12,206 (53.6%) |
| Products with a pack size (price per unit available) | 11,782 (51.8%) |
| Products with a known use (DrugCentral) | 18,290 (80.4%) |
| Products with a listed contraindication (DrugCentral) | 16,270 (71.5%) |
| Products with at least one interaction (DDInter) | 16,326 (71.7%) |
| Products with a U.S. leaflet for the same ingredients (openFDA) | 9,943 (43.7%) |
| Interactions by severity | major 8,957; moderate 34,125; minor 3,113; unknown 26,295 |
| Disease rows by relation | contraindication 21,344; indication 8,699; off-label 2,248 |
| Distinct diseases | 3,360 |

## Sources

| Source | Downloaded | Address | Licence |
|---|---|---|---|
| Egyptian drug list | 2026-11-14 | https://github.com/karem505/egyptian-drug-database | CC0 1.0 |
| DDInter 2.0 | 2026-11-19 | https://ddinter2.scbdd.com/download/ | CC BY-NC-SA 4.0 (stated on https://ddinter2.scbdd.com/terms/) |
| openFDA drug labels | 2026-11-19 | https://api.fda.gov/download.json | Public domain |
| DrugCentral (dump of 2026-09-25) | 2026-11-19 | https://drugcentral.org/download | CC BY-SA 4.0 (stated on https://drugcentral.org/privacy) |

**Using these files.** Credit each source you use. `interactions.csv` may
not be used commercially. If you change `interactions.csv` or
`conditions.csv` and share the result, share it under the same licence as
the original file.

## Rebuilding the files

```bash
python manage.py import-csv data/egypt/egyptian-drugs.csv --replace
python manage.py collect-data
python manage.py export-dataset dataset
```

## Known limitations

1. **The Egyptian list's origin is not stated by its publisher.** An automatic
   cross-check with the EDA's official OTC list (January 2026, 355 products)
   found 267 products by exact brand name. Of these, 93.3% have the same active
   ingredients (84.3% spelled the same, 9.0% with spelling differences such as
   "Phenylepherine"), and 86.2% of the 123 products with the same form and a
   readable strength have the same strength. The 80 remaining differences and
   a random sample of 100 products still need a person to check them
   (`data/verification/`). Prices change often. Details:
   `docs/results/eda_crosscheck.txt`.
2. **DrugCentral contraindications are broad.** They are gathered from many
   leaflets, including combination products. For example ibuprofen has 85
   listed conditions, including "Agoraphobia". Their precision for single
   products has not been measured.
3. **Leaflets are U.S. leaflets in English**, matched by active ingredient.
   They may differ from Egyptian leaflets. A combination product only gets a
   leaflet written for exactly the same ingredients.
4. **`pediatric_note` is read by fixed sentence rules.** An empty value does
   not mean the medicine is safe for children. Its precision has not been
   measured.
5. **Matching is by ingredient name.** About 14% of distinct Egyptian
   ingredient names are found in DDInter and about 20% in DrugCentral. Most of
   the names not found are supplements, cosmetics and plant extracts, which
   these sources do not cover. Because common medicines are found, coverage
   by product is much higher (see Numbers).
6. **The Arabic labels in `patient_condition_groups.csv` were written by the
   project** and have not yet been reviewed by a pharmacist.

## Citation

If you use this dataset, cite the Badeel project and each source you use:

- Badeel: A Secure Medication Alternative Recommendation System. Egyptian Chinese University, 2026.
- Xiong G. et al. DDInter 2.0: an enhanced drug interaction resource with expanded data coverage, new interaction types, and improved user interface. Nucleic Acids Research, 2025.
- Avram S. et al. DrugCentral. Nucleic Acids Research (latest update paper).
- U.S. Food and Drug Administration, openFDA drug label dataset.

## Disclaimer

This dataset can contain errors and gaps. The absence of an interaction or a
contraindication does not mean none exists. Do not use it to choose, start,
stop or change any medicine. Ask a pharmacist or a doctor.
