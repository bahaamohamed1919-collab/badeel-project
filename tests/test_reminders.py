"""Tests for medicine reminders, refill alerts, notification sign-up and the PWA files."""
import json
import re
from datetime import datetime, timedelta, timezone

from badeel import db
from badeel.services import reminders

try:
    from tests.test_app import Base, PASSWORD
except ImportError:
    from test_app import Base, PASSWORD

T0 = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)   # 08:00 in Cairo


def row(**kw):
    r = {"first_dose_at": reminders.fmt(T0), "every_hours": 8, "units_per_dose": 1.0,
         "units_in_box": 20, "box_started_at": reminders.fmt(T0)}
    r.update(kw)
    return r


class MathsTests(Base):
    def test_next_and_last_dose(self):
        r = row()
        self.assertIsNone(reminders.last_dose(r, T0 - timedelta(minutes=1)))
        self.assertEqual(reminders.next_dose(r, T0 - timedelta(hours=1)), T0)
        self.assertEqual(reminders.last_dose(r, T0 + timedelta(hours=9)), T0 + timedelta(hours=8))
        self.assertEqual(reminders.next_dose(r, T0 + timedelta(hours=9)), T0 + timedelta(hours=16))

    def test_box_counts_down_and_warns_two_days_before(self):
        r = row()                                    # 20 tablets, 3 a day: lasts about 6.7 days
        start = reminders.box_status(r, T0)
        self.assertEqual(start["units_left"], 19)    # the first dose is taken at the start
        self.assertFalse(start["refill_due"])
        later = reminders.box_status(r, T0 + timedelta(days=5))
        self.assertTrue(later["refill_due"])
        self.assertLessEqual(later["days_left"], 2)
        self.assertEqual(reminders.box_status(r, T0 + timedelta(days=30))["units_left"], 0)
        self.assertIsNone(reminders.box_status(row(units_in_box=None), T0))

    def test_new_box_starts_the_count_again(self):
        r = row(box_started_at=reminders.fmt(T0 + timedelta(days=5)))
        self.assertEqual(reminders.box_status(r, T0 + timedelta(days=5))["units_left"], 19)


class RouteTests(Base):
    def _create(self, drug, **extra):
        data = {"every_hours": "8", "first_time": "08:00", "units_per_dose": "1", "units_in_box": "30",
                "consent": "yes", "csrf_token": self.token(f"/reminders/new/{drug['id']}")}
        data.update(extra)
        return self.client.post(f"/reminders/new/{drug['id']}", data=data)

    def test_create_saves_medicine_and_shows_on_dashboard(self):
        brufen = self.drug("Brufen 400")
        self.login("pat@test.local")
        r = self._create(brufen)
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            rem = db.one("SELECT * FROM reminders WHERE drug_id = ?", (brufen["id"],))
            self.assertEqual((rem["every_hours"], rem["units_in_box"]), (8, 30))
            self.assertTrue(db.one("SELECT 1 FROM favorites WHERE drug_id = ?", (brufen["id"],)))
            log = db.one("SELECT detail FROM audit_log WHERE action = 'reminder_saved' ORDER BY id DESC")
            self.assertNotIn("Brufen", log["detail"] or "")
        html = self.client.get("/me").get_data(as_text=True)
        self.assertIn('id="reminders"', html)
        self.assertIn("data-next-dose", html)
        self.assertIn("08:00", self.client.get(f"/reminders/new/{brufen['id']}").get_data(as_text=True))

    def test_invalid_input_is_refused(self):
        self.login("pat@test.local")
        r = self._create(self.drug("Zyrtec 10"), every_hours="5", units_per_dose="50")
        self.assertEqual(r.status_code, 400)

    def test_cannot_touch_another_patients_reminder(self):
        self.login("pat@test.local")
        self._create(self.drug("Glucophage 500"))
        with self.app.app_context():
            rid = db.one("SELECT id FROM reminders ORDER BY id DESC")["id"]
        other = self.app.test_client()
        html = other.get("/login").get_data(as_text=True)
        tok = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        other.post("/login", data={"email": "pharm@test.local", "password": PASSWORD, "csrf_token": tok})
        tok = re.search(r'name="csrf-token" content="([^"]+)"', other.get("/").get_data(as_text=True)).group(1)
        self.assertEqual(other.post(f"/reminders/{rid}/delete", data={"csrf_token": tok}).status_code, 404)

    def test_needs_login(self):
        self.assertEqual(self.client.get(f"/reminders/new/{self.drug('Brufen 400')['id']}").status_code, 302)


