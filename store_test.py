"""Persistence check. Run: python store_test.py

Uses a throwaway DB so it never touches your real one.
"""
import json
import os
import tempfile
from datetime import date
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="ptohacker-test-"))
os.environ["PTOHACKER_DB"] = str(TMP / "test.db")

import store  # noqa: E402  (must come after the env var)

YEAR = 2026
store.init()
print(f"db: {store.DB_PATH}")

# --- settings round-trip, including falsy and None values -----------------
store.set_settings({"balance": 18, "home_city": "BLR", "require_bridge": False,
                    "subdiv": None, "longer_bias": 0.35})
s = store.all_settings()
assert s["balance"] == 18 and s["home_city"] == "BLR"
assert s["require_bridge"] is False, "False must survive, not become a default"
assert s["subdiv"] is None and "subdiv" in s, "None must survive as a stored value"
assert s["longer_bias"] == 0.35
store.set_setting("balance", 24)
assert store.get_setting("balance") == 24, "upsert should overwrite"
assert store.get_setting("nope", "fallback") == "fallback"
print(f"settings: {len(s)} keys round-tripped, upsert + default OK")

# --- company holidays, including the duplicate path -----------------------
rows = [{"date": "2026-12-24", "name": "Christmas Eve"},
        {"date": "2026-05-08", "name": "Founder's Day"}]
assert store.add_company_holidays(YEAR, rows) == 2
assert store.add_company_holidays(YEAR, rows) == 0, "re-import must not duplicate"
assert store.add_company_holidays(YEAR, []) == 0
got = store.company_holidays(YEAR)
assert [h["date"] for h in got] == ["2026-05-08", "2026-12-24"], "should be sorted"
assert store.company_holidays(2027) == [], "years must not bleed into each other"
store.remove_company_holiday(YEAR, "2026-05-08")
assert len(store.company_holidays(YEAR)) == 1
print(f"company holidays: insert/dedupe/remove/year-scope OK")

# --- commitments ----------------------------------------------------------
store.add_commitment(YEAR, date(2026, 6, 15), date(2026, 6, 17), "Wedding")
store.add_commitment(YEAR, date(2026, 9, 1), date(2026, 9, 2), "Visa")
cs = store.commitments(YEAR)
assert len(cs) == 2 and cs[0]["label"] == "Wedding"
assert cs[0]["start"] == "2026-06-15"
store.remove_commitment(cs[1]["id"])
assert len(store.commitments(YEAR)) == 1
print("commitments: add/list/remove by id OK")

# --- accepted breaks ------------------------------------------------------
store.add_accepted(YEAR, date(2026, 3, 2), date(2026, 3, 8))
store.add_accepted(YEAR, date(2026, 3, 2), date(2026, 3, 8))
assert len(store.accepted(YEAR)) == 1, "same span must not be accepted twice"
store.add_accepted_many(YEAR, [(date(2026, 5, 23), date(2026, 5, 31)),
                               (date(2026, 8, 22), date(2026, 8, 30))])
assert len(store.accepted(YEAR)) == 3
store.clear_accepted(YEAR)
assert store.accepted(YEAR) == []
print("accepted: dedupe/bulk/clear OK")

# --- watchlist via the public class --------------------------------------
from watchlist import Watchlist  # noqa: E402

wl = Watchlist()
item = wl.add("BLR", "GOI", date(2026, 3, 2), date(2026, 3, 8), note="Holi break")
item.record(11600)
item.record(12100)
item.record(9800)
assert len(Watchlist().items) == 1
again = Watchlist().items[item.key]
assert again.latest == 9800, f"latest wrong: {again.latest}"
assert again.best == 9800
assert again.delta == -2300, f"delta wrong: {again.delta}"
assert again.note == "Holi break"
print(f"watchlist: latest {again.latest}, best {again.best}, delta {again.delta}")

wl.add("BLR", "GOI", date(2026, 3, 2), date(2026, 3, 8), note="same route")
assert len(Watchlist().items) == 1, "re-adding a route must not duplicate it"


class _FakeProvider:
    def quote(self, o, d, dep, ret=None):
        class Q:
            price = 7777
        return Q()


n, failures = Watchlist().refresh(_FakeProvider())
assert n == 1 and failures == []
assert Watchlist().items[item.key].latest == 7777
print(f"watchlist refresh: {n} route re-quoted, history kept")

# --- cascade on delete ----------------------------------------------------
wl = Watchlist()
wl.remove(item.key)
assert Watchlist().items == {}
with store.connect() as con:
    left = con.execute("SELECT COUNT(*) c FROM watch_price").fetchone()["c"]
assert left == 0, f"price history orphaned: {left} rows"
print("delete: route and its price history both gone")

# --- legacy JSON migration -----------------------------------------------
legacy = TMP / "watchlist.json"
legacy.write_text(json.dumps({"items": [{
    "origin": "DEL", "destination": "IXL", "depart": "2026-05-23",
    "ret": "2026-05-31", "note": "old", "history": [
        {"checked_at": "2026-01-01T10:00:00", "price": 7200}]}]}), encoding="utf-8")
assert store.migrate_watchlist_json(legacy) == 1
assert not legacy.exists() and legacy.with_suffix(".json.migrated").exists()
moved = Watchlist().items
assert len(moved) == 1
only = next(iter(moved.values()))
assert only.origin == "DEL" and only.latest == 7200 and only.note == "old"
assert store.migrate_watchlist_json(legacy) == 0, "second run must be a no-op"
assert store.migrate_watchlist_json(TMP / "nothing.json") == 0
print("migration: legacy JSON imported once, file renamed, re-run is a no-op")

# --- survives a "restart": new connection, same file ----------------------
assert len(store.commitments(YEAR)) == 1
assert len(store.company_holidays(YEAR)) == 1
assert store.get_setting("home_city") == "BLR"
print("restart: state still there on a fresh connection")

print("\nALL STORE CHECKS PASSED")
