"""Business Algorithms Engine by Nando. Synthetic reference implementation.
Python 3.11+, standard library only. No production services or real payments.
"""
import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

POLICY = "demo-v1"
MAX_CENTS = 9_000_000_000_000


class DomainError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise DomainError(code)


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def distance_km(a, b):
    for point in (a, b):
        require(isinstance(point, (list, tuple)) and len(point) == 2,
                "INVALID_LOCATION")
        require(all(type(x) in (int, float) and math.isfinite(x) for x in point),
                "INVALID_LOCATION")
        require(abs(point[0]) <= 90 and abs(point[1]) <= 180, "INVALID_LOCATION")
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def instant(text):
    try:
        dt = datetime.fromisoformat(text)
        require(dt.utcoffset() is not None, "TIMEZONE_REQUIRED")
        return int(dt.timestamp())
    except (TypeError, ValueError, OverflowError) as exc:
        raise DomainError("INVALID_AWARE_DATETIME") from exc


def normalize(command, now):
    require(integer(now), "INVALID_CLOCK")
    require(isinstance(command.get("owner"), str) and bool(command["owner"].strip()), "OWNER_REQUIRED")
    start, end = instant(command["start"]), instant(command["end"])
    require(start > now and end > start, "INVALID_INTERVAL")
    hours, remainder = divmod(end-start, 3600)
    require(remainder == 0 and 4 <= hours <= 14, "UNSUPPORTED_DURATION")
    distance_km(command["location"], (0, 0))
    require(type(command.get("premium", False)) is bool, "INVALID_PREMIUM")
    require(isinstance(command.get("lines"), list) and 0 < len(command["lines"]) <= 50,
            "INVALID_LINES")
    for line in command["lines"]:
        require(isinstance(line.get("profile"), str) and bool(line["profile"]), "INVALID_PROFILE")
        require(integer(line.get("quantity"), 1) and line["quantity"] <= 100, "INVALID_QUANTITY")
    # Synthetic demonstration policy. Not a replica of production pricing.
    zone = ZoneInfo("America/Mexico_City")
    local_start = datetime.fromtimestamp(start, zone)
    local_end = datetime.fromtimestamp(end, zone)
    reasons = []
    if command.get("premium", False):
        reasons.append("requested_premium")
    if start-now <= 86400:
        reasons.append("short_notice")
    if local_start.date() != local_end.date() or local_start.hour < 9 or (
            local_end.hour > 22 or (local_end.hour == 22 and local_end.minute > 0)):
        reasons.append("extended_schedule")
    if distance_km(command["location"], (0, 0)) > 15:
        reasons.append("outside_demo_zone")
    return start, end, hours, "pro" if reasons else "standard", reasons


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS rates (
  profile TEXT, hours INTEGER, journey TEXT, cents INTEGER CHECK(cents>0),
  currency TEXT NOT NULL, version INTEGER NOT NULL, active INTEGER NOT NULL,
  PRIMARY KEY(profile,hours,journey));
