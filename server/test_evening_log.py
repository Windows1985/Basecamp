"""
Tests for the evening log Flask endpoints in morning/app.py.
"""
import json
import os
import sys
import tempfile

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, PROJECT_ROOT)

import server.config as _cfg

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
_cfg.DB_PATH = _tmp_db.name

from server.db import init_db
init_db(_tmp_db.name)

# Point the Flask app at the temp DB before importing it
import morning.app as _app_mod
_app_mod._DB_PATH = _tmp_db.name

client = _app_mod.app.test_client()

checks = []


def check(label, passed):
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {label}")
    checks.append(passed)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def post_evening(payload):
    return client.post(
        "/log/evening",
        data=json.dumps(payload),
        content_type="application/json",
    )


def get_by_date(date):
    return client.get(f"/log/evening/{date}")


# ---------------------------------------------------------------------------
# Test: submit an evening log
# ---------------------------------------------------------------------------
resp = post_evening({
    "date": "2026-06-09",
    "stress": 6,
    "exercise": 1,
    "exercise_intensity": 3,
    "caffeine_last_dose": "14:30",
    "screen_off_time": "22:00",
    "notes": "Felt okay",
})
body = json.loads(resp.data)
check("POST /log/evening returns 200", resp.status_code == 200)
check("POST /log/evening returns success=true", body.get("success") is True)
check("POST /log/evening returns an id", isinstance(body.get("id"), int))
first_id = body.get("id")

# ---------------------------------------------------------------------------
# Test: retrieve by date
# ---------------------------------------------------------------------------
resp = get_by_date("2026-06-09")
row = json.loads(resp.data)
check("GET /log/evening/<date> returns 200", resp.status_code == 200)
check("date field matches", row.get("date") == "2026-06-09")
check("stress field matches", row.get("stress") == 6)
check("caffeine_last_dose matches", row.get("caffeine_last_dose") == "14:30")
check("exercise matches", row.get("exercise") == 1)
check("exercise_intensity matches", row.get("exercise_intensity") == 3)
check("screen_off_time matches", row.get("screen_off_time") == "22:00")
check("notes match", row.get("notes") == "Felt okay")

# ---------------------------------------------------------------------------
# Test: upsert — second POST for same date updates, not duplicates
# ---------------------------------------------------------------------------
resp2 = post_evening({
    "date": "2026-06-09",
    "stress": 8,
    "notes": "Updated note",
})
body2 = json.loads(resp2.data)
check("upsert returns success=true", body2.get("success") is True)
check("upsert returns same id", body2.get("id") == first_id)

resp_check = get_by_date("2026-06-09")
updated = json.loads(resp_check.data)
check("upsert updates stress", updated.get("stress") == 8)
check("upsert updates notes", updated.get("notes") == "Updated note")

# Confirm only one row for that date in the DB
from server.db import get_connection
conn = get_connection(_tmp_db.name)
count = conn.execute("SELECT COUNT(*) FROM evening_log WHERE date='2026-06-09'").fetchone()[0]
conn.close()
check("upsert does not insert a duplicate row", count == 1)

# ---------------------------------------------------------------------------
# Test: 404 on missing date
# ---------------------------------------------------------------------------
resp = get_by_date("1999-01-01")
check("GET /log/evening/<missing-date> returns 404", resp.status_code == 404)

# ---------------------------------------------------------------------------
# Test: GET /log/evening returns latest entry
# ---------------------------------------------------------------------------
post_evening({"date": "2026-06-08", "stress": 4})
resp = client.get("/log/evening")
latest = json.loads(resp.data)
check("GET /log/evening (latest) returns 200", resp.status_code == 200)
check("GET /log/evening returns most recent date", latest.get("date") == "2026-06-09")

# ---------------------------------------------------------------------------
# Test: GET /log/evening/history returns all entries ordered desc
# ---------------------------------------------------------------------------
resp = client.get("/log/evening/history")
history = json.loads(resp.data)
check("GET /log/evening/history returns 200", resp.status_code == 200)
check("history contains 2 entries", len(history) == 2)
check("history ordered date descending", history[0]["date"] >= history[1]["date"])

# ---------------------------------------------------------------------------
# Test: date is required
# ---------------------------------------------------------------------------
resp = post_evening({"stress": 5})
check("POST without date returns 400", resp.status_code == 400)

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
os.unlink(_tmp_db.name)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
all_pass = all(checks)
total = len(checks)
passed = sum(checks)
print(f"  {passed}/{total} checks passed.")
print()
if all_pass:
    print("All checks passed.")
    sys.exit(0)
else:
    print("One or more checks FAILED.")
    sys.exit(1)
