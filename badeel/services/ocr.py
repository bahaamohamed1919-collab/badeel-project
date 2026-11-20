"""Search by photo: read the text on a medicine box and find the product.

Uses Tesseract (free, runs on the server, Arabic + English). The photo is
written to a temporary file only while Tesseract reads it, then deleted:
nothing is stored. When Tesseract is not installed, the camera button is
hidden and the route answers with a short message.

Install on the server:  apt install tesseract-ocr tesseract-ocr-ara tesseract-ocr-eng
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict, deque

MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 25
LANGS = "ara+eng"

# Only real photos: checked by their first bytes, not by the file name.
_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")


def _is_image(data):
    return data.startswith(_SIGNATURES) or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


_available = None


def available():
    """True when Tesseract with Arabic and English is installed."""
    global _available
    if _available is None:
        exe = shutil.which("tesseract")
        if not exe:
            _available = False
        else:
            try:
                out = subprocess.run([exe, "--list-langs"], capture_output=True, timeout=10, text=True)
                langs = set((out.stdout + out.stderr).split())
                _available = {"ara", "eng"} <= langs
            except (OSError, subprocess.SubprocessError):
                _available = False
    return _available


class PhotoError(ValueError):
    pass


def read_text(data):
    """Text found in the photo (may be empty)."""
    if not data:
        raise PhotoError("empty")
    if len(data) > MAX_BYTES:
        raise PhotoError("too_large")
    if not _is_image(data):
        raise PhotoError("not_image")
    fd, path = tempfile.mkstemp(suffix=".img")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        texts = []
        # psm 11: scattered text, as on a box; psm 6: one block, as on a strip or label
        for psm in ("11", "6"):
            out = subprocess.run([shutil.which("tesseract"), path, "stdout", "-l", LANGS, "--psm", psm],
                                 capture_output=True, timeout=TIMEOUT_SECONDS, text=True)
            texts.append(out.stdout)
        return "\n".join(texts)
    except subprocess.TimeoutExpired as e:
        raise PhotoError("timeout") from e
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def candidate_queries(text, limit=25):
    """Lines of the photo that could be a medicine name, cleaned, longest words kept."""
    seen, out = set(), []
    lines = [re.sub(r"[^\w؀-ۿ.+/ -]", " ", ln) for ln in text.splitlines()]
    lines = [re.sub(r"\s+", " ", ln).strip(" .-/+") for ln in lines]
    for ln in lines:
        letters = re.findall(r"[A-Za-z؀-ۿ]", ln)
        if len(letters) < 3 or len(ln) > 60:
            continue
        key = ln.lower()
        if key not in seen:
            seen.add(key)
            out.append(ln)
    return out[:limit]


_STRENGTH = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:mg|mcg|g|gm|ml|iu|%)\b", re.I)


def best_match(text, search_fn):
    """Pick the line that matches a product best.

    search_fn(query, limit) returns [(drug_id, score), ...] best first.
    A brand printed without its strength ("Panadol") is also tried with each
    strength printed elsewhere on the box ("Panadol 500 mg"), and a line that
    carries a strength gets a small advantage, so the exact product comes
    before a product that only shares the name or the ingredient.
    Returns (query, [other lines]) or (None, lines) when nothing matched.
    """
    lines = candidate_queries(text)
    strengths = list(dict.fromkeys(m.group(0) for m in _STRENGTH.finditer(text)))[:2]
    queries = list(lines)
    for ln in lines:
        if not _STRENGTH.search(ln):
            queries += [f"{ln} {st}" for st in strengths]
    scored = []
    for q in dict.fromkeys(queries):
        hits = search_fn(q, 1)
        if hits:
            scored.append((hits[0][1] + (0.08 if _STRENGTH.search(q) else 0), q))
    if not scored:
        return None, lines
    scored.sort(key=lambda x: -x[0])
    best = scored[0][1]
    others = [q for _, q in scored[1:] if q in lines and q != best][:5]
    return best, others


# ---- simple limit per address: reading photos uses a lot of CPU
_recent = defaultdict(deque)
PER_WINDOW, WINDOW_SECONDS = 12, 600


def allowed(address):
    now = time.monotonic()
    q = _recent[address]
    while q and now - q[0] > WINDOW_SECONDS:
        q.popleft()
    if len(q) >= PER_WINDOW:
        return False
    q.append(now)
    return True
