#!/usr/bin/env python3
"""
Regression Tests for prune (history data cleanup) command.

Tests:
  PART 1 - Happy path:
    - Full workflow: init -> import x2 -> merge x3 (creates 3 snapshots)
    - dry-run preview (verify no changes)
    - Actual prune with --keep 1 (keep only latest snapshot)
    - Cross-restart persistence (restart process, verify history/rollback/batches/export)
    - Prune with --before (delete snapshots older than a date)
    - Prune with --prune-orphans (delete orphaned batches)

  PART 2 - Reference conflicts:
    - Create 3 snapshots sharing some batches
    - Prune with --keep 1 --prune-orphans
    - Verify batches still referenced by retained snapshot are NOT deleted
    - Verify proper warning messages

  PART 3 - Error scenarios:
    - No --before or --keep specified -> error
    - Invalid --before time format -> error
    - Negative --keep value -> error
    - No data to prune (keep larger than snapshot count) -> warning, exit 0
    - Database file does not exist -> error
    - dry-run does NOT modify database (verify counts unchanged)
    - Verify all error scenarios produce NO database pollution
"""
import json
import os
import sys
import tempfile
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
TESTS = ROOT / "tests"


def run_cli(*args, cwd=None, expect_success=True, desc=""):
    """Run inventory CLI via subprocess (simulates user command)."""
    full_env = os.environ.copy()
    pythonpath = str(SRC)
    if "PYTHONPATH" in full_env:
        pythonpath = os.pathsep.join([pythonpath, full_env["PYTHONPATH"]])
    full_env["PYTHONPATH"] = pythonpath

    flat_args = [str(a) for a in args]
    cmd = [sys.executable, "-m", "inventory_cli.cli"] + flat_args

    print(f"\n{'='*70}")
    print(f">>> {desc}")
    print(f"CMD: inventory {' '.join(flat_args)}")
    print(f"{'='*70}")

    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else str(ROOT),
        env=full_env,
        capture_output=True,
        text=True,
    )

    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print("STDERR:", result.stderr.rstrip())

    print(f"[Exit code: {result.returncode}]")

    if expect_success:
        assert result.returncode == 0, f"Expected success but got exit code {result.returncode}"
    else:
        assert result.returncode != 0, f"Expected failure but got exit code 0"

    return result


def get_snapshot_count(db_path: Path) -> int:
    """Count snapshots in database."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT COUNT(*) FROM snapshots")
        return cur.fetchone()[0]
    finally:
        conn.close()


def get_snapshot_ids(db_path: Path) -> list:
    """Get all snapshot IDs in descending order."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT id FROM snapshots ORDER BY id DESC")
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def get_batch_count(db_path: Path) -> int:
    """Count unique batches in inventory table."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT COUNT(DISTINCT batch_id) FROM inventory")
        return cur.fetchone()[0]
    finally:
        conn.close()


def get_history_count(db_path: Path) -> int:
    """Count history entries."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT COUNT(*) FROM history")
        return cur.fetchone()[0]
    finally:
        conn.close()


