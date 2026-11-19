# Outside data sources

Added by `python manage.py collect-data`. Files are downloaded unchanged into
`data/raw/<source>/<date>/` with a `SOURCE.json` (address, licence, date).
`data/raw/` is not committed to Git: the files are large and some licences do
not allow re-publishing them.

| Source | What Badeel takes from it | Licence | Table |
|---|---|---|---|
| DDInter (http://ddinter.scbdd.com/) | Drug-drug interactions with severity (Major, Moderate, Minor, Unknown) | Reported as CC BY-NC-SA 4.0: confirm on the DDInter site before publishing derived data | `drug_interactions` |
| openFDA drug labels (https://open.fda.gov/data/downloads/) | U.S. package leaflets: indications, dosage, children, older adults, pregnancy, breastfeeding, contraindications, warnings | Public domain (CC0) | `ingredient_labels` |

## Matching

Both sources are matched on the active ingredient, not on the trade name,
with `normalize.moiety_key`: salts and hydrates are removed only for this
match (`diclofenac sodium` and `diclofenac potassium` -> `diclofenac`). A
combination product only gets a leaflet written for exactly the same set of
ingredients.

## Safety

The leaflet is a U.S. leaflet, in English. The drug page says so and says
that Badeel does not choose doses. The children note (`pediatric_note`) is
read by fixed sentence rules (`labels.pediatric_note`); when no rule matches,
nothing is shown, which does not mean the medicine is safe for children. The
precision of these rules on real leaflets still has to be measured.

## If the download is blocked

Download the files in a browser and load them by hand:

    python manage.py load-interactions data/raw/ddinter/*.csv
    python manage.py load-labels data/raw/openfda_labels/*.json.zip
    python manage.py enrichment-report

Re-run both `load-` commands after importing a new drug list: the leaflets
kept are the ones that match the products in the database.
