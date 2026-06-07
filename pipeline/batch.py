"""
Master pipeline orchestrator — runs the full morning analysis in sequence.
Triggered by the presence watcher after bed exit is detected.
"""
import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.db import get_connection, get_latest_session_id
from server.config import MIN_SLEEP_HOURS


def run_pipeline(session_id=None, db_path=None):
    """
    Run the full morning pipeline for a sleep session.

    session_id : int or None (defaults to most recent session)
    db_path    : path to SQLite database

    Returns a summary dict with step results and any errors encountered.
    """
    if db_path is None:
        from server.config import DB_PATH
        db_path = DB_PATH

    summary = {
        "session_id": None,
        "features": None,
        "scores": None,
        "positives": [],
        "negatives": [],
        "anomaly": None,
        "report": None,
        "errors": [],
    }

    # ---- Step 1: Identify session ----------------------------------------
    try:
        if session_id is None:
            session_id = get_latest_session_id(db_path)
        if session_id is None:
            raise RuntimeError("No sleep sessions found in database")

        conn = get_connection(db_path)
        try:
            session = conn.execute(
                "SELECT bed_entry, bed_exit, duration_hours FROM sleep_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        finally:
            conn.close()

        if session is None:
            raise RuntimeError(f"Session {session_id} not found")

        if session["duration_hours"] < MIN_SLEEP_HOURS:
            raise RuntimeError(
                f"Session duration {session['duration_hours']:.1f}h is below "
                f"minimum {MIN_SLEEP_HOURS}h threshold"
            )

        summary["session_id"] = session_id
        print(f"[1/7] Session {session_id}: "
              f"{session['bed_entry']} → {session['bed_exit']} "
              f"({session['duration_hours']:.1f}h)")
    except Exception as e:
        summary["errors"].append(f"Step 1 (identify session): {e}")
        print(f"[1/7] FAILED: {e}")
        return summary

    # ---- Step 2: Feature extraction ---------------------------------------
    try:
        from pipeline.features import extract_features
        features = extract_features(session_id, db_path)
        summary["features"] = features
        print(
            f"[2/7] Features extracted — "
            f"deep {features['deep_sleep_proportion']*100:.0f}%, "
            f"REM {features['rem_proportion']*100:.0f}%, "
            f"awakenings {features['awakening_count']}, "
            f"peak CO2 {features['peak_co2']:.0f}ppm"
        )
    except Exception as e:
        summary["errors"].append(f"Step 2 (features): {e}")
        print(f"[2/7] FAILED: {e}")
        traceback.print_exc()

    # ---- Step 3: Recovery scoring ----------------------------------------
    try:
        if summary["features"] is None:
            raise RuntimeError("No features available")
        from pipeline.score import calculate_recovery_score
        scores = calculate_recovery_score(summary["features"], session_id, db_path)
        summary["scores"] = scores
        print(
            f"[3/7] Recovery score: {scores['total_score']}/100  "
            f"(arch {scores['architecture_score']}  "
            f"cont {scores['continuity_score']}  "
            f"brth {scores['breathing_score']}  "
            f"env {scores['environment_score']})"
        )
    except Exception as e:
        summary["errors"].append(f"Step 3 (scoring): {e}")
        print(f"[3/7] FAILED: {e}")
        traceback.print_exc()

    # ---- Step 4: SHAP attribution -----------------------------------------
    try:
        if summary["features"] is None or summary["scores"] is None:
            raise RuntimeError("Features or scores unavailable")
        from pipeline.attribution import generate_attribution
        positives, negatives = generate_attribution(
            session_id, summary["features"], summary["scores"], db_path
        )
        summary["positives"] = positives
        summary["negatives"] = negatives
        print(f"[4/7] Attribution — {len(positives)} positive, {len(negatives)} negative factors")
    except Exception as e:
        summary["errors"].append(f"Step 4 (attribution): {e}")
        print(f"[4/7] FAILED: {e}")
        traceback.print_exc()

    # ---- Step 5: Anomaly detection ----------------------------------------
    try:
        from pipeline.anomaly import detect_anomaly
        is_anomaly, description = detect_anomaly(session_id, db_path)
        summary["anomaly"] = {"is_anomaly": is_anomaly, "description": description}
        if is_anomaly is None:
            print("[5/7] Anomaly detection skipped (insufficient baseline data)")
        elif is_anomaly:
            print(f"[5/7] ANOMALY: {description}")
        else:
            print(f"[5/7] No anomaly detected")
    except Exception as e:
        summary["errors"].append(f"Step 5 (anomaly): {e}")
        print(f"[5/7] FAILED: {e}")
        traceback.print_exc()

    # ---- Step 6: Generate and send ntfy report ----------------------------
    try:
        from pipeline.report import generate_report
        report = generate_report(session_id, db_path)
        summary["report"] = report
        print(f"[6/7] Report generated and sent via ntfy")
    except Exception as e:
        summary["errors"].append(f"Step 6 (report): {e}")
        print(f"[6/7] FAILED: {e}")
        traceback.print_exc()

    # ---- Step 7: Retrain anomaly model if >= 7 sessions -------------------
    try:
        conn = get_connection(db_path)
        try:
            session_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM sleep_sessions"
            ).fetchone()["cnt"]
        finally:
            conn.close()

        if session_count >= 7:
            from pipeline.anomaly import train_baseline
            trained = train_baseline(db_path)
            if trained:
                print(f"[7/7] Anomaly model retrained on {session_count} sessions")
            else:
                print(f"[7/7] Anomaly model training skipped (< 7 sessions with scores)")
        else:
            print(f"[7/7] Anomaly model training skipped ({session_count} sessions total, need 7)")
    except Exception as e:
        summary["errors"].append(f"Step 7 (retrain): {e}")
        print(f"[7/7] FAILED: {e}")
        traceback.print_exc()

    if summary["errors"]:
        print(f"\nCompleted with {len(summary['errors'])} error(s):")
        for err in summary["errors"]:
            print(f"  - {err}")
    else:
        print("\nPipeline completed successfully.")
        _cleanup_old_audio(db_path)

    return summary


def _cleanup_old_audio(db_path):
    """
    Delete .opus audio files older than AUDIO_RETENTION_DAYS.
    SQLite rows are kept; only the actual files are removed.
    """
    try:
        from server.config import AUDIO_RETENTION_DAYS
        cutoff = datetime.utcnow() - timedelta(days=AUDIO_RETENTION_DAYS)
        audio_dir = Path(db_path).parent / "audio"
        if not audio_dir.exists():
            return
        deleted = 0
        for f in audio_dir.glob("*.opus"):
            try:
                mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    f.unlink()
                    deleted += 1
            except Exception:
                pass
        if deleted:
            print(f"[cleanup] Removed {deleted} audio file(s) older than {AUDIO_RETENTION_DAYS} days")
    except Exception as e:
        print(f"[cleanup] Audio cleanup error: {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the Basecamp morning pipeline")
    parser.add_argument("--session", type=int, default=None, help="Session ID")
    parser.add_argument("--db", default=None, help="Database path")
    args = parser.parse_args()

    run_pipeline(session_id=args.session, db_path=args.db)