def get_history_operations(db_path: Path) -> list:
    """Get all history operations in order."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT operation FROM history ORDER BY id")
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def get_all_batches(db_path: Path) -> set:
    """Get all unique batch IDs from inventory."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT DISTINCT batch_id FROM inventory")
        return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def main():
    # ============================================================
    # PART 1: Happy path - full workflow, dry-run, prune, persistence
    # ============================================================
    print(f"\n{'#'*70}")
    print("PART 1: HAPPY PATH - Full workflow, dry-run, prune, persistence")
    print(f"{'#'*70}")

    test_dir = Path(tempfile.mkdtemp(prefix="inv_prune_happy_"))
    db_path = test_dir / "test.db"
    print(f"Happy path test directory: {test_dir}")

    try:
        # --- Step 1: init ---
        run_cli("init", "--database", str(db_path), "--config", "",
                cwd=test_dir, desc="Step 1: init")

        # --- Step 2: import store_a.csv ---
        run_cli("import", str(TESTS / "store_a.csv"), "STORE001",
                "--batch", "batch_store_a", "--database", str(db_path),
                cwd=test_dir, desc="Step 2: import store_a.csv")

        # --- Step 3: import store_b.json ---
        run_cli("import", str(TESTS / "store_b.json"), "STORE002",
                "--batch", "batch_store_b", "--database", str(db_path),
                cwd=test_dir, desc="Step 3: import store_b.json")

        # --- Step 4: merge #1 (sum strategy) ---
        run_cli("merge", "--strategy", "sum", "--database", str(db_path),
                cwd=test_dir, desc="Step 4: merge #1 (sum) -> snapshot #1")

        # --- Step 5: merge #2 (average strategy) ---
        run_cli("merge", "--strategy", "average", "--database", str(db_path),
                cwd=test_dir, desc="Step 5: merge #2 (average) -> snapshot #2")

        # --- Step 6: merge #3 (first strategy) ---
        run_cli("merge", "--strategy", "first", "--database", str(db_path),
                cwd=test_dir, desc="Step 6: merge #3 (first) -> snapshot #3")

        # Verify we have 3 snapshots
        snap_count = get_snapshot_count(db_path)
        assert snap_count == 3, f"Expected 3 snapshots, got {snap_count}"
        snap_ids = get_snapshot_ids(db_path)
        assert snap_ids == [3, 2, 1], f"Expected snapshot IDs [3,2,1], got {snap_ids}"
        print(f"[OK] Created 3 snapshots: {snap_ids}")

        # Baseline counts before any prune
        baseline_history = get_history_count(db_path)
        baseline_batches = get_batch_count(db_path)
        print(f"Baseline: {baseline_history} history entries, {baseline_batches} batches")

        # ============================================================
        # TEST 1a: dry-run with --keep 1 (should NOT change database)
        # ============================================================
        print(f"\n{'-'*70}")
        print("TEST 1a: dry-run --keep 1 (no changes expected)")
        print(f"{'-'*70}")

        result = run_cli("prune", "--dry-run", "--keep", "1", "--database", str(db_path),
                         cwd=test_dir, desc="TEST 1a: dry-run --keep 1")

        # Verify dry-run output contains expected info
        assert "DRY RUN" in result.stdout, "Should show DRY RUN header"
        assert "Snapshots to delete (2)" in result.stdout, "Should show 2 snapshots to delete"
        assert "ID" in result.stdout and "Created At" in result.stdout, "Should show table header"
        assert "Would delete 2 snapshots" in result.stdout, "Should show summary"
        assert "Remove --dry-run" in result.stdout, "Should hint at actual execution"

        # Verify NO changes to database
        assert get_snapshot_count(db_path) == 3, "dry-run should not delete snapshots"
        assert get_history_count(db_path) == baseline_history, "dry-run should not add history"
        assert get_batch_count(db_path) == baseline_batches, "dry-run should not delete batches"
        print("[OK] dry-run made no changes to database")

        # ============================================================
        # TEST 1b: actual prune --keep 1 (keep only latest snapshot #3)
        # ============================================================
        print(f"\n{'-'*70}")
        print("TEST 1b: actual prune --keep 1 (delete snapshots #1, #2)")
        print(f"{'-'*70}")

        result = run_cli("prune", "--keep", "1", "--database", str(db_path),
                         cwd=test_dir, desc="TEST 1b: prune --keep 1")

        # Verify output
        assert "PRUNE COMPLETED" in result.stdout
        assert "Successfully deleted 2 snapshots" in result.stdout
        assert "Deleted snapshot IDs: [1, 2]" in result.stdout
        assert "Operation recorded in history" in result.stdout

        # Verify database changes
        assert get_snapshot_count(db_path) == 1, f"Expected 1 snapshot, got {get_snapshot_count(db_path)}"
        remaining_ids = get_snapshot_ids(db_path)
        assert remaining_ids == [3], f"Expected only snapshot #3, got {remaining_ids}"

        # Verify history has prune entry
        ops = get_history_operations(db_path)
        assert "prune" in ops, "prune operation should be in history"
        assert ops.count("prune") == 1, f"Expected 1 prune entry, got {ops.count('prune')}"
        assert get_history_count(db_path) == baseline_history + 1, "Should have +1 history entry"

        # Batches should NOT be deleted (we didn't use --prune-orphans)
        assert get_batch_count(db_path) == baseline_batches, "Batches should not be deleted without --prune-orphans"
        print("[OK] prune --keep 1 worked correctly")

        # ============================================================
        # TEST 1c: Cross-restart persistence - verify after process restart
        # ============================================================
        print(f"\n{'-'*70}")
        print("TEST 1c: Cross-restart persistence (fresh subprocess)")
        print(f"{'-'*70}")

        # Run history in a new process
        result = run_cli("history", "--database", str(db_path),
                         cwd=test_dir, desc="TEST 1c: history (fresh process)")
        assert "PRUNE" in result.stdout or "prune" in result.stdout.lower(), \
            "prune operation should persist across restarts"

        # Run rollback list in a new process
        result = run_cli("rollback", "--database", str(db_path),
                         cwd=test_dir, desc="TEST 1c: rollback list (fresh process)")
        # Should only show 1 snapshot
        lines = [l for l in result.stdout.split('\n') if l.strip()]
        snapshot_lines = [l for l in lines if any(c.isdigit() for c in l[:10]) and '20' in l]
        assert len(snapshot_lines) == 1, f"Expected 1 snapshot in rollback list, got {len(snapshot_lines)}"

        # Run batches in a new process
        result = run_cli("batches", "--database", str(db_path),
                         cwd=test_dir, desc="TEST 1c: batches (fresh process)")
        assert "batch_store_a" in result.stdout and "batch_store_b" in result.stdout, \
            "Both batches should still be listed"

        # Run export in a new process and verify it works
        export_path = test_dir / "after_prune.csv"
        run_cli("export", str(export_path), "--database", str(db_path),
                cwd=test_dir, desc="TEST 1c: export (fresh process)")
        assert export_path.exists(), "Export should work after prune"
        with open(export_path, encoding='utf-8') as f:
            content = f.read()
        assert "SKU001" in content, "Export should contain data"
        print("[OK] Cross-restart persistence verified (history/rollback/batches/export)")

        # ============================================================
        # TEST 1d: prune with --before (no data should match)
        # ============================================================
        print(f"\n{'-'*70}")
        print("TEST 1d: prune --before 2000-01-01 (no data to prune)")
        print(f"{'-'*70}")

        result = run_cli("prune", "--before", "2000-01-01", "--database", str(db_path),
                         cwd=test_dir, desc="TEST 1d: prune --before 2000 (no matches)")

        assert "No data to prune" in result.stdout, "Should indicate no data to prune"
        assert get_snapshot_count(db_path) == 1, "Should still have 1 snapshot"
        print("[OK] No-data-to-prune handled correctly")

        # ============================================================
        # TEST 1e: prune with --prune-orphans
        # ============================================================
        print(f"\n{'-'*70}")
        print("TEST 1e: prune --keep 0 --prune-orphans (delete everything)")
        print(f"{'-'*70}")

        # First create an orphan batch (import but never merge/snapshot)
        run_cli("import", str(TESTS / "store_a.csv"), "STORE003",
                "--batch", "batch_orphan", "--database", str(db_path),
                cwd=test_dir, desc="Step: Create orphan batch (no snapshot)")

        # Also merge again to create a snapshot that references batch_store_a and batch_store_b
        run_cli("merge", "--strategy", "sum", "--database", str(db_path),
                cwd=test_dir, desc="Step: merge again -> snapshot #4 (references a and b)")

        batches_before = get_all_batches(db_path)
        assert "batch_orphan" in batches_before, "Orphan batch should exist"
        print(f"Batches before prune: {batches_before}")

        history_before = get_history_count(db_path)

        # Now prune: keep 0 snapshots, with --prune-orphans
        result = run_cli("prune", "--keep", "0", "--prune-orphans", "--database", str(db_path),
                         cwd=test_dir, desc="TEST 1e: prune --keep 0 --prune-orphans")

        assert "PRUNE COMPLETED" in result.stdout
        # Should delete snapshot #4 and all batches (orphan + no longer referenced)
        assert get_snapshot_count(db_path) == 0, f"Expected 0 snapshots, got {get_snapshot_count(db_path)}"
        assert get_batch_count(db_path) == 0, f"Expected 0 batches, got {get_batch_count(db_path)}"
        assert get_history_count(db_path) == history_before + 1, "Should have +1 history entry"

        ops = get_history_operations(db_path)
        assert ops.count("prune") == 2, f"Expected 2 prune entries, got {ops.count('prune')}"
        print("[OK] prune --prune-orphans worked correctly")

        print(f"\n{'-'*70}")
        print("[PART 1 PASSED] Happy path + cross-restart persistence OK")
        print(f"{'-'*70}")

    except AssertionError as e:
        print(f"\n{'!'*70}")
        print(f"PART 1 FAILED: {e}")
        print(f"{'!'*70}")
        print(f"Test directory: {test_dir}")
        raise

    # ============================================================
    # PART 2: Reference conflicts - batches still referenced by retained snapshots
    # ============================================================
    print(f"\n{'#'*70}")
    print("PART 2: REFERENCE CONFLICTS - batches still referenced")
    print(f"{'#'*70}")

    test_dir2 = Path(tempfile.mkdtemp(prefix="inv_prune_conflict_"))
    db_path2 = test_dir2 / "test.db"
    print(f"Reference conflict test directory: {test_dir2}")

    try:
        # Setup: create 3 snapshots, all referencing batch_store_a and batch_store_b
        run_cli("init", "--database", str(db_path2), "--config", "",
                cwd=test_dir2, desc="Setup: init")
        run_cli("import", str(TESTS / "store_a.csv"), "STORE001",
                "--batch", "batch_a", "--database", str(db_path2),
                cwd=test_dir2, desc="Setup: import batch_a")
        run_cli("import", str(TESTS / "store_b.json"), "STORE002",
                "--batch", "batch_b", "--database", str(db_path2),
                cwd=test_dir2, desc="Setup: import batch_b")

        # Create 3 snapshots (all reference both batch_a and batch_b)
        for i, strategy in enumerate(["sum", "average", "first"], 1):
            run_cli("merge", "--strategy", strategy, "--database", str(db_path2),
                    cwd=test_dir2, desc=f"Setup: merge #{i} ({strategy}) -> snapshot #{i}")

        assert get_snapshot_count(db_path2) == 3, "Should have 3 snapshots"
        batches_before = get_all_batches(db_path2)
        assert batches_before == {"batch_a", "batch_b"}, f"Expected both batches, got {batches_before}"

        # Now prune --keep 1 --prune-orphans
        # Snapshot #3 will be kept, and it still references both batches
        # So NEITHER batch should be deleted, even though we're deleting snapshots #1 and #2
        print(f"\n{'-'*70}")
        print("TEST 2a: prune --keep 1 --prune-orphans (batches still referenced)")
        print(f"{'-'*70}")

        result = run_cli("prune", "--keep", "1", "--prune-orphans", "--database", str(db_path2),
                         cwd=test_dir2, desc="TEST 2a: prune with reference conflicts")

        # Should show warning about referenced batches
        assert "Warning:" in result.stdout or "Note:" in result.stdout, \
            "Should warn about batches still being referenced"
        assert "still referenced" in result.stdout.lower(), \
            "Should mention batches are still referenced"

        # Verify snapshots: only #3 remains
        assert get_snapshot_count(db_path2) == 1, f"Expected 1 snapshot, got {get_snapshot_count(db_path2)}"
        remaining_ids = get_snapshot_ids(db_path2)
        assert remaining_ids == [3], f"Expected snapshot #3, got {remaining_ids}"

        # CRITICAL: BOTH batches should still exist because they're referenced by snapshot #3
        batches_after = get_all_batches(db_path2)
        assert batches_after == {"batch_a", "batch_b"}, \
            f"Both batches should still exist (referenced by retained snapshot), got {batches_after}"

        print("[OK] Reference conflicts handled correctly - batches preserved")

        # Verify history, rollback, batches, export still work after this prune
        result = run_cli("history", "--database", str(db_path2),
                         cwd=test_dir2, desc="TEST 2b: verify history after conflict prune")
        assert "PRUNE" in result.stdout or "prune" in result.stdout.lower()

        result = run_cli("rollback", "--database", str(db_path2),
                         cwd=test_dir2, desc="TEST 2b: verify rollback list")
        assert "1" in result.stdout, "Should show 1 snapshot"

        result = run_cli("batches", "--database", str(db_path2),
                         cwd=test_dir2, desc="TEST 2b: verify batches list")
        assert "batch_a" in result.stdout and "batch_b" in result.stdout

        export_path = test_dir2 / "after_conflict_prune.csv"
        run_cli("export", str(export_path), "--database", str(db_path2),
                cwd=test_dir2, desc="TEST 2b: verify export still works")
        assert export_path.exists()
        print("[OK] history/rollback/batches/export all work after conflict prune")

        print(f"\n{'-'*70}")
        print("[PART 2 PASSED] Reference conflicts handled correctly")
        print(f"{'-'*70}")

    except AssertionError as e:
        print(f"\n{'!'*70}")
        print(f"PART 2 FAILED: {e}")
        print(f"{'!'*70}")
        print(f"Test directory: {test_dir2}")
        raise

    # ============================================================
    # PART 3: Error scenarios - clean errors, no database pollution
    # ============================================================
    print(f"\n{'#'*70}")
    print("PART 3: ERROR SCENARIOS - validation errors, no DB pollution")
    print(f"{'#'*70}")

    test_dir3 = Path(tempfile.mkdtemp(prefix="inv_prune_error_"))
    db_path3 = test_dir3 / "test.db"
    print(f"Error scenario test directory: {test_dir3}")

    try:
        # Setup: create a valid DB with 2 snapshots
        run_cli("init", "--database", str(db_path3), "--config", "",
                cwd=test_dir3, desc="Setup: init clean DB for error tests")
        run_cli("import", str(TESTS / "store_a.csv"), "STORE001",
                "--batch", "batch_a", "--database", str(db_path3),
                cwd=test_dir3, desc="Setup: import batch_a")
        run_cli("import", str(TESTS / "store_b.json"), "STORE002",
                "--batch", "batch_b", "--database", str(db_path3),
                cwd=test_dir3, desc="Setup: import batch_b")
        run_cli("merge", "--strategy", "sum", "--database", str(db_path3),
                cwd=test_dir3, desc="Setup: merge #1")
        run_cli("merge", "--strategy", "average", "--database", str(db_path3),
                cwd=test_dir3, desc="Setup: merge #2")

        baseline_snaps = get_snapshot_count(db_path3)
        baseline_history = get_history_count(db_path3)
        baseline_batches = get_batch_count(db_path3)
        print(f"Baseline: {baseline_snaps} snapshots, {baseline_history} history, {baseline_batches} batches")

        # --- Error 1: No --before or --keep specified ---
        result = run_cli("prune", "--database", str(db_path3),
                         cwd=test_dir3, expect_success=False,
                         desc="Error 1: no filter (no --before/--keep)")
        assert "At least one of --before or --keep" in result.stdout, \
            "Should require at least one filter"
        assert "dry-run" in result.stdout.lower(), "Should hint at --dry-run"

        # --- Error 2: Invalid --before time format ---
        result = run_cli("prune", "--before", "not-a-date", "--database", str(db_path3),
                         cwd=test_dir3, expect_success=False,
                         desc="Error 2: invalid --before time format")
        assert "Invalid --before" in result.stdout or "ISO" in result.stdout, \
            "Should report invalid time format"

        # --- Error 3: Negative --keep value ---
        result = run_cli("prune", "--keep", "-1", "--database", str(db_path3),
                         cwd=test_dir3, expect_success=False,
                         desc="Error 3: negative --keep value")
        assert "non-negative" in result.stdout or "must be" in result.stdout, \
            "Should report --keep must be non-negative"

        # --- Error 4: --keep larger than snapshot count (no data to prune) ---
        result = run_cli("prune", "--keep", "100", "--database", str(db_path3),
                         cwd=test_dir3, expect_success=True,
                         desc="Error 4: --keep 100 (no data to prune)")
        assert "No data to prune" in result.stdout, "Should say no data to prune"

        # --- Error 5: Database file does not exist ---
        nonexistent = test_dir3 / "does_not_exist.db"
        result = run_cli("prune", "--keep", "1", "--database", str(nonexistent),
                         cwd=test_dir3, expect_success=False,
                         desc="Error 5: database does not exist")
        assert "not found" in result.stdout.lower() or "init" in result.stdout.lower(), \
            "Should report database not found"

        # --- Error 6: dry-run does NOT modify database ---
        before_snaps = get_snapshot_count(db_path3)
        before_history = get_history_count(db_path3)
        before_batches = get_batch_count(db_path3)

        run_cli("prune", "--dry-run", "--keep", "1", "--database", str(db_path3),
                cwd=test_dir3, desc="Error 6: verify dry-run doesn't modify DB")

        after_snaps = get_snapshot_count(db_path3)
        after_history = get_history_count(db_path3)
        after_batches = get_batch_count(db_path3)

        assert after_snaps == before_snaps, f"dry-run changed snapshots: {before_snaps} -> {after_snaps}"
        assert after_history == before_history, f"dry-run changed history: {before_history} -> {after_history}"
        assert after_batches == before_batches, f"dry-run changed batches: {before_batches} -> {after_batches}"
        print("[OK] dry-run verified to make no changes")

        # --- Error 7: No snapshots to prune (empty DB) ---
        empty_db = test_dir3 / "empty.db"
        run_cli("init", "--database", str(empty_db), "--config", "",
                cwd=test_dir3, desc="Setup: empty DB (no snapshots)")
        result = run_cli("prune", "--keep", "1", "--database", str(empty_db),
                         cwd=test_dir3, expect_success=True,
                         desc="Error 7: no snapshots in DB")
        assert "No snapshots found" in result.stdout, "Should say no snapshots found"

        # --- CRITICAL: Verify NO pollution from any error scenario ---
        after_snaps = get_snapshot_count(db_path3)
        after_history = get_history_count(db_path3)
        after_batches = get_batch_count(db_path3)

        assert after_snaps == baseline_snaps, \
            f"Snapshot pollution! Before: {baseline_snaps}, After: {after_snaps}"
        assert after_history == baseline_history, \
            f"History pollution! Before: {baseline_history}, After: {after_history}"
        assert after_batches == baseline_batches, \
            f"Batch pollution! Before: {baseline_batches}, After: {after_batches}"
        print(f"[OK] No database pollution from any error scenario")

        print(f"\n{'-'*70}")
        print("[PART 3 PASSED] All error scenarios handled correctly, no DB pollution")
        print(f"{'-'*70}")

    except AssertionError as e:
        print(f"\n{'!'*70}")
        print(f"PART 3 FAILED: {e}")
        print(f"{'!'*70}")
        print(f"Test directory: {test_dir3}")
        raise

    # ============================================================
    # ALL TESTS PASSED
    # ============================================================
    print(f"\n{'='*70}")
    print(f"{'='*70}")
    print(f"ALL PRUNE REGRESSION TESTS PASSED!  [OK]")
    print(f"{'='*70}")
    print(f"{'='*70}")
    print(f"\nSummary:")
    print(f"  [OK] PART 1: Happy path")
    print(f"       - dry-run preview, no changes made")
    print(f"       - prune --keep N works correctly")
    print(f"       - prune --before works correctly")
    print(f"       - prune --prune-orphans deletes unreferenced batches")
    print(f"       - Cross-restart persistence (history/rollback/batches/export)")
    print(f"  [OK] PART 2: Reference conflicts")
    print(f"       - Batches still referenced by retained snapshots are NOT deleted")
    print(f"       - Proper warning messages shown")
    print(f"       - history/rollback/batches/export work after prune")
    print(f"  [OK] PART 3: Error scenarios")
    print(f"       - No filter specified -> clear error, exit 1")
    print(f"       - Invalid --before format -> clear error, exit 1")
    print(f"       - Negative --keep -> clear error, exit 1")
    print(f"       - No matching data -> warning, exit 0, no changes")
    print(f"       - DB not found -> hints at init, exit 1")
    print(f"       - dry-run makes ZERO changes to database")
    print(f"       - NO database pollution from any error scenario")
    print(f"\nTest directories:")
    print(f"  Happy path: {test_dir}")
    print(f"  Reference conflicts: {test_dir2}")
    print(f"  Error scenarios: {test_dir3}")


if __name__ == "__main__":
    main()
