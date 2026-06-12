#!/usr/bin/env python3
"""
Regression Tests for README compliance.

Tests:
  1. Auto-create parent directory for database file
  2. README example CSV/JSON can be imported successfully
  3. README example commands work correctly

This is NOT a happy path test - it reproduces the exact issues from the bug report:
  - Bug 1: init --database ./data/stores.db fails if ./data/ doesn't exist
  - Bug 2: README store_b.json example had {"sku": "SKU005", "300"} which failed import
"""
import json
import os
import sys
import tempfile
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
TESTS = ROOT / "tests"


def run_cli(*args, cwd=None, expect_success=True, desc=""):
    """Run inventory CLI via subprocess, exactly as user would from command line."""
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
    
    result = subprocess.run(cmd, cwd=cwd, env=full_env, capture_output=True, text=True)
    
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


def write_temp_file(dir_path: Path, filename: str, content: str) -> Path:
    """Write a temp file with given content."""
    file_path = dir_path / filename
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return file_path


def main():
    # ============================================================
    # TEST 1: Bug 1 regression - auto-create parent directory for database
    # ============================================================
    print(f"\n{'#'*70}")
    print("TEST 1: Regression - auto-create parent directory for --database ./data/nonexistent/stores.db")
    print("BUG REPRO: init --database ./data/stores.db used to fail with 'unable to open database file'")
    print("FIX: db.py connect() now creates parent dirs with os.makedirs(exist_ok=True)")
    print(f"{'#'*70}")
    
    test_dir = Path(tempfile.mkdtemp(prefix="inv_readme_test_"))
    os.chdir(test_dir)
    print(f"Test directory: {test_dir}")
    
    # BEFORE FIX: This would fail because ./data/nonexistent/ doesn't exist
    db_path = "./data/nonexistent_dir/stores.db"
    db_abs_path = test_dir / "data" / "nonexistent_dir" / "stores.db"
    
    assert not db_abs_path.parent.exists(), f"Parent dir should NOT exist before test: {db_abs_path.parent}"
    
    run_cli("init", "--database", db_path,
            cwd=test_dir,
            desc="TEST 1a: init with nested non-existent parent dirs")
    
    assert db_abs_path.parent.exists(), f"Parent dir SHOULD be auto-created: {db_abs_path.parent}"
    assert db_abs_path.exists(), f"Database file SHOULD exist: {db_abs_path}"
    print(f"[OK] Auto-created parent dir: {db_abs_path.parent}")
    
    # Test that even deeper nesting works
    db_path2 = "./a/b/c/d/e/f/deep.db"
    run_cli("init", "--database", db_path2, "--config", "",
            cwd=test_dir,
            desc="TEST 1b: init with 6 levels of non-existent parent dirs")
    assert (test_dir / "a/b/c/d/e/f/deep.db").exists(), "Deep nested db should exist"
    print(f"[OK] Auto-created 6 levels of parent dirs")
    
    # ============================================================
    # TEST 2: Bug 2 regression - README example data can be imported
    # ============================================================
    print(f"\n{'#'*70}")
    print("TEST 2: Regression - README example CSV/JSON imports correctly")
    print("BUG REPRO: README store_b.json had {'sku': 'SKU005', '300'} missing 'quantity' key")
    print("FIX: README example corrected to {'sku': 'SKU005', 'quantity': 150}")
    print(f"{'#'*70}")
    
    test_dir2 = Path(tempfile.mkdtemp(prefix="inv_readme_data_test_"))
    os.chdir(test_dir2)
    print(f"Data test directory: {test_dir2}")
    
    # Write EXACTLY the examples from README - no "happy path" modifications!
    readme_csv = """sku,quantity
SKU001,100
SKU002,50
SKU003,75
SKU004,200
"""
    
    readme_json = """[
  {"sku": "SKU001", "quantity": 100},
  {"sku": "SKU002", "quantity": 60},
  {"sku": "SKU003", "quantity": 75},
  {"sku": "SKU005", "quantity": 150}
]
"""
    
    store_a_csv = write_temp_file(test_dir2, "store_a.csv", readme_csv)
    store_b_json = write_temp_file(test_dir2, "store_b.json", readme_json)
    
    db_path3 = test_dir2 / "inv.db"
    
    run_cli("init", "--database", str(db_path3), "--config", "",
            cwd=test_dir2,
            desc="TEST 2a: init for import test")
    
    # Import README's exact store_a.csv example
    run_cli("import", str(store_a_csv), "STORE001",
            "--batch", "batch_store_a",
            "--database", str(db_path3),
            cwd=test_dir2,
            desc="TEST 2b: Import README's exact store_a.csv example")
    
    # Import README's exact store_b.json example
    run_cli("import", str(store_b_json), "STORE002",
            "--batch", "batch_store_b",
            "--database", str(db_path3),
            cwd=test_dir2,
            desc="TEST 2c: Import README's exact store_b.json example")
    
    # Verify records count
    import sqlite3
    conn = sqlite3.connect(str(db_path3))
    cur = conn.execute("SELECT COUNT(*) FROM inventory")
    count = cur.fetchone()[0]
    conn.close()
    assert count == 8, f"Expected 8 records (4+4), got {count}"
    print(f"[OK] Successfully imported 8 records from README examples")
    
    # Verify SKU005 has quantity=150
    import sqlite3
    conn = sqlite3.connect(str(db_path3))
    cur = conn.execute(
        "SELECT quantity FROM inventory WHERE sku = 'SKU005' AND batch_id = 'batch_store_b'"
    )
    row = cur.fetchone()
    conn.close()
    assert row is not None, "SKU005 should exist"
    assert row[0] == 150, f"SKU005 should have quantity=150, got {row[0]}"
    print(f"[OK] SKU005 quantity = 150 (matches README example)")
    
    # ============================================================
    # TEST 3: Verify the BAD example from the original bug report WOULD fail
    # ============================================================
    print(f"\n{'#'*70}")
    print("TEST 3: Verify the original BAD example from README WOULD fail")
    print("This ensures our fix is correct - the old example SHOULD have failed")
    print(f"{'#'*70}")
    
    bad_json_content = """[
  {"sku": "SKU001", "quantity": 100},
  {"sku": "SKU002", "quantity": 60},
  {"sku": "SKU003", "quantity": 75},
  {"sku": "SKU005", "300"}
]
"""
    bad_json = write_temp_file(test_dir2, "bad_store_b.json", bad_json_content)
    
    # This should FAIL - it's the original buggy example
    result = run_cli("import", str(bad_json), "STORE003",
                    "--batch", "batch_bad",
                    "--database", str(db_path3),
                    cwd=test_dir2, expect_success=False,
                    desc="TEST 3: Original BAD example from bug report SHOULD fail")
    
    # Verify no pollution - should still have 8 records, not 9+
    import sqlite3
    conn = sqlite3.connect(str(db_path3))
    cur = conn.execute("SELECT COUNT(*) FROM inventory")
    count_after = cur.fetchone()[0]
    conn.close()
    assert count_after == 8, f"Database should NOT be polluted! Expected 8, got {count_after}"
    print(f"[OK] Bad import did not pollute database - still {count_after} records")
    
    # ============================================================
    print(f"\n{'='*70}")
    print("ALL README REGRESSION TESTS PASSED!  [OK]")
    print(f"{'='*70}")
    print(f"\nTest directories kept for inspection:")
    print(f"  Directory test 1: {test_dir}")
    print(f"  Directory test 2: {test_dir2}")


if __name__ == "__main__":
    main()
