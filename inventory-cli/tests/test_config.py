#!/usr/bin/env python3
"""
Configuration Regression Tests for inventory-cli.
Tests:
  - Config file loading (valid / invalid)
  - Priority: CLI > config file > SQLite > default
  - require_manual strategy correctly blocks conflicts
  - sum strategy via config file works
  - Bad config does NOT pollute database/snapshots
  - Backward compatibility (no --config flag works)
  - init generates valid example config
"""
import json
import os
import sys
import tempfile
import shutil
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
    
    flat_args = [str(a) for a in args]
    
    cmd = [sys.executable, "-m", "inventory_cli.cli"] + flat_args
    
    print(f"\n{'='*70}")
    print(f">>> {desc}")
    print(f"CMD: inventory {' '.join(flat_args)}")
    print(f"{'='*70}")
    
    result = subprocess_run(cmd, cwd=cwd, env=full_env)
    
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


def subprocess_run(cmd, cwd=None, env=None):
    """Wrapper for subprocess.run."""
    import subprocess
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


def get_snapshot_count(db_path: Path) -> int:
    """Count snapshots in database."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT COUNT(*) FROM snapshots")
        return cur.fetchone()[0]
    finally:
        conn.close()


def get_history_count(db_path: Path) -> int:
    """Count history entries."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT COUNT(*) FROM history")
        return cur.fetchone()[0]
    finally:
        conn.close()


def assert_file_not_polluted(db_path: Path, expected_snapshots: int, expected_history: int):
    """Verify that failed operations didn't create snapshots or history."""
    actual_snapshots = get_snapshot_count(db_path)
    actual_history = get_history_count(db_path)
    assert actual_snapshots == expected_snapshots, \
        f"Snapshot pollution! Expected {expected_snapshots}, got {actual_snapshots}"
    assert actual_history == expected_history, \
        f"History pollution! Expected {expected_history}, got {actual_history}"
    print(f"[OK] Database state unchanged: snapshots={actual_snapshots}, history={actual_history}")


