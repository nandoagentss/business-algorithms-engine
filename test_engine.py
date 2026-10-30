"""Executable invariants and real SQLite race tests. Synthetic data only."""
import copy
import json
import os
import tempfile
import threading
import unittest
from engine import Engine, DomainError, demo_command, instant, distance_km

NOW = instant("2030-06-01T12:00:00-06:00")


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.e = Engine()
        self.e.seed_demo()
        self.cmd = demo_command()

    def tearDown(self):
        self.e.close()

    def quote(self, key="one", command=None, now=NOW):
        return self.e.create_request(command or self.cmd, key, now)

    def test_exact_cents_and_slots(self):
        q = self.quote()
        self.assertEqual(q["total_cents"], 24690)
        self.assertEqual(len(q["slot_ids"]), 2)
        self.assertEqual(q["journey"], "standard")

    def test_idempotent_request(self):
        self.assertEqual(self.quote(), self.quote(now=NOW+99999))
        self.assertEqual(self.e.db.execute("SELECT count(*) FROM requests").fetchone()[0], 1)

    def test_idempotency_conflict(self):
        self.quote()
        self.cmd["lines"][0]["quantity"] = 3
        with self.assertRaisesRegex(DomainError, "IDEMPOTENCY_CONFLICT"):
            self.quote()

    def test_actor_scoped_key(self):
        q = self.quote()
        self.cmd["owner"] = "other-client-demo"
        self.assertNotEqual(q["id"], self.quote()["id"])

    def test_invalid_quantities(self):
        for qty in (0, -1, True, 1.5, 101):
            with self.subTest(qty=qty):
                self.cmd["lines"][0]["quantity"] = qty
                with self.assertRaises(DomainError):
                    self.quote()

    def test_missing_rate_rolls_back(self):
        self.cmd["lines"].append(dict(profile="missing", quantity=1))
        with self.assertRaisesRegex(DomainError, "RATE_UNAVAILABLE"):
            self.quote()
        self.assertEqual(self.e.db.execute("SELECT count(*) FROM requests").fetchone()[0], 0)
        self.assertEqual(self.e.db.execute("SELECT count(*) FROM events").fetchone()[0], 0)

    def test_premium_catalog_rate(self):
        self.cmd["premium"] = True
        self.assertEqual(self.quote()["total_cents"], 34690)

    def test_short_notice(self):
        q = self.quote(now=instant(self.cmd["start"])-86400)
        self.assertIn("short_notice", q["reasons"])

    def test_schedule_boundary(self):
        self.cmd.update(start="2030-06-10T18:00:00-06:00", end="2030-06-10T22:00:00-06:00")
        self.assertEqual(self.quote()["journey"], "standard")
        self.cmd.update(start="2030-06-10T18:01:00-06:00", end="2030-06-10T22:01:00-06:00")
        self.assertIn("extended_schedule", self.quote(key="late")["reasons"])

    def test_cross_midnight(self):
        self.cmd.update(start="2030-06-10T22:00:00-06:00", end="2030-06-11T02:00:00-06:00")
        self.assertEqual(self.quote()["journey"], "pro")

    def test_unsupported_fractional_duration(self):
        self.cmd["end"] = "2030-06-10T16:30:00-06:00"
        with self.assertRaisesRegex(DomainError, "UNSUPPORTED_DURATION"):
            self.quote()

    def test_timezone_required(self):
        self.cmd["start"] = "2030-06-10T12:00:00"
        with self.assertRaises(DomainError):
            self.quote()

    def test_invalid_locations(self):
        for point in ([91, 0], [0, 181], [float("nan"), 0], [True, 0]):
            with self.subTest(point=point):
                with self.assertRaises(DomainError):
                    distance_km(point, [0, 0])

    def test_outside_demo_zone(self):
        self.cmd["location"] = [1, 0]
        self.assertIn("outside_demo_zone", self.quote()["reasons"])

    def test_mixed_currency(self):
        self.e.db.execute("UPDATE rates SET currency='USD' WHERE profile='chef-demo'")
        self.cmd["lines"].append(dict(profile="chef-demo", quantity=1))
        with self.assertRaisesRegex(DomainError, "MIXED_CURRENCY"):
            self.quote()

    def test_matching_filters_and_super_priority(self):
        sid = self.quote()["slot_ids"][0]
        self.assertEqual([p["id"] for p in self.e.candidates(sid, NOW)], ["pro-alpha", "pro-beta"])

    def test_rating_is_not_rounded(self):
        self.cmd["premium"] = True
        self.e.db.execute("UPDATE pros SET stars_total=99,reviews=20 WHERE id='pro-alpha'")
        sid = self.quote()["slot_ids"][0]
        self.assertEqual([p["id"] for p in self.e.candidates(sid, NOW)], ["pro-beta"])

    def test_stale_version(self):
        sid = self.quote()["slot_ids"][0]
        with self.assertRaisesRegex(DomainError, "STALE_VERSION"):
            self.e.accept_demo(sid, "pro-alpha", 2, NOW)

    def test_expired_quote(self):
        sid = self.quote()["slot_ids"][0]
        with self.assertRaisesRegex(DomainError, "QUOTE_EXPIRED"):
            self.e.accept_demo(sid, "pro-alpha", 1, NOW+900)

    def test_catalog_revalidated(self):
        sid = self.quote()["slot_ids"][0]
        self.e.db.execute("UPDATE rates SET cents=cents+1")
        with self.assertRaisesRegex(DomainError, "REQUOTE_REQUIRED"):
            self.e.accept_demo(sid, "pro-alpha", 1, NOW)

    def test_duplicate_acceptance_deduplicates_events(self):
        sid = self.quote()["slot_ids"][0]
        first = self.e.accept_demo(sid, "pro-alpha", 1, NOW)
        self.assertEqual(first, self.e.accept_demo(sid, "pro-alpha", 1, NOW+9999))
        self.assertEqual(self.e.db.execute("SELECT count(*) FROM reservations").fetchone()[0], 1)
        self.assertEqual(self.e.db.execute("SELECT count(*) FROM events").fetchone()[0], 2)

    def test_taken_slot(self):
        sid = self.quote()["slot_ids"][0]
        self.e.accept_demo(sid, "pro-alpha", 1, NOW)
        with self.assertRaisesRegex(DomainError, "SLOT_TAKEN"):
            self.e.accept_demo(sid, "pro-beta", 1, NOW)

    def test_pro_cannot_cover_two_simultaneous_slots(self):
        a, b = self.quote()["slot_ids"]
        self.e.accept_demo(a, "pro-alpha", 1, NOW)
        with self.assertRaisesRegex(DomainError, "PRO_INELIGIBLE"):
            self.e.accept_demo(b, "pro-alpha", 1, NOW)

    def test_verification_revalidated_at_acceptance(self):
        sid = self.quote()["slot_ids"][0]
        self.e.db.execute("UPDATE pros SET verified=0 WHERE id='pro-alpha'")
        with self.assertRaisesRegex(DomainError, "PRO_INELIGIBLE"):
            self.e.accept_demo(sid, "pro-alpha", 1, NOW)

    def test_complete_demo(self):
        for sid in self.quote()["slot_ids"]:
            winner = self.e.candidates(sid, NOW)[0]["id"]
            self.e.accept_demo(sid, winner, 1, NOW)
            self.assertEqual(self.e.candidates(sid, NOW), [])
        self.assertEqual(self.e.db.execute("SELECT count(*) FROM reservations").fetchone()[0], 2)

    def test_snapshot_survives_catalog_change(self):
        q = self.quote()
        self.e.db.execute("UPDATE rates SET cents=cents+1000,version=version+1")
        self.assertEqual(q, self.quote())

    def test_real_sqlite_races_and_persistence(self):
        # Separate connections, real transactions, shared temporary database.
        for same_slot in (True, False):
            with self.subTest(same_slot=same_slot), tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, "demo.sqlite")
                setup = Engine(path)
                setup.seed_demo()
                q1 = setup.create_request(self.cmd, "a", NOW)
                q2 = setup.create_request(self.cmd, "b", NOW)
                setup.close()
                barrier, results = threading.Barrier(2), []
                def worker(sid, pid):
                    db = Engine(path)
                    try:
                        barrier.wait(timeout=10)
                        db.accept_demo(sid, pid, 1, NOW)
                        results.append("ok")
                    except DomainError:
                        results.append("conflict")
                    except Exception as exc:
                        results.append(type(exc).__name__)
                    finally:
                        db.close()
                a = threading.Thread(target=worker, args=(q1["slot_ids"][0], "pro-alpha"))
                b = threading.Thread(target=worker, args=(q1["slot_ids"][0] if same_slot else q2["slot_ids"][0],
                                                         "pro-beta" if same_slot else "pro-alpha"))
                a.start(); b.start(); a.join(timeout=20); b.join(timeout=20)
                self.assertFalse(a.is_alive() or b.is_alive())
                self.assertCountEqual(results, ["ok", "conflict"])
                reopened = Engine(path)
                self.assertEqual(reopened.db.execute("SELECT count(*) FROM reservations").fetchone()[0], 1)
                self.assertEqual(reopened.create_request(self.cmd, "a", NOW), q1)
                reopened.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
