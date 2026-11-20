"""Tests for search by photo (text read with Tesseract) and the voice search button."""
import io
import re
from unittest import mock

from badeel.services import ocr

try:
    from tests.test_app import Base
except ImportError:
    from test_app import Base

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
BOX_TEXT = "Panadol\nParacetamol 500 mg\n24 Tablets\nبانادول\nStore below 25°C. Keep out of reach of children."


class PhotoServiceTests(Base):
    def test_only_real_images_are_read(self):
        with self.assertRaises(ocr.PhotoError):
            ocr.read_text(b"")
        with self.assertRaises(ocr.PhotoError):
            ocr.read_text(b"<script>alert(1)</script>")               # not an image
        with self.assertRaises(ocr.PhotoError):
            ocr.read_text(PNG + b"\x00" * ocr.MAX_BYTES)               # too large

    def test_candidate_lines(self):
        lines = ocr.candidate_queries(BOX_TEXT)
        self.assertIn("Panadol", lines)
        self.assertIn("بانادول", lines)
        self.assertNotIn("Store below 25°C. Keep out of reach of children.", lines)   # too long

    def test_name_is_combined_with_the_strength_on_the_box(self):
        def fake_search(q, limit):
            return [(1, 0.9)] if "panadol" in q.lower() or "بانادول" in q else []
        best, others = ocr.best_match(BOX_TEXT, fake_search)
        self.assertIn("500 mg", best)
        self.assertTrue(best.lower().startswith("panadol") or best.startswith("بانادول"))

    def test_nothing_found(self):
        self.assertEqual(ocr.best_match("xx\n12", lambda q, n: [])[0], None)

    def test_rate_limit(self):
        address = "203.0.113.50"
        results = [ocr.allowed(address) for _ in range(ocr.PER_WINDOW + 1)]
        self.assertTrue(all(results[:-1]))
        self.assertFalse(results[-1])


class PhotoRouteTests(Base):
    def _token(self):
        html = self.client.get("/").get_data(as_text=True)
        return re.search(r'id="photo-form".*?name="csrf_token" value="([^"]+)"', html, re.S).group(1)

    def setUp(self):
        super().setUp()
        ocr._recent.clear()

    def test_photo_finds_the_medicine(self):
        with mock.patch.object(ocr, "available", return_value=True), \
             mock.patch.object(ocr, "read_text", return_value=BOX_TEXT):
            r = self.client.post("/photo-search", content_type="multipart/form-data",
                                 data={"csrf_token": self._token(), "photo": (io.BytesIO(PNG), "box.png")})
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("photo-read", html)
        self.assertIn("Panadol", html)

    def test_needs_csrf_token(self):
        with mock.patch.object(ocr, "available", return_value=True):
            r = self.client.post("/photo-search", content_type="multipart/form-data",
                                 data={"photo": (io.BytesIO(PNG), "box.png")})
        self.assertEqual(r.status_code, 400)

    def test_unreadable_photo_explains_what_to_do(self):
        with mock.patch.object(ocr, "available", return_value=True), \
             mock.patch.object(ocr, "read_text", return_value="..."):
            r = self.client.post("/photo-search", content_type="multipart/form-data", follow_redirects=True,
                                 data={"csrf_token": self._token(), "photo": (io.BytesIO(PNG), "box.png")})
        self.assertIn("صوّر العلبة من قريب", r.get_data(as_text=True))

    def test_camera_hidden_when_tesseract_missing(self):
        with mock.patch.object(ocr, "available", return_value=False):
            html = self.client.get("/").get_data(as_text=True)
            self.assertNotIn('id="photo-form"', html)
            r = self.client.post("/photo-search", data={"csrf_token": "x"})
            self.assertIn(r.status_code, (302, 400))


class VoiceTests(Base):
    def test_voice_buttons_start_hidden_until_supported(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertRegex(html, r'data-voice-lang hidden')      # shown by app.js only if the browser can listen
        self.assertRegex(html, r'data-voice hidden')
        self.assertIn('class="examples"', html)
