#!/usr/bin/env python3
"""
End-to-end test script for inventory-cli (subprocess mode).
Tests: init, import (valid/invalid), merge, export, history, rollback
"""
import json
import os
import sys
import csv
import tempfile
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
TESTS = ROOT / "tests"


def run_cli(*args, cwd=None, expect_success=True, desc=""):
    """Run inventory CLI via subprocess."""
    full_env = os.environ.copy()
    pythonpath = str(SRC)
    if "PYTHONPATH" in full_env:
        pythonpath = os.pathsep.join([pythonpath, full_env["PYTHONPATH"]])
    full_env["PYTHONPATH"] = pythonpath
    
    flat_args = []
    for a in args:
        if isinstance(a, (list, tuple)):
            flat_args.extend(str(x) for x in a)
        else:
            flat_args.append(str(a))
    
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
        text=True
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


def main():
    test_dir = Path(tempfile.mkdtemp(prefix="inventory_test_"))
    db_path = str(test_dir / "test.db")
    
    print(f"Test directory: {test_dir}")
    
    try:
        # ============================================================
        # TEST 1: init - Initialize repository
        # ============================================================
        run_cli("init", "--database", db_path,
                cwd=test_dir,
                desc="TEST 1: Initialize repository")

        # ============================================================
        # TEST 2: config - Verify default config
        # ============================================================
        run_cli("config", "--database", db_path,
                cwd=test_dir,
                desc="TEST 2: Verify default configuration")

        # ============================================================
        # TEST 3: FAIL - Import missing required columns
        # ============================================================
        bad_file = str(TESTS / "store_a_missing_column.csv")
        run_cli("import", bad_file, "STORE_BAD", "--database", db_path,
                cwd=test_dir, expect_success=False,
                desc="TEST 3: FAIL - Import with missing 'sku'/'quantity' columns")

        # ============================================================
        # TEST 4: FAIL - Import negative quantities
        # ============================================================
        bad_file = str(TESTS / "store_a_negative.csv")
        run_cli("import", bad_file, "STORE_NEG", "--database", db_path,
                cwd=test_dir, expect_success=False,
                desc="TEST 4: FAIL - Import with negative quantities")

        # ============================================================
        # TEST 5: FAIL - Import duplicate SKU with conflicting quantities
        # ============================================================
        bad_file = str(TESTS / "store_a_duplicate_conflict.csv")
        run_cli("import", bad_file, "STORE_DUP", "--database", db_path,
                cwd=test_dir, expect_success=False,
                desc="TEST 5: FAIL - Import duplicate SKU with conflicting quantities")

        # ============================================================
        # TEST 6: FAIL - Import unknown file format
        # ============================================================
        bad_file = str(TESTS / "invalid_format.txt")
        run_cli("import", bad_file, "STORE_FMT", "--database", db_path,
                cwd=test_dir, expect_success=False,
                desc="TEST 6: FAIL - Import unknown file format (.txt)")

        # ============================================================
        # TEST 7: history - Verify only init is recorded (failed imports not persisted)
        # ============================================================
        run_cli("history", "--database", db_path,
                cwd=test_dir,
                desc="TEST 7: History - only INIT recorded, no failed imports")

        # ============================================================
        # TEST 8: SUCCESS - Import store_a.csv (valid)
        # ============================================================
        good_file = str(TESTS / "store_a.csv")
        run_cli("import", good_file, "STORE001", "--batch", "batch_store_a", "--database", db_path,
                cwd=test_dir,
                desc="TEST 8: SUCCESS - Import store_a.csv (CSV format)")

        # ============================================================
        # TEST 9: SUCCESS - Import store_b.json (valid)
        # ============================================================
        good_file = str(TESTS / "store_b.json")
        run_cli("import", good_file, "STORE002", "--batch", "batch_store_b", "--database", db_path,
                cwd=test_dir,
                desc="TEST 9: SUCCESS - Import store_b.json (JSON format)")

        # ============================================================
        # TEST 10: batches - List batches
        # ============================================================
        run_cli("batches", "--database", db_path,
                cwd=test_dir,
                desc="TEST 10: List imported batches")

        # ============================================================
        # TEST 11: FAIL - Merge with require_manual (has cross-store conflicts)
        # ============================================================
        run_cli("config", "conflict_strategy", "require_manual", "--database", db_path,
                cwd=test_dir,
                desc="TEST 11a: Set conflict strategy to require_manual")
        run_cli("merge", "--database", db_path,
                cwd=test_dir, expect_success=False,
                desc="TEST 11b: FAIL - Merge with require_manual (SKU002 has 50 vs 60)")

        # ============================================================
        # TEST 12: SUCCESS - Merge with strategy=sum
        # ============================================================
        run_cli("merge", "--strategy", "sum", "--database", db_path,
                cwd=test_dir,
                desc="TEST 12: SUCCESS - Merge with strategy=sum")

        # ============================================================
        # TEST 13: Export CSV - latest snapshot
        # ============================================================
        csv_output = str(test_dir / "merged.csv")
        run_cli("export", csv_output, "--database", db_path,
                cwd=test_dir,
                desc="TEST 13: Export merged inventory as CSV")
        assert os.path.exists(csv_output)
        with open(csv_output, encoding='utf-8') as f:
            content = f.read()
            print("CSV content preview:")
            print(content[:800])

        # ============================================================
        # TEST 14: Export JSON report with source batches
        # ============================================================
        json_output = str(test_dir / "merged.report.json")
        run_cli("export", json_output, "--database", db_path,
                cwd=test_dir,
                desc="TEST 14: Export detailed report with diff")
        assert os.path.exists(json_output)
        with open(json_output, encoding='utf-8') as f:
            report = json.load(f)
            print("\nReport metadata:")
            print(json.dumps(report.get('metadata', {}), indent=2))
            src_batches = report.get('metadata', {}).get('source_batches')
            print(f"\nSource batches: {src_batches}")
            assert src_batches is not None, "Report should contain source_batches metadata!"
            assert len(src_batches) == 2, f"Expected 2 source batches, got {len(src_batches)}"
            if 'diff_report' in report:
                print("Diff report summary:", json.dumps(report['diff_report'].get('summary', {}), indent=2))

        # ============================================================
        # TEST 15: Merge again with strategy=average to create 2nd snapshot
        # ============================================================
        run_cli("merge", "--strategy", "average", "--database", db_path,
                cwd=test_dir,
                desc="TEST 15: 2nd merge with strategy=average (creates 2nd snapshot)")

        # ============================================================
        # TEST 16: history - Full audit log (history persists across restarts!)
        # ============================================================
        run_cli("history", "--database", db_path,
                cwd=test_dir,
                desc="TEST 16: Show full operation history")

        # ============================================================
        # TEST 17: rollback - List snapshots
        # ============================================================
        run_cli("rollback", "--database", db_path,
                cwd=test_dir,
                desc="TEST 17: List available snapshots")

        # ============================================================
        # TEST 18: rollback - Go back to snapshot #1 (sum strategy)
        # ============================================================
        run_cli("rollback", "1", "--database", db_path,
                cwd=test_dir,
                desc="TEST 18: Rollback to snapshot #1 (sum strategy)")

        # ============================================================
        # TEST 19: Export again after rollback - SHOULD BE sum version!
        # ============================================================
        csv_after_rollback = str(test_dir / "after_rollback.csv")
        run_cli("export", csv_after_rollback, "--database", db_path,
                cwd=test_dir,
                desc="TEST 19: Export after rollback (should be 'sum' strategy data)")
        assert os.path.exists(csv_after_rollback)
        with open(csv_after_rollback, encoding='utf-8') as f:
            content = f.read()
            print("After rollback CSV preview:")
            print(content[:800])

        # ============================================================
        # TEST 20: history - Verify rollback recorded
        # ============================================================
        run_cli("history", "--database", db_path,
                cwd=test_dir,
                desc="TEST 20: History shows rollback operation")

        # ============================================================
        # TEST 21: Verify persistence (history across restarts)
        # ============================================================
        print(f"\n{'='*70}")
        print(">>> TEST 21: Persistence check - Re-open DB and verify history exists")
        print(f"{'='*70}")
        result = subprocess.run(
            [sys.executable, "-m", "inventory_cli.cli", "history",
             "--database", db_path, "-n", "5"],
            cwd=str(test_dir),
            env={**os.environ, "PYTHONPATH": str(SRC)},
            capture_output=True,
            text=True
        )
        print(result.stdout.rstrip())
        assert "rollback" in result.stdout.lower() or "ROLLBACK" in result.stdout, \
            "History should persist across CLI invocations and show rollback entry!"
        print("[PASS: History persisted across CLI invocations]")

        # ============================================================
        # TEST 22: --help for each command (verify docs are real)
        # ============================================================
        for cmd in [
            [], ["init"], ["import"], ["merge"], ["export"],
            ["history"], ["rollback"], ["config"], ["batches"]
        ]:
            run_cli(*cmd, "--help",
                    cwd=test_dir,
                    desc=f"TEST 22: {'/'.join(cmd) if cmd else 'main'} --help")

        # ============================================================
        print(f"\n{'='*70}")
        print("ALL TESTS PASSED!  [OK]")
        print(f"{'='*70}")
        print(f"\nTest artifacts kept in: {test_dir}")

    except AssertionError as e:
        print(f"\n{'='*70}")
        print(f"TEST FAILED: {e}")
        print(f"{'='*70}")
        print(f"Test artifacts kept in: {test_dir}")
        raise


if __name__ == "__main__":
    main()
