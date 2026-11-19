"""Performance test.   python checks/performance_check.py

Part 1 - RESPONSE TIME AND THROUGHPUT
  Starts a temporary copy of the site on a free port (real HTTP, real
  database file) and sends many requests from 20 users at the same time:
  home page, typo searches, drug pages and autocomplete.

Part 2 - SCALABILITY
  Fills a temporary database with 20,000 generated drugs (about the size of
  a national drug list) and measures how long the search and the
  alternatives take at that size.

Your real database is never touched.
"""
import csv
import io
import logging
import os
import random
import shutil
import statistics
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from werkzeug.serving import make_server                            # noqa: E402

from badeel import create_app, db                                   # noqa: E402
from badeel.services import importer, recommender, search           # noqa: E402

USERS = 20               # requests in flight at the same time
REQUESTS = 2000
SCALE = 20000
# Talk to 127.0.0.1 directly, even if the computer has a proxy configured.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def percentile(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def temp_app(name):
    tmp = tempfile.mkdtemp(prefix=f"badeel-{name}-")
    app = create_app({"TESTING": False, "INSTANCE": tmp,
                      "DATABASE": os.path.join(tmp, f"{name}.db")})
    return tmp, app


# ------------------------------------------------------------------ part 1
def load_test():
    tmp, app = temp_app("load")
    with app.app_context():
        with open(os.path.join(ROOT, "data", "sample_drugs.csv"), "rb") as f:
            importer.import_csv(f.read())
        search.train_model(log=lambda m: None, folds=2, per_kind=2)   # serve with the model
        drug_ids = [r["id"] for r in db.query("SELECT id FROM drugs")]

    logging.getLogger("werkzeug").setLevel(logging.ERROR)      # no line per request
    server = make_server("127.0.0.1", 0, app, threaded=True)
    base = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()

    typos = ["ogmentin", "panadl", "brufen", "cataflm", "glucofage", "concor", "lipitr",
             "zithromx", "بنادول", "اوجمنتين", "amoxcillin", "paracetmol"]
    rng = random.Random(7)
    plan = []
    for _ in range(REQUESTS):
        kind = rng.choices(["home", "search", "drug", "suggest"], [1, 3, 4, 2])[0]
        if kind == "home":
            plan.append((kind, "/"))
        elif kind == "search":
            plan.append((kind, "/search?q=" + urllib.parse.quote(rng.choice(typos))))
        elif kind == "drug":
            plan.append((kind, f"/drug/{rng.choice(drug_ids)}"))
        else:
            plan.append((kind, "/api/suggest?q=" + urllib.parse.quote(rng.choice(typos)[:4])))

    def hit(item):
        kind, path = item
        start = time.perf_counter()
        try:
            with OPENER.open(base + path, timeout=30) as r:
                r.read()
                ok = r.status == 200
        except Exception:
            ok = False
        return kind, (time.perf_counter() - start) * 1000, ok

    for item in plan[:40]:                      # warm-up: build the search index
        hit(item)
    single = [hit(item)[1] for item in plan[:300]]      # one user, one request at a time
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=USERS) as pool:
        results = list(pool.map(hit, plan))
    elapsed = time.perf_counter() - started
    server.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)

    times = [t for _, t, _ in results]
    errors = sum(1 for *_, ok in results if not ok)
    print("1) RESPONSE TIME AND THROUGHPUT  (real HTTP, temporary copy of the site)")
    print(f"   {REQUESTS} requests, {USERS} at the same time, {len(drug_ids)} drugs\n")
    print(f"   {'page':<12}{'requests':>9}{'average':>11}{'95% under':>12}")
    for kind in ("home", "search", "drug", "suggest"):
        t = [ms for k, ms, _ in results if k == kind]
        print(f"   {kind:<12}{len(t):>9}{statistics.mean(t):>9.1f} ms{percentile(t, 95):>9.1f} ms")
    print(f"\n   One user alone     : average {statistics.mean(single):.1f} ms per page")
    print(f"   Throughput         : {REQUESTS / elapsed:.0f} requests per second")
    print(f"   Average response   : {statistics.mean(times):.1f} ms (with {USERS} users at once)")
    print(f"   95% of requests in : {percentile(times, 95):.1f} ms or less")
    print(f"   Failed requests    : {errors}")
    print("   (Measured on the Flask development server. A production server such as")
    print("    waitress or gunicorn with several workers is faster.)")


