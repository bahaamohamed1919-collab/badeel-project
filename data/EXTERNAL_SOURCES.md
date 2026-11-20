# Outside data sources

Added by `python manage.py collect-data`. Files are downloaded unchanged into
`data/raw/<source>/<date>/` with a `SOURCE.json` (address, licence, date).
`data/raw/` is not committed to Git: the files are large and some licences do
not allow re-publishing them.

| Source | What Badeel takes from it | Licence | Table |
|---|---|---|---|
| DDInter 2.0 (https://ddinter2.scbdd.com/) | Drug-drug interactions with severity (Major, Moderate, Minor, Unknown) | Reported as CC BY-NC-SA 4.0: confirm on the DDInter site before publishing derived data | `drug_interactions` |
| openFDA drug labels (index: https://api.fda.gov/download.json) | U.S. package leaflets: indications, dosage, children, older adults, pregnancy, breastfeeding, contraindications, warnings | Public domain (CC0) | `ingredient_labels` |

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

## DrugCentral (diseases)

| Source | What Badeel takes from it | Licence | Table |
|---|---|---|---|
| DrugCentral (https://drugcentral.org/download) | For each active ingredient: diseases it treats (indication) and conditions listed as contraindications | CC BY-SA 4.0 | `ingredient_conditions` |

The dump is a PostgreSQL archive; Badeel reads the two tables it needs
(`omop_relationship`, `synonyms`) with `pg_restore`, so no PostgreSQL server
is needed, only the PostgreSQL 16 client tools.

Patients tick simple groups from `data/patient_conditions.csv` ("Liver
disease"), and each group covers several DrugCentral terms. The Arabic labels
in that file were written by the project and should be reviewed by a
pharmacist.

**Known limitation.** DrugCentral attaches contraindications to an
ingredient from many leaflets, including combination products. For example
it lists 85 conditions for ibuprofen, among them "Agoraphobia" and "Suicidal
thoughts", which most likely come from combinations with other medicines.
The drug page therefore says "contraindications or cautions" and explains
this. The precision of these warnings must be measured on a sample reviewed
by a pharmacist before the paper reports them.
