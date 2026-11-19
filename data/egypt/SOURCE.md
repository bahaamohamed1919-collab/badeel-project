# Egyptian drug list (candidate real dataset)

File: `egyptian-drugs.csv` (25,070 rows, 7 columns)

Downloaded on 14 November 2026 from the public GitHub repository
<https://github.com/karem505/egyptian-drug-database>, which publishes it under
**CC0-1.0** (public domain dedication). Columns:

| column | meaning |
|---|---|
| commercial_name_en | trade name as sold, with strength, form and pack size inside it |
| commercial_name_ar | Arabic search alias (a transliteration, not always the official Arabic name) |
| scientific_name | active ingredients joined by `+`, usually without strengths |
| manufacturer | company |
| drug_class | therapeutic group |
| route | ORAL.SOLID, TOPICAL, INJECTION, ... |
| price_egp | retail price in Egyptian pounds |

**Important:** the repository does not say where the data originally came
from, and prices change often. Before the project relies on it (and before
the site goes online) the data team must:

1. compare a sample of rows with the Egyptian Drug Authority (EDA) records;
2. record the date of the prices;
3. confirm with the supervisor that the source is acceptable.

Import it: Admin panel -> Import data -> choose this file -> "Delete them all
first" -> Import file. Then press "Train search model" on the admin overview.
Or from the terminal:

    python manage.py import-csv data/egypt/egyptian-drugs.csv --replace
    python manage.py train-model