def main():
    test_dir = Path(tempfile.mkdtemp(prefix="inv_config_test_"))
    db_path = test_dir / "test.db"
    os.chdir(test_dir)
    
    print(f"Test directory: {test_dir}")
    
    try:
        # ============================================================
        # TEST 1: init generates valid example config file
        # ============================================================
        run_cli("init", "--database", str(db_path),
                cwd=test_dir, desc="TEST 1: init generates config file")
        
        config_file = test_dir / "inventory.config.json"
        assert config_file.exists(), "init should generate inventory.config.json"
        with open(config_file, encoding='utf-8') as f:
            config = json.load(f)
        assert 'conflict_strategy' in config
        assert config['conflict_strategy'] == 'require_manual'
        assert 'validation' in config
        print("[OK] Generated config file is valid")
        
        init_snapshots = get_snapshot_count(db_path)  # 0
        init_history = get_history_count(db_path)      # 1 (init)
        print(f"Initial state: snapshots={init_snapshots}, history={init_history}")
        
        # ============================================================
        # TEST 2: Import store_a and store_b (valid data)
        # ============================================================
        run_cli("import", str(TESTS / "store_a.csv"), "STORE001",
                "--batch", "batch_store_a", "--database", str(db_path),
                cwd=test_dir, desc="TEST 2a: Import store_a.csv")
        run_cli("import", str(TESTS / "store_b.json"), "STORE002",
                "--batch", "batch_store_b", "--database", str(db_path),
                cwd=test_dir, desc="TEST 2b: Import store_b.json")
        
        after_import_history = get_history_count(db_path)  # init + 2 imports = 3
        
        # ============================================================
        # TEST 3: require_manual (via config file) blocks cross-store conflicts
        # ============================================================
        before_snapshots = get_snapshot_count(db_path)
        before_history = get_history_count(db_path)
        
        # SKU002 has 50 (STORE001) vs 60 (STORE002) -> require_manual should fail
        run_cli("merge", "--config", str(TESTS / "config_require_manual.json"),
                "--database", str(db_path), cwd=test_dir, expect_success=False,
                desc="TEST 3: require_manual + conflicts = FAIL, no pollution")
        
        # Verify no pollution
        assert_file_not_polluted(db_path, before_snapshots, before_history)
        assert before_snapshots == 0, "Should have 0 snapshots before any successful merge"
        
        # ============================================================
        # TEST 4: sum strategy via config file works, creates snapshot
        # ============================================================
        result = run_cli("merge", "--config", str(TESTS / "config_sum.json"),
                        "--database", str(db_path), cwd=test_dir,
                        desc="TEST 4: sum strategy via config file = SUCCESS")
        assert "Loaded config from" in result.stdout, "Should indicate config file loaded"
        assert "conflict_strategy" in result.stdout, "Should show effective config"
        assert "config_file" in result.stdout, "Should indicate strategy comes from config_file"
        
        after_sum_snapshots = get_snapshot_count(db_path)
        assert after_sum_snapshots == 1, "Should have 1 snapshot after successful merge"
        
        # Export and verify source_batches present in report
        report_path = test_dir / "sum_report.report.json"
        run_cli("export", str(report_path), "--database", str(db_path), cwd=test_dir,
                desc="TEST 4b: Export sum report")
        with open(report_path, encoding='utf-8') as f:
            report = json.load(f)
        assert 'source_batches' in report['metadata'], "Report should contain source_batches"
        assert len(report['metadata']['source_batches']) >= 2, "Should have at least 2 source batches"
        assert 'batch_store_a' in report['metadata']['source_batches']
        assert 'batch_store_b' in report['metadata']['source_batches']
        assert report['metadata']['merge_strategy'] == 'sum'
        print(f"[OK] Report metadata: {json.dumps(report['metadata'], indent=2)}")
        
        # ============================================================
        # TEST 5: CLI parameter takes priority over config file
        # ============================================================
        # Config says 'sum', but CLI says 'average' -> CLI wins
        result = run_cli("merge", "--config", str(TESTS / "config_sum.json"),
                        "--strategy", "average", "--database", str(db_path),
                        cwd=test_dir,
                        desc="TEST 5: --strategy average takes priority over config file sum")
        assert "cli_parameter" in result.stdout, "Should indicate source is cli_parameter"
        
        after_avg_snapshots = get_snapshot_count(db_path)
        assert after_avg_snapshots == 2, "Should have 2 snapshots now"
        
        # ============================================================
        # TEST 6: Bad configs fail cleanly, no pollution
        # ============================================================
        before_snapshots = get_snapshot_count(db_path)
        before_history = get_history_count(db_path)
        
        bad_configs = [
            (TESTS / "config_bad_json.json", "bad JSON syntax"),
            (TESTS / "config_invalid_strategy.json", "invalid strategy name"),
            (TESTS / "config_malformed_structure.json", "array instead of object"),
        ]
        
        for bad_config, description in bad_configs:
            run_cli("merge", "--config", str(bad_config), "--database", str(db_path),
                    cwd=test_dir, expect_success=False,
                    desc=f"TEST 6a: FAIL with {description}")
            assert_file_not_polluted(db_path, before_snapshots, before_history)
            print(f"[OK] {description} - no pollution")
        
        # Also test bad config for import
        run_cli("import", str(TESTS / "store_a.csv"), "STORE003",
                "--config", str(TESTS / "config_bad_json.json"),
                "--database", str(db_path), cwd=test_dir, expect_success=False,
                desc="TEST 6b: import with bad config fails, no pollution")
        assert_file_not_polluted(db_path, before_snapshots, before_history)
        
        # ============================================================
        # TEST 7: Backward compatibility - no --config flag works
        # ============================================================
        # First set SQLite config to require_manual
        run_cli("config", "conflict_strategy", "require_manual",
                "--database", str(db_path), cwd=test_dir,
                desc="TEST 7a: Set SQLite config to require_manual")
        
        # Remove any default config file to force SQLite config usage
        if os.path.exists(config_file):
            os.remove(config_file)
        
        # Without --config, should use SQLite config (require_manual) -> fail due to conflicts
        run_cli("merge", "--database", str(db_path), cwd=test_dir, expect_success=False,
                desc="TEST 7b: merge without --config uses SQLite config (require_manual) -> FAIL")
        
        # Now set SQLite config to 'first', merge should succeed
        run_cli("config", "conflict_strategy", "first",
                "--database", str(db_path), cwd=test_dir,
                desc="TEST 7c: Set SQLite config to first")
        
        result = run_cli("merge", "--database", str(db_path), cwd=test_dir,
                        desc="TEST 7d: merge without --config uses SQLite 'first' -> SUCCESS")
        assert "sqlite_db" in result.stdout, "Should indicate strategy comes from sqlite_db"
        
        # ============================================================
        # TEST 8: Default config file auto-detected
        # ============================================================
        # Generate a new config file in test_dir with strategy 'last'
        test_config = {
            "conflict_strategy": "last",
            "validation": {"negative_quantities": True}
        }
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(test_config, f)
        
        # Without --config, should auto-detect ./inventory.config.json (last)
        result = run_cli("merge", "--database", str(db_path), cwd=test_dir,
                        desc="TEST 8: auto-detect ./inventory.config.json")
        assert "Loaded config from default" in result.stdout or "inventory.config.json" in result.stdout
        assert "config_file" in result.stdout, "Should indicate strategy comes from config_file"
        
        # Verify strategy in snapshot is 'last'
        # ============================================================
        # TEST 9: Rollback then export = back to previous version
        # ============================================================
        # Get number of snapshots before rollback
        before_rollback_snapshots = get_snapshot_count(db_path)
        
        # Rollback to snapshot #1 (sum strategy)
        run_cli("rollback", "1", "--database", str(db_path), cwd=test_dir,
                desc="TEST 9a: Rollback to snapshot #1")
        
        after_rollback_snapshots = get_snapshot_count(db_path)
        assert after_rollback_snapshots == before_rollback_snapshots + 1, \
            "Rollback should create a NEW snapshot (no data loss)"
        
        # Export after rollback - should be sum strategy version
        rollback_export = test_dir / "after_rollback.csv"
        run_cli("export", str(rollback_export), "--database", str(db_path), cwd=test_dir,
                desc="TEST 9b: Export after rollback")
        with open(rollback_export, encoding='utf-8') as f:
            content = f.read()
        assert "Source Batches" in content, "CSV should have source batches metadata"
        print(f"[OK] Export after rollback contains source batches")
        
        # ============================================================
        # TEST 10: History persists across CLI invocations
        # ============================================================
        result = subprocess_run(
            [sys.executable, "-m", "inventory_cli.cli", "history",
             "--database", str(db_path), "-n", "100"],
            cwd=str(test_dir),
            env={**os.environ, "PYTHONPATH": str(SRC)}
        )
        history_out = result.stdout
        assert "rollback" in history_out.lower() or "ROLLBACK" in history_out
        assert "merge" in history_out.lower() or "MERGE" in history_out
        assert "import" in history_out.lower() or "IMPORT" in history_out
        assert "init" in history_out.lower() or "INIT" in history_out
        print("[OK] History persists across CLI invocations")
        
        # ============================================================
        print(f"\n{'='*70}")
        print("ALL CONFIG REGRESSION TESTS PASSED!  [OK]")
        print(f"{'='*70}")
        
    except AssertionError as e:
        print(f"\n{'='*70}")
        print(f"TEST FAILED: {e}")
        print(f"{'='*70}")
        print(f"Test directory kept: {test_dir}")
        raise
    finally:
        print(f"\nTest directory: {test_dir}")
        # shutil.rmtree(test_dir)


if __name__ == "__main__":
    main()