# ------------------------------------------------------------------ part 2
def synthetic_csv(n, seed=11):
    rng = random.Random(seed)
    syll = ["ba", "ce", "di", "fo", "ga", "hi", "lo", "ma", "ne", "po", "ra", "si", "ta",
            "vo", "xa", "zo", "pra", "tri", "mel", "dor", "fen", "lin", "mox", "zol"]
    ingredients = sorted({"".join(rng.choice(syll) for _ in range(rng.randint(3, 4))) + suf
                          for suf in ["ine", "ol", "ide", "pril", "mab", "cin", "zole", "fen"]
                          for _ in range(60)})
    strengths = ["5 mg", "10 mg", "20 mg", "25 mg", "50 mg", "100 mg", "250 mg", "500 mg",
                 "1 g", "100 mg/5 ml", "2%"]
    forms = ["Tablets", "Capsules", "Syrup", "Suspension", "Injection", "Cream", "Eye drops"]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["trade_name", "active_ingredients", "form", "price", "availability"])
    for i in range(n):
        ings = rng.sample(ingredients, rng.choice([1, 1, 1, 2]))
        comp = " + ".join(f"{x} {rng.choice(strengths)}" for x in ings)
        brand = ("".join(rng.choice(syll) for _ in range(rng.randint(2, 3)))).capitalize()
        w.writerow([f"{brand} {i}", comp, rng.choice(forms), rng.randint(5, 400),
                    rng.choice(["available", "available", "shortage", ""])])
    return out.getvalue().encode("utf-8"), len(ingredients)


def small_model():
    """Train a quick model on the demo drugs; its features do not depend on
    drug names, so the same file can rank the 20,000 generated drugs."""
    tmp, app = temp_app("model")
    with app.app_context():
        with open(os.path.join(ROOT, "data", "sample_drugs.csv"), "rb") as f:
            importer.import_csv(f.read())
        search.train_model(log=lambda m: None, folds=2, per_kind=2)
    return tmp, os.path.join(tmp, "search_model.json")


def scale_test():
    model_tmp, model_file = small_model()
    tmp, app = temp_app("scale")
    shutil.copy(model_file, os.path.join(tmp, "search_model.json"))
    shutil.rmtree(model_tmp, ignore_errors=True)
    data, n_ing = synthetic_csv(SCALE)
    print(f"\n2) SCALABILITY  ({SCALE:,} generated drugs, {n_ing} generated ingredients)")
    with app.app_context():
        start = time.perf_counter()
        report = importer.import_csv(data)
        import_s = time.perf_counter() - start
        start = time.perf_counter()
        search.search("warm-up")                # builds the TF-IDF index
        index_s = time.perf_counter() - start
        rows = db.query("SELECT * FROM drugs ORDER BY RANDOM() LIMIT 300")
        rng = random.Random(3)
        s_times, a_times, b_times = [], [], []
        for r in rows:
            name = r["trade_name"].split()[0].lower()
            i = rng.randrange(1, len(name))
            typo = name[:i] + name[i + 1:]            # drop one letter
            t = time.perf_counter()
            search.search(typo, use_model=False)
            b_times.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter()
            search.search(typo)
            s_times.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter()
            recommender.get_alternatives(r)
            a_times.append((time.perf_counter() - t) * 1000)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"   CSV import            : {report['added']:,} drugs in {import_s:.1f} s "
          f"({report['added'] / import_s:,.0f} rows per second)")
    print(f"   Search index build    : {index_s * 1000:.0f} ms (once, after the data changes)")
    print(f"   Search, TF-IDF only   : average {statistics.mean(b_times):.1f} ms, "
          f"95% under {percentile(b_times, 95):.1f} ms")
    print(f"   Search with the model : average {statistics.mean(s_times):.1f} ms, "
          f"95% under {percentile(s_times, 95):.1f} ms")
    print(f"   Find all alternatives : average {statistics.mean(a_times):.2f} ms, "
          f"95% under {percentile(a_times, 95):.2f} ms")


if __name__ == "__main__":
    load_test()
    if "--quick" not in sys.argv:
        scale_test()
