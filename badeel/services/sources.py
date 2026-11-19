"""Downloading outside data sources into data/raw/ (never committed to Git).

Every file is saved unchanged, next to a SOURCE.json that records where it
came from, its licence and the date, so each cleaning step can be repeated
and the paper can cite exactly what was used.

The addresses are settings, not constants in the code, because sources move:
    BADEEL_DDINTER_URL   folder that holds ddinter_downloads_code_<X>.csv
    BADEEL_OPENFDA_URL   openFDA download index (download.json)
"""
import json
import os
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(ROOT, "data", "raw")

DDINTER_URL = "http://ddinter.scbdd.com/static/media/download/"
# DDInter publishes one file per ATC first-level code.
DDINTER_CODES = ["A", "B", "D", "H", "L", "M", "P", "R", "S", "V"]
DDINTER_LICENCE = ("DDInter (Xiong et al., Nucleic Acids Research). Reported as CC BY-NC-SA 4.0: "
                   "check the licence on the DDInter website before publishing derived data.")

OPENFDA_URL = "https://download.open.fda.gov/download.json"
OPENFDA_LICENCE = "openFDA drug labels: public domain (CC0), U.S. Food and Drug Administration."

USER_AGENT = "Badeel-academic-project/1.0"


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def download(url, dest, log=print):
    """Save url to dest. Skips the download when dest already exists."""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        log(f"  already downloaded: {os.path.relpath(dest, ROOT)}")
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    log(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest + ".part"
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    os.replace(tmp, dest)
    return dest


def _write_source(folder, name, urls, licence):
    with open(os.path.join(folder, "SOURCE.json"), "w", encoding="utf-8") as f:
        json.dump({"source": name, "downloaded_on": _today(), "urls": urls,
                   "licence": licence}, f, indent=2)


def fetch_ddinter(base_url=None, raw_dir=RAW_DIR, log=print):
    """Download all DDInter files. Returns the list of local paths."""
    base = (base_url or os.environ.get("BADEEL_DDINTER_URL") or DDINTER_URL).rstrip("/") + "/"
    folder = os.path.join(raw_dir, "ddinter", _today())
    urls = [f"{base}ddinter_downloads_code_{c}.csv" for c in DDINTER_CODES]
    paths = [download(u, os.path.join(folder, u.rsplit("/", 1)[1]), log) for u in urls]
    _write_source(folder, "DDInter", urls, DDINTER_LICENCE)
    return paths


def fetch_openfda_labels(index_url=None, raw_dir=RAW_DIR, log=print):
    """Download every partition of the openFDA drug label dataset (zipped JSON)."""
    index_url = index_url or os.environ.get("BADEEL_OPENFDA_URL") or OPENFDA_URL
    folder = os.path.join(raw_dir, "openfda_labels", _today())
    index_path = download(index_url, os.path.join(folder, "download.json"), log)
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)
    parts = index["results"]["drug"]["label"]["partitions"]
    urls = [p["file"] for p in parts]
    log(f"  openFDA drug labels: {len(urls)} files")
    paths = [download(u, os.path.join(folder, u.rsplit("/", 1)[1]), log) for u in urls]
    _write_source(folder, "openFDA drug labels", [index_url] + urls, OPENFDA_LICENCE)
    return paths
