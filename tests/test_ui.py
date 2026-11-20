"""Tests for the role dashboards and the page frame (theme, menus)."""
import re

try:
    from tests.test_app import Base, PASSWORD
except ImportError:
    from test_app import Base, PASSWORD


class UiTests(Base):
    def test_each_role_lands_on_its_dashboard(self):
        for email, path in [("pat@test.local", "/me"), ("pharm@test.local", "/pharmacist"),
                            ("admin@test.local", "/admin/")]:
            client = self.app.test_client()
            html = client.get("/login").get_data(as_text=True)
            token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
            r = client.post("/login", data={"email": email, "password": PASSWORD, "csrf_token": token})
            self.assertEqual(r.status_code, 302, email)
            self.assertTrue(r.headers["Location"].endswith(path), (email, r.headers["Location"]))
            self.assertEqual(client.get(path).status_code, 200, path)

    def test_patient_dashboard_needs_login(self):
        r = self.client.get("/me")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_patient_dashboard_shows_saved_medicine(self):
        brufen = self.drug("Brufen 400")
        self.login("pat@test.local")
        self.client.post(f"/favorite/{brufen['id']}", data={"csrf_token": self.token(f"/drug/{brufen['id']}")})
        html = self.client.get("/me").get_data(as_text=True)
        self.assertIn("Brufen 400", html)
        self.assertIn('id="warnings"', html)

    def test_frame_has_theme_toggle_and_role_menu(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("js/theme.js", html)
        self.assertIn("theme-toggle", html)
        self.assertNotIn('class="avatar"', html)            # visitors have no account menu
        self.login("admin@test.local")
        html = self.client.get("/admin/").get_data(as_text=True)
        self.assertIn('class="avatar"', html)
        self.assertIn("/admin/import", html)                # admin actions in the top bar

    def test_no_inline_script_or_style(self):
        # The Content Security Policy blocks them, so none may appear.
        self.login("admin@test.local")
        for path in ["/", "/admin/", "/pharmacist", "/account", f"/drug/{self.drug('Brufen 400')['id']}"]:
            html = self.client.get(path).get_data(as_text=True)
            self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)[^>]*>", path)
            self.assertNotIn(' style="', html, path)
            self.assertNotIn("<style", html, path)
