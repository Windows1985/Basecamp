"""
Tests for server/backup.py.
All file operations use temporary directories so the real database is untouched.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

checks = []


def check(label, passed):
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {label}")
    checks.append(passed)


def _make_valid_db(path: Path) -> None:
    """Create a minimal valid SQLite database at path."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Import backup with a patched DB_PATH so it never touches the real db
# ---------------------------------------------------------------------------
import server.config as _cfg
_tmp_root = tempfile.mkdtemp()
_fake_db = Path(_tmp_root) / "data" / "basecamp.db"
_fake_db.parent.mkdir(parents=True)
_make_valid_db(_fake_db)
_cfg.DB_PATH = str(_fake_db)

from server.backup import run_backup, BACKUP_RETENTION

# ---------------------------------------------------------------------------
# Test 1: successful backup creates a valid file
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "src.db"
    bdir = Path(tmp) / "backups"
    _make_valid_db(src)

    result = run_backup(db_path=str(src), backup_dir=str(bdir))
    check("run_backup returns True on success", result is True)
    check("backups directory is created", bdir.exists())

    backups = list(bdir.glob("basecamp_*.db"))
    check("exactly one backup file created", len(backups) == 1)

    # Verify the backup is readable
    try:
        conn = sqlite3.connect(str(backups[0]))
        conn.execute("SELECT 1")
        conn.close()
        check("backup is a valid SQLite file", True)
    except Exception:
        check("backup is a valid SQLite file", False)

# ---------------------------------------------------------------------------
# Test 2: backup appears in data/backups/ (default path derivation)
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "basecamp.db"
    _make_valid_db(src)
    default_bdir = src.parent / "backups"

    result = run_backup(db_path=str(src))
    check("run_backup with default backup_dir returns True", result is True)
    check("default backup dir is data/backups/ sibling of db", default_bdir.exists())
    check("backup file present in default dir", len(list(default_bdir.glob("basecamp_*.db"))) == 1)

# ---------------------------------------------------------------------------
# Test 3: retention deletes files beyond BACKUP_RETENTION (30)
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "basecamp.db"
    bdir = Path(tmp) / "backups"
    bdir.mkdir()
    _make_valid_db(src)

    # Pre-populate with BACKUP_RETENTION old backup stubs
    for i in range(BACKUP_RETENTION):
        stub = bdir / f"basecamp_20250101_{i:06d}.db"
        _make_valid_db(stub)

    result = run_backup(db_path=str(src), backup_dir=str(bdir))
    check("run_backup succeeds with full retention set", result is True)

    remaining = sorted(bdir.glob("basecamp_*.db"))
    check(
        f"retention caps backups at {BACKUP_RETENTION}",
        len(remaining) == BACKUP_RETENTION,
    )
    # The oldest stubs should have been deleted; the newest (today's) should survive
    names = [p.name for p in remaining]
    check("newest backup is retained", any("202" in n and n > "basecamp_20250101" for n in names))

# ---------------------------------------------------------------------------
# Test 4: corrupted / missing source triggers failure and returns False
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    missing = Path(tmp) / "nonexistent.db"
    bdir = Path(tmp) / "backups"

    result = run_backup(db_path=str(missing), backup_dir=str(bdir))
    check("missing source db returns False", result is False)
    backups = list(bdir.glob("basecamp_*.db")) if bdir.exists() else []
    check("no backup file created when source missing", len(backups) == 0)

# Test 4b: source exists but is not a valid SQLite file
with tempfile.TemporaryDirectory() as tmp:
    bad_src = Path(tmp) / "corrupt.db"
    bad_src.write_bytes(b"this is not sqlite")
    bdir = Path(tmp) / "backups"

    result = run_backup(db_path=str(bad_src), backup_dir=str(bdir))
    check("corrupt source db returns False", result is False)
    leftover = list(bdir.glob("basecamp_*.db")) if bdir.exists() else []
    check("invalid backup file is cleaned up after validation failure", len(leftover) == 0)

# ---------------------------------------------------------------------------
# Cleanup temp root
# ---------------------------------------------------------------------------
shutil.rmtree(_tmp_root, ignore_errors=True)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
total = len(checks)
passed = sum(checks)
print(f"  {passed}/{total} checks passed.")
print()
if all(checks):
    print("All checks passed.")
    sys.exit(0)
else:
    print("One or more checks FAILED.")
    sys.exit(1)
