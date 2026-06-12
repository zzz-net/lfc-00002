#!/usr/bin/env python3
"""
Regression Tests for export directory auto-creation.

Tests:
  1. Export CSV to non-existent nested directories
  2. Export JSON to non-existent nested directories
  3. Export report.json to non-existent nested directories
  4. Full README flow without pre-creating output directories

This ensures the fix in exporter.py (_ensure_parent_dir) works correctly
and users can follow README from empty directory without manual mkdir.
"""
import json
import os
import sys
import tempfile
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
TESTS = ROOT / "tests"


def run_cmd(cmd_parts, cwd, expect_success=True, desc=""):
    """Run CLI command and print output."""
    full_env = dict(os.environ)
    full_env["PYTHONPATH"] = str(SRC)
    
    print(f"\n{'='*70}")
    print(f">>> {desc}")
    print(f"CMD: {' '.join(cmd_parts)}")
    print(f"{'='*70}")
    
    result = subprocess.run(cmd_parts, cwd=str(cwd), env=full_env,
                          capture_output=True, text=True)
    
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print("STDERR:", result.stderr.rstrip())
    print(f"[exit {result.returncode}]")
    
    if expect_success:
        assert result.returncode == 0, f"Command failed: {' '.join(cmd_parts)}"
    else:
        assert result.returncode != 0, f"Command succeeded when it should have failed"
    
    return result


def step(num, desc):
    print(f"\n{'#'*70}")
    print(f"TEST {num}: {desc}")
    print(f"{'#'*70}")


