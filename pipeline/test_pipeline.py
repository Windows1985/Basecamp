"""
Integration test: generates 10 simulated nights and runs the full pipeline on each.
Run from the project root:  python pipeline/test_pipeline.py
"""
import os
import sys
import sqlite3
import tempfile
import traceback
from datetime import datetime, timedelta

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.db import init_db
from pipeline.simulate import simulate_night
from pipeline.batch import run_pipeline


N_NIGHTS = 10
# Qualities spread from poor to excellent
QUALITIES = [0.1, 0.2, 0.35, 0.4, 0.5, 0.6, 0.7, 0.75, 0.85, 0.95]


def main():
    # ---- Set up a fresh test database ------------------------------------
    db_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="basecamp_test_")
    os.close(db_fd)

    print("=" * 60)
    print(f"Basecamp pipeline integration test")
    print(f"Database: {db_path}")
    print("=" * 60)

    init_db(db_path)

    results = []
    all_errors = []

    # ---- Simulate N nights and run the pipeline --------------------------
    for night_idx in range(N_NIGHTS):
        quality = QUALITIES[night_idx]
        # Start each night slightly before midnight, separated by 24 h
        night_start = datetime.now().replace(
            hour=22, minute=30, second=0, microsecond=0
        ) - timedelta(days=N_NIGHTS - night_idx)

        print(f"\n{'─' * 60}")
        print(f"Night {night_idx + 1}/{N_NIGHTS}  quality={quality:.2f}  "
              f"date={night_start.strftime('%Y-%m-%d')}")
        print("─" * 60)

        try:
            session_id = simulate_night(
                quality=quality,
                start_time=night_start,
                db_path=db_path,
            )
            print(f"  Simulated session_id={session_id}")
        except Exception as e:
            msg = f"Night {night_idx+1}: simulate_night failed: {e}"
            print(f"  FAILED: {msg}")
            traceback.print_exc()
            all_errors.append(msg)
            results.append({
                "night": night_idx + 1,
                "quality": quality,
                "session_id": "ERR",
                "total": "—",
                "arch": "—",
                "cont": "—",
                "brth": "—",
                "env": "—",
            })
            continue

        try:
            summary = run_pipeline(session_id=session_id, db_path=db_path)
            scores = summary.get("scores") or {}
            all_errors.extend(summary.get("errors", []))

            results.append({
                "night": night_idx + 1,
                "quality": quality,
                "session_id": session_id,
                "total": scores.get("total_score", "—"),
                "arch": scores.get("architecture_score", "—"),
                "cont": scores.get("continuity_score", "—"),
                "brth": scores.get("breathing_score", "—"),
                "env": scores.get("environment_score", "—"),
            })
        except Exception as e:
            msg = f"Night {night_idx+1}: run_pipeline failed: {e}"
            print(f"  PIPELINE FAILED: {msg}")
            traceback.print_exc()
            all_errors.append(msg)
            results.append({
                "night": night_idx + 1,
                "quality": quality,
                "session_id": session_id,
                "total": "ERR",
                "arch": "—",
                "cont": "—",
                "brth": "—",
                "env": "—",
            })

    # ---- Summary table ---------------------------------------------------
    print(f"\n{'=' * 80}")
    print(f"{'Night':>5}  {'Quality':>7}  {'SID':>4}  "
          f"{'Total':>6}  {'Arch':>6}  {'Cont':>6}  {'Brth':>6}  {'Env':>6}")
    print("─" * 80)
    for r in results:
        print(
            f"{r['night']:>5}  {r['quality']:>7.2f}  {str(r['session_id']):>4}  "
            f"{str(r['total']):>6}  {str(r['arch']):>6}  "
            f"{str(r['cont']):>6}  {str(r['brth']):>6}  {str(r['env']):>6}"
        )
    print("=" * 80)

    # ---- Print the final night's ntfy report -----------------------------
    final_session_id = results[-1]["session_id"]
    if final_session_id not in ("ERR", None):
        print(f"\n{'═' * 60}")
        print(f"FULL REPORT — Night {N_NIGHTS} (session {final_session_id}):")
        print("═" * 60)
        try:
            from pipeline.report import generate_report
            report_text = generate_report(final_session_id, db_path)
            print(report_text)
        except Exception as e:
            print(f"Could not generate report: {e}")
        print("═" * 60)

    # ---- Final verdict ---------------------------------------------------
    print(f"\nTotal errors across all steps: {len(all_errors)}")
    if all_errors:
        print("Errors encountered:")
        for err in all_errors:
            print(f"  • {err}")
    else:
        print("All steps completed without errors.")

    # Clean up temp db
    try:
        os.unlink(db_path)
    except Exception:
        pass

    return len(all_errors) == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