CREATE TABLE IF NOT EXISTS pros (
  id TEXT PRIMARY KEY, profiles TEXT NOT NULL, lat REAL, lng REAL,
  active INTEGER NOT NULL, verified INTEGER NOT NULL, super_pro INTEGER NOT NULL,
  stars_total INTEGER NOT NULL, reviews INTEGER NOT NULL, agenda_known INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS requests (
  id TEXT PRIMARY KEY, owner TEXT NOT NULL, idem_key TEXT NOT NULL,
  command_hash TEXT NOT NULL, snapshot TEXT NOT NULL,
  UNIQUE(owner,idem_key));
CREATE TABLE IF NOT EXISTS slots (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES requests(id),
  profile TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
  lat REAL NOT NULL, lng REAL NOT NULL, journey TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1, pro_id TEXT REFERENCES pros(id));
CREATE TABLE IF NOT EXISTS reservations (
  slot_id TEXT PRIMARY KEY REFERENCES slots(id), pro_id TEXT NOT NULL REFERENCES pros(id),
  start INTEGER NOT NULL, end INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS agenda_idx ON reservations(pro_id,start,end);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL);
"""


class Engine:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def seed_demo(self):
        # All rates and Pros below are invented fixtures, not business data.
        with self.transaction():
            for profile, base in (("staff-demo", 12345), ("chef-demo", 23456)):
                for hours in range(4, 15):
                    for journey, extra in (("standard", 0), ("pro", 5000)):
                        self.db.execute("INSERT OR IGNORE INTO rates VALUES (?,?,?,?,?,?,?)",
                                        (profile, hours, journey, base+extra+(hours-4)*1000, "MXN", 1, 1))
            fixtures = [
                ("pro-alpha", '["staff-demo"]', 0.01, 0, 1, 1, 1, 50, 10, 1),
                ("pro-beta", '["staff-demo","chef-demo"]', 0.02, 0, 1, 1, 0, 50, 10, 1),
                ("pro-far", '["staff-demo"]', 2, 0, 1, 1, 1, 50, 10, 1),
                ("pro-pending", '["staff-demo"]', 0, 0, 1, 0, 1, 50, 10, 1),
                ("pro-unknown", '["staff-demo"]', 0, 0, 1, 1, 0, 0, 0, 0),
            ]
            self.db.executemany("INSERT OR IGNORE INTO pros VALUES (?,?,?,?,?,?,?,?,?,?)", fixtures)

    def create_request(self, command, key, now):
        require(isinstance(key, str) and 0 < len(key) <= 200, "IDEMPOTENCY_KEY_REQUIRED")
        require(isinstance(command, dict), "INVALID_COMMAND")
        digest = hashlib.sha256(canonical(command).encode()).hexdigest()
        with self.transaction():
            old = self.db.execute("SELECT * FROM requests WHERE owner=? AND idem_key=?",
                                  (command.get("owner"), key)).fetchone()
            if old:
                require(old["command_hash"] == digest, "IDEMPOTENCY_CONFLICT")
                return json.loads(old["snapshot"])
            start, end, hours, journey, reasons = normalize(command, now)
            items, currencies, total = [], set(), 0
            for line in command["lines"]:
                rate = self.db.execute("SELECT * FROM rates WHERE profile=? AND hours=? AND journey=? AND active=1",
                                       (line["profile"], hours, journey)).fetchone()
                require(rate is not None, "RATE_UNAVAILABLE")
                subtotal = rate["cents"] * line["quantity"]
                total += subtotal
                require(0 < total <= MAX_CENTS, "MONEY_OVERFLOW")
                currencies.add(rate["currency"])
                items.append(dict(profile=line["profile"], quantity=line["quantity"],
                                  unit_cents=rate["cents"], subtotal_cents=subtotal,
                                  rate_version=rate["version"]))
            require(len(currencies) == 1, "MIXED_CURRENCY")
            rid = hashlib.sha256(canonical([command["owner"], key]).encode()).hexdigest()[:24]
            snapshot = dict(id=rid, policy=POLICY, journey=journey, reasons=reasons,
                            currency=currencies.pop(), total_cents=total, items=items,
                            expires_at=now+900, state="quoted", slot_ids=[])
            self.db.execute("INSERT INTO requests VALUES (?,?,?,?,?)",
                            (rid, command["owner"], key, digest, canonical(snapshot)))
            for item in items:
                for _ in range(item["quantity"]):
                    sid = rid + ":" + str(len(snapshot["slot_ids"]))
                    self.db.execute("INSERT INTO slots (id,request_id,profile,start,end,lat,lng,journey) VALUES (?,?,?,?,?,?,?,?)",
                                    (sid, rid, item["profile"], start, end, *command["location"], journey))
                    snapshot["slot_ids"].append(sid)
            self.db.execute("UPDATE requests SET snapshot=? WHERE id=?", (canonical(snapshot), rid))
            self.db.execute("INSERT INTO events VALUES (?,?,?)", (rid+":created", "request.created", canonical(snapshot)))
            return snapshot

    def candidates(self, slot_id, now):
        require(integer(now), "INVALID_CLOCK")
        slot = self.db.execute("SELECT * FROM slots WHERE id=?", (slot_id,)).fetchone()
        require(slot is not None, "SLOT_NOT_FOUND")
        if slot["pro_id"] or slot["start"] <= now:
            return []
        found = []
        for pro in self.db.execute("SELECT * FROM pros WHERE active=1 AND verified=1 AND agenda_known=1"):
            if slot["profile"] not in json.loads(pro["profiles"]) or pro["lat"] is None or pro["lng"] is None:
                continue
            if slot["journey"] == "pro" and not (pro["reviews"] > 0 and pro["stars_total"] == 5*pro["reviews"]):
                continue
            km = distance_km((slot["lat"], slot["lng"]), (pro["lat"], pro["lng"]))
            if km > 20:
                continue
            busy = self.db.execute("SELECT 1 FROM reservations WHERE pro_id=? AND start<? AND end>? LIMIT 1",
                                   (pro["id"], slot["end"], slot["start"])).fetchone()
            if not busy:
                found.append(dict(id=pro["id"], super_pro=bool(pro["super_pro"]), distance_km=km))
        return sorted(found, key=lambda p: (not p["super_pro"], p["distance_km"], p["id"]))

    def accept_demo(self, slot_id, pro_id, expected_version, now):
        """Trusted demo command. Does not authenticate a human or verify payment."""
        require(integer(expected_version, 1) and integer(now), "INVALID_VERSION_OR_CLOCK")
        with self.transaction():
            slot = self.db.execute("SELECT * FROM slots WHERE id=?", (slot_id,)).fetchone()
            require(slot is not None, "SLOT_NOT_FOUND")
            if slot["pro_id"] == pro_id:
                return dict(slot_id=slot_id, pro_id=pro_id, state="reserved_demo")
            require(slot["pro_id"] is None, "SLOT_TAKEN")
            require(slot["version"] == expected_version, "STALE_VERSION")
            quote = json.loads(self.db.execute("SELECT snapshot FROM requests WHERE id=?", (slot["request_id"],)).fetchone()[0])
            require(now < quote["expires_at"], "QUOTE_EXPIRED")
            for item in quote["items"]:
                rate = self.db.execute("SELECT * FROM rates WHERE profile=? AND hours=? AND journey=?",
                                       (item["profile"], (slot["end"]-slot["start"])//3600, slot["journey"])).fetchone()
                require(rate is not None and rate["active"] == 1 and rate["version"] == item["rate_version"] and
                        rate["cents"] == item["unit_cents"] and rate["currency"] == quote["currency"], "REQUOTE_REQUIRED")
            require(pro_id in {p["id"] for p in self.candidates(slot_id, now)}, "PRO_INELIGIBLE")
            self.db.execute("INSERT INTO reservations VALUES (?,?,?,?)", (slot_id, pro_id, slot["start"], slot["end"]))
            self.db.execute("UPDATE slots SET pro_id=?,version=version+1 WHERE id=?", (pro_id, slot_id))
            result = dict(slot_id=slot_id, pro_id=pro_id, state="reserved_demo")
            self.db.execute("INSERT INTO events VALUES (?,?,?)", (slot_id+":reserved", "slot.reserved_demo", canonical(result)))
            return result


def demo_command():
    return dict(owner="client-demo", start="2030-06-10T12:00:00-06:00",
                end="2030-06-10T16:00:00-06:00", location=[0, 0],
                lines=[dict(profile="staff-demo", quantity=2)])


if __name__ == "__main__":
    engine = Engine()
    engine.seed_demo()
    clock = instant("2030-06-01T12:00:00-06:00")
    quote = engine.create_request(demo_command(), "demo-request-1", clock)
    print("1. COTIZACION", json.dumps(quote, indent=2, ensure_ascii=False))
    for sid in quote["slot_ids"]:
        ranked = engine.candidates(sid, clock)
        print("2. CANDIDATOS", json.dumps(ranked, ensure_ascii=False))
        print("3. RESERVA DEMO", engine.accept_demo(sid, ranked[0]["id"], 1, clock))
    print("4. EVENTOS DURABLES", engine.db.execute("SELECT count(*) FROM events").fetchone()[0])
    engine.close()