def main():
    cli_prefix = [sys.executable, "-m", "inventory_cli.cli"]
    
    # ============================================================
    # TEST 1: Export CSV to non-existent nested dir
    # ============================================================
    step(1, "Export CSV to 3-level non-existent directories")
    
    test_dir1 = Path(tempfile.mkdtemp(prefix="inv_export_csv_"))
    print(f"Test directory: {test_dir1}")
    
    # Setup: init + import + merge
    run_cmd(cli_prefix + ["init", "--database", "inv.db", "--config", ""],
           cwd=test_dir1, desc="Init repo")
    
    run_cmd(cli_prefix + ["import", str(TESTS / "store_a.csv"), "STORE001",
                         "--batch", "batch_a", "--database", "inv.db"],
           cwd=test_dir1, desc="Import store_a.csv")
    
    run_cmd(cli_prefix + ["merge", "--strategy", "sum", "--database", "inv.db"],
           cwd=test_dir1, desc="Merge with sum strategy")
    
    # Export CSV to non-existent dirs - BEFORE FIX this would fail with "No such file"
    csv_path = "a/b/c/exported.csv"
    full_csv_path = test_dir1 / csv_path
    assert not full_csv_path.parent.exists(), f"Parent dir should NOT exist: {full_csv_path.parent}"
    
    run_cmd(cli_prefix + ["export", csv_path, "--database", "inv.db"],
           cwd=test_dir1, desc=f"Export CSV to {csv_path} (parent dirs don't exist)")
    
    assert full_csv_path.exists(), f"CSV should exist: {full_csv_path}"
    assert full_csv_path.parent.exists(), f"Parent dirs should be auto-created: {full_csv_path.parent}"
    print(f"[OK] Auto-created parent dirs and exported CSV to {full_csv_path}")
    
    # ============================================================
    # TEST 2: Export JSON to non-existent nested dir
    # ============================================================
    step(2, "Export JSON to 4-level non-existent directories")
    
    json_path = "x/y/z/w/exported.json"
    full_json_path = test_dir1 / json_path
    assert not full_json_path.parent.exists(), f"Parent dir should NOT exist: {full_json_path.parent}"
    
    run_cmd(cli_prefix + ["export", json_path, "--database", "inv.db"],
           cwd=test_dir1, desc=f"Export JSON to {json_path}")
    
    assert full_json_path.exists(), f"JSON should exist"
    print(f"[OK] Auto-created parent dirs and exported JSON to {full_json_path}")
    
    # ============================================================
    # TEST 3: Export report.json to non-existent nested dir
    # ============================================================
    step(3, "Export report.json to deeply nested non-existent dir")
    
    report_path = "deep/nested/path/for/report/full_report.report.json"
    full_report_path = test_dir1 / report_path
    assert not full_report_path.parent.exists(), f"Parent dir should NOT exist: {full_report_path.parent}"
    
    run_cmd(cli_prefix + ["export", report_path, "--database", "inv.db"],
           cwd=test_dir1, desc=f"Export report to {report_path}")
    
    assert full_report_path.exists(), f"Report should exist"
    
    # Verify report metadata
    with open(full_report_path, encoding='utf-8') as f:
        report = json.load(f)
    assert "source_batches" in report["metadata"], "Report should have source_batches"
    print(f"[OK] Auto-created 6 levels of parent dirs for report")
    
    # ============================================================
    # TEST 4: Verify the BEFORE-FIX behavior WOULD have failed
    # ============================================================
    step(4, "Regression: Verify WITHOUT fix, this would fail (sanity check)")
    
    # Try to open a file in non-existent dir with plain Python (simulating old behavior)
    bad_path = test_dir1 / "does/not/exist/file.txt"
    try:
        with open(bad_path, 'w') as f:
            f.write("test")
        assert False, "Should have failed!"
    except FileNotFoundError:
        print(f"[OK] Confirmed: plain open() fails without parent dir - our fix is necessary")
    
    # ============================================================
    # TEST 5: FULL README FLOW from empty directory - NO manual mkdir
    # ============================================================
    step(5, "FULL README FLOW from EMPTY directory - no manual mkdir anywhere")
    
    test_dir2 = Path(tempfile.mkdtemp(prefix="inv_readme_full_"))
    print(f"Full flow test directory: {test_dir2}")
    
    cli = [sys.executable, "-m", "inventory_cli.cli"]
    db = ["--database", "./data/stores.db"]
    
    # STEP 1: init - README: python -m inventory_cli.cli init --database ./data/stores.db
    # This ALSO tests the earlier fix for auto-creating DB parent dir!
    run_cmd(cli + ["init"] + db + ["--force"],
           cwd=test_dir2,
           desc="README STEP 1: init with ./data/stores.db (auto-creates ./data/)")
    
    # Verify data dir was created (from earlier fix)
    assert (test_dir2 / "data" / "stores.db").exists()
    
    # Create data files using EXACT README content
    store_a_csv = """sku,quantity
SKU001,100
SKU002,50
SKU003,75
SKU004,200
"""
    store_b_json = """[
  {"sku": "SKU001", "quantity": 100},
  {"sku": "SKU002", "quantity": 60},
  {"sku": "SKU003", "quantity": 75},
  {"sku": "SKU005", "quantity": 150}
]
"""
    (test_dir2 / "store_a.csv").write_text(store_a_csv, encoding='utf-8')
    (test_dir2 / "store_b.json").write_text(store_b_json, encoding='utf-8')
    
    # Copy config_sum.json
    import shutil
    shutil.copy(str(TESTS / "config_sum.json"), str(test_dir2 / "config_sum.json"))
    
    # STEP 2: import - README: import store_a.csv STORE001 --batch batch_store_a
    run_cmd(cli + ["import", "store_a.csv", "STORE001",
                  "--batch", "batch_store_a"] + db,
           cwd=test_dir2,
           desc="README STEP 2: Import store_a.csv")
    
    run_cmd(cli + ["import", "store_b.json", "STORE002",
                  "--batch", "batch_store_b",
                  "--config", "config_sum.json"] + db,
           cwd=test_dir2,
           desc="README STEP 3: Import store_b.json")
    
    # STEP 3: batches
    run_cmd(cli + ["batches"] + db,
           cwd=test_dir2,
           desc="README STEP 4: List batches")
    
    # STEP 4: merge require_manual (should fail)
    run_cmd(cli + ["config", "conflict_strategy", "require_manual"] + db,
           cwd=test_dir2,
           desc="README STEP 5: Set strategy to require_manual")
    
    # Remove default config to force require_manual
    if (test_dir2 / "inventory.config.json").exists():
        (test_dir2 / "inventory.config.json").unlink()
    
    run_cmd(cli + ["merge"] + db,
           cwd=test_dir2, expect_success=False,
           desc="README STEP 6: merge require_manual - should FAIL (SKU002 conflict)")
    
    # STEP 5: merge with sum via config file
    run_cmd(cli + ["merge", "--config", "config_sum.json"] + db,
           cwd=test_dir2,
           desc="README STEP 7: merge with config_sum.json")
    
    # STEP 6: Export - README uses output/ directory!
    # BEFORE FIX: this would fail because output/ doesn't exist!
    # AFTER FIX: auto-creates output/ directory
    
    # README: python -m inventory_cli.cli export output/merged.csv
    run_cmd(cli + ["export", "output/merged.csv"] + db,
           cwd=test_dir2,
           desc="README STEP 8a: Export CSV to output/merged.csv (auto-creates output/)")
    assert (test_dir2 / "output" / "merged.csv").exists()
    print(f"[OK] Auto-created output/ directory for CSV export")
    
    # README: python -m inventory_cli.cli export output/merged.json
    run_cmd(cli + ["export", "output/merged.json"] + db,
           cwd=test_dir2,
           desc="README STEP 8b: Export JSON to output/merged.json")
    assert (test_dir2 / "output" / "merged.json").exists()
    
    # README: python -m inventory_cli.cli export output/merged.report.json
    run_cmd(cli + ["export", "output/merged.report.json"] + db,
           cwd=test_dir2,
           desc="README STEP 8c: Export report to output/merged.report.json")
    assert (test_dir2 / "output" / "merged.report.json").exists()
    
    # STEP 7: history - README: python -m inventory_cli.cli history -n 50
    run_cmd(cli + ["history", "-n", "50"] + db,
           cwd=test_dir2,
           desc="README STEP 9: Show history")
    
    # STEP 8: rollback list
    run_cmd(cli + ["rollback"] + db,
           cwd=test_dir2,
           desc="README STEP 10: List snapshots")
    
    # STEP 9: rollback 1
    run_cmd(cli + ["rollback", "1"] + db,
           cwd=test_dir2,
           desc="README STEP 11: Rollback to snapshot #1")
    
    # STEP 10: export after rollback - README: export output/after_rollback.csv
    run_cmd(cli + ["export", "output/after_rollback.csv"] + db,
           cwd=test_dir2,
           desc="README STEP 12: Export after rollback to output/after_rollback.csv")
    assert (test_dir2 / "output" / "after_rollback.csv").exists()
    
    # Verify after_rollback.csv contains source batches metadata
    csv_content = (test_dir2 / "output" / "after_rollback.csv").read_text(encoding='utf-8')
    assert "Source Batches" in csv_content, "CSV should have source batches metadata"
    
    # ============================================================
    # ALL TESTS PASSED
    # ============================================================
    print(f"\n{'='*70}")
    print(f"{'='*70}")
    print(f"ALL EXPORT DIRECTORY TESTS PASSED!  [OK]")
    print(f"{'='*70}")
    print(f"{'='*70}")
    print(f"\nSummary:")
    print(f"  [OK] Export CSV auto-creates parent dirs")
    print(f"  [OK] Export JSON auto-creates parent dirs")
    print(f"  [OK] Export report auto-creates parent dirs")
    print(f"  [OK] Full README flow works from empty directory (no manual mkdir)")
    print(f"  [OK] output/ directory auto-created as per README")
    print(f"\nTest directories:")
    print(f"  CSV/JSON/report test: {test_dir1}")
    print(f"  Full README flow: {test_dir2}")


if __name__ == "__main__":
    main()