class PushTests(Base):
    SUB = {"endpoint": "https://push.example.org/abc", "keys": {"p256dh": "BKey", "auth": "AuthKey"}}

    def _token(self):
        return re.search(r'name="csrf-token" content="([^"]+)"', self.client.get("/").get_data(as_text=True)).group(1)

    def test_subscribe_needs_csrf_and_valid_data(self):
        self.login("pat@test.local")
        self.assertEqual(self.client.post("/push/subscribe", json=self.SUB).status_code, 400)
        h = {"X-CSRF-Token": self._token()}
        self.assertEqual(self.client.post("/push/subscribe", json={"endpoint": "http://x"}, headers=h).status_code, 400)
        self.assertEqual(self.client.post("/push/subscribe", json=self.SUB, headers=h).status_code, 200)
        key = self.client.get("/push/key").get_json()
        self.assertTrue(key["available"])
        self.assertGreater(len(key["key"]), 80)                 # uncompressed P-256 public key

    def test_send_due_notifications_once(self):
        self.login("pat@test.local")
        self.client.post("/push/subscribe", json=self.SUB, headers={"X-CSRF-Token": self._token()})
        with self.app.app_context():
            uid = db.one("SELECT id FROM users WHERE email = 'pat@test.local'")["id"]
            drug = db.one("SELECT id FROM drugs WHERE trade_name = 'Augmentin 1 g'")["id"]   # in shortage
            now = reminders.utcnow()
            db.execute("INSERT INTO reminders (user_id, drug_id, every_hours, first_dose_at, units_per_dose, "
                       "units_in_box, box_started_at, created_at) VALUES (?, ?, 12, ?, 1, 3, ?, ?)",
                       (uid, drug, reminders.fmt(now - timedelta(minutes=5)), reminders.fmt(now - timedelta(minutes=5)), db.now()))
            db.commit()
            sent = []
            reminders.send_due(now, sender=lambda sub, p: sent.append(p) or True, log=lambda m: None)
            kinds = sorted(p["tag"].split("-")[0] for p in sent)
            self.assertEqual(kinds, ["dose", "refill"])
            refill = next(p for p in sent if p["tag"].startswith("refill"))
            self.assertIn("ناقص", refill["body"])                # shortage: points to the alternatives
            sent.clear()
            reminders.send_due(now + timedelta(minutes=1), sender=lambda sub, p: sent.append(p) or True, log=lambda m: None)
            self.assertEqual(sent, [])                          # not sent twice
            # a browser that no longer accepts notifications is forgotten
            db.execute("UPDATE reminders SET last_dose_notified = NULL, refill_notified_at = NULL")
            reminders.send_due(now, sender=lambda sub, p: False, log=lambda m: None)
            self.assertIsNone(db.one("SELECT 1 FROM push_subscriptions"))


class PwaTests(Base):
    def test_manifest_and_service_worker(self):
        r = self.client.get("/manifest.webmanifest")
        self.assertEqual(r.mimetype, "application/manifest+json")
        data = json.loads(r.get_data(as_text=True))
        self.assertEqual(data["display"], "standalone")
        self.assertEqual({i["sizes"] for i in data["icons"]}, {"192x192", "512x512"})
        sw = self.client.get("/sw.js")
        self.assertEqual(sw.mimetype, "application/javascript")
        self.assertIn("showNotification", sw.get_data(as_text=True))
        self.assertIn('rel="manifest"', self.client.get("/").get_data(as_text=True))
