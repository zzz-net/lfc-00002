#!/usr/bin/env python3
"""
Documentation consistency test for prune command.

Verifies that README documentation matches actual CLI behavior:
  - README mentions prune command and all parameters
  - prune --help output contains all parameters documented in README
  - "常见组合速查"表格里的每条命令都能实际运行（参数合法）
  - 错误场景描述与实际 CLI 输出一致
  - dry-run 输出格式符合 README 描述

This is a regression test to catch drift between docs and implementation.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
README = ROOT / "README.md"
TESTS = ROOT / "tests"


def run_cli(*args, cwd=None):
    """Run inventory CLI via subprocess, return (returncode, stdout, stderr)."""
    full_env = __import__("os").environ.copy()
    pythonpath = str(SRC)
    if "PYTHONPATH" in full_env:
        pythonpath = pythonpath + __import__("os").pathsep + full_env["PYTHONPATH"]
    full_env["PYTHONPATH"] = pythonpath

    cmd = [sys.executable, "-m", "inventory_cli.cli"] + list(args)
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else str(ROOT),
        env=full_env,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def read_readme() -> str:
    """Read README content."""
    return README.read_text(encoding="utf-8")


def test_readme_mentions_prune():
    """README should have a prune section."""
    content = read_readme()
    assert "prune" in content.lower(), "README should mention 'prune'"
    assert "历史清理" in content or "历史数据清理" in content, \
        "README should have prune/历史清理 section"
    assert "--dry-run" in content, "README should mention --dry-run"
    assert "--keep" in content, "README should mention --keep"
    assert "--before" in content, "README should mention --before"
    assert "--prune-orphans" in content, "README should mention --prune-orphans"
    print("  [OK] README mentions prune and all parameters")


def test_cli_help_matches_readme():
    """prune --help should list all parameters documented in README."""
    rc, stdout, stderr = run_cli("prune", "--help")

    # --help should succeed
    assert rc == 0, f"prune --help should exit 0"
    help_text = stdout + stderr

    # All documented parameters should appear in help
    for param in ["--before", "--keep", "--prune-orphans", "--dry-run", "--database"]:
        assert param in help_text, f"CLI help should contain {param}"

    # Help should describe purpose
    assert "clean" in help_text.lower() or "prune" in help_text.lower(), \
        "Help should describe what prune does"

    print("  [OK] CLI --help contains all documented parameters")


def test_common_combos_are_valid():
    """Each command in the '常见组合速查' table should be valid (参数合法).

    We test by running with --dry-run where applicable and a temp DB,
    or by checking that invalid-parameter errors match expectations.
    """
    content = read_readme()

    # Find the "prune 常见组合速查" section heading (may be in Chinese)
    has_section = (
        "prune" in content.lower() and
        ("common" in content.lower() or "\xe5\xb8\xb8" in content.encode('utf-8').decode('utf-8') or
         "速查" in content or "组合" in content or
         # fallback: check for multiple prune command examples with concrete args
         len(re.findall(r"inventory prune --", content)) >= 3)
    )
    assert has_section, "README should have prune common combos/examples section"

    # Extract all `inventory prune ...` commands from the README
    # (focus on common combos: ones with --dry-run, --keep, --before patterns)
    all_prune_cmds = re.findall(r"`inventory prune ([^`]+)`", content)
    # Filter to get the "common combo" style commands (not the basic signature)
    # Common combos have specific arguments like --keep, --before, --dry-run, --prune-orphans
    cmds = [c for c in all_prune_cmds if any(
        kw in c for kw in ["--keep", "--before", "--dry-run", "--prune-orphans"]
    )]
    assert len(cmds) >= 4, f"Should have at least 4 common combos, found {len(cmds)}: {cmds}"
    print(f"  Found {len(cmds)} prune example commands in README")

    # Create a temp DB with some data so we can test real commands
    test_dir = Path(tempfile.mkdtemp(prefix="inv_prune_docs_"))
    db_path = test_dir / "test.db"

    # init + import + merge to create snapshots
    rc, _, _ = run_cli("init", "--database", str(db_path),
                       "--config", str(TESTS / "config_good.json"))
    assert rc == 0, "init should succeed"

    rc, _, _ = run_cli("import", str(TESTS / "store_a.csv"), "STORE001",
                        "--batch", "batch_a", "--database", str(db_path))
    assert rc == 0, "import should succeed"

    rc, _, _ = run_cli("import", str(TESTS / "store_b.json"), "STORE002",
                        "--batch", "batch_b", "--database", str(db_path))
    assert rc == 0, "import should succeed"

    for i, strategy in enumerate(["sum", "average", "first"]):
        rc, _, _ = run_cli("merge", "--strategy", strategy, "--database", str(db_path))
        assert rc == 0, f"merge #{i+1} should succeed"

    # Test each common combo
    print(f"  Testing {len(cmds)} common combos from README...")
    for i, cmd_args_str in enumerate(cmds):
        # Split the args, add --database and possibly --dry-run if not there
        args = cmd_args_str.split()

        # For destructive commands (not dry-run), we add --dry-run to be safe
        has_dry_run = "--dry-run" in args
        full_args = ["prune"] + args
        if not any(a.startswith("--database") for a in full_args):
            full_args.extend(["--database", str(db_path)])

        # If it's a destructive command (keep 0, no dry-run), skip actual execution
        # Just check that --help-style validation works
        if "0" in args and "--keep" in args and not has_dry_run:
            # This is "清空所有快照", it's destructive but valid syntax
            # Verify it doesn't crash by checking with a non-existent empty DB would error
            print(f"    [{i+1}] skipping destructive command (keep 0) - syntax only check via dry-run equivalent")
            # Test with --dry-run flag added to verify param parsing
            test_args = ["prune", "--dry-run"] + args + ["--database", str(db_path)]
            rc, stdout, stderr = run_cli(*test_args)
            assert rc == 0, f"Command should be valid: inventory prune {cmd_args_str} (with --dry-run)"
            continue

        rc, stdout, stderr = run_cli(*full_args)

        # Commands with --dry-run should succeed (exit 0)
        if has_dry_run:
            assert rc == 0, \
                f"Common combo should succeed (exit 0): inventory prune {cmd_args_str}\n" \
                f"stdout: {stdout}\nstderr: {stderr}"
            # Verify it actually shows "DRY RUN"
            assert "DRY RUN" in stdout or "dry-run" in stdout.lower(), \
                f"Dry-run output should mention DRY RUN: {cmd_args_str}"
        else:
            # Non-dry-run commands: we expect them to succeed too (we have data)
            # But since they modify data, let's just verify they don't crash with arg errors
            # (they'll modify data which is fine since we're in a temp dir)
            assert rc == 0, \
                f"Common combo should succeed (exit 0): inventory prune {cmd_args_str}\n" \
                f"stdout: {stdout}\nstderr: {stderr}"

        print(f"    [{i+1}] OK: inventory prune {cmd_args_str}")

    print("  [OK] All common combos from README are valid commands")


def test_error_scenarios_match_readme():
    """Error scenarios documented in README should match actual CLI behavior."""
    test_dir = Path(tempfile.mkdtemp(prefix="inv_prune_errdoc_"))
    db_path = test_dir / "test.db"

    # Setup a valid DB with snapshots
    run_cli("init", "--database", str(db_path),
            "--config", str(TESTS / "config_good.json"))
    run_cli("import", str(TESTS / "store_a.csv"), "STORE001",
            "--batch", "batch_a", "--database", str(db_path))
    run_cli("merge", "--strategy", "sum", "--database", str(db_path))

    scenarios = [
        # (description, args, expected_exit_code, expected_keywords_in_output)
        ("未指定 --before/--keep",
         ["prune", "--database", str(db_path)],
         1, ["At least one", "--before", "--keep"]),
        ("--before 时间格式非法",
         ["prune", "--before", "not-a-date", "--database", str(db_path)],
         1, ["Invalid", "ISO"]),
        ("--keep 为负数",
         ["prune", "--keep", "-5", "--database", str(db_path)],
         1, ["non-negative"]),
    ]

    print(f"  Testing {len(scenarios)} error scenarios...")
    for i, (desc, args, expected_rc, keywords) in enumerate(scenarios):
        rc, stdout, stderr = run_cli(*args)
        output = stdout + stderr

        assert rc == expected_rc, \
            f"Error scenario '{desc}' should exit {expected_rc}, got {rc}\nOutput: {output}"

        for kw in keywords:
            # Check that keywords appear in output - but we need to adjust for typer's way of saying things
            kw_lower = kw.lower()
            output_lower = output.lower()
            assert kw_lower in output_lower, \
                f"Error scenario '{desc}': output should contain '{kw}'\nOutput: {output}"

        print(f"    [{i+1}] OK: {desc}")

    print("  [OK] Error scenarios match README documentation")


def test_dry_run_format_matches_readme():
    """dry-run output should match the format described in README."""
    test_dir = Path(tempfile.mkdtemp(prefix="inv_prune_dryfmt_"))
    db_path = test_dir / "test.db"

    # Setup: 2 snapshots
    run_cli("init", "--database", str(db_path),
            "--config", str(TESTS / "config_good.json"))
    run_cli("import", str(TESTS / "store_a.csv"), "STORE001",
            "--batch", "batch_a", "--database", str(db_path))
    run_cli("import", str(TESTS / "store_b.json"), "STORE002",
            "--batch", "batch_b", "--database", str(db_path))
    run_cli("merge", "--strategy", "sum", "--database", str(db_path))
    run_cli("merge", "--strategy", "average", "--database", str(db_path))

    # Test dry-run without --prune-orphans
    rc, stdout, _ = run_cli("prune", "--dry-run", "--keep", "1", "--database", str(db_path))
    assert rc == 0

    # Should have DRY RUN header
    assert "DRY RUN" in stdout
    # Should show snapshot table with ID / Created At / Batch ID / Records
    assert "ID" in stdout
    assert "Created At" in stdout
    assert "Batch ID" in stdout
    assert "Records" in stdout
    # Should have Summary
    assert "Summary" in stdout or "summary" in stdout.lower()
    # Should mention removing --dry-run
    assert "Remove --dry-run" in stdout

    # Without --prune-orphans: should NOT show batch deletion info
    # (no "Batches to delete" section)
    assert "Batches to delete" not in stdout, \
        "Without --prune-orphans, dry-run should not show batches section"

    # Test dry-run WITH --prune-orphans
    rc, stdout_orphans, _ = run_cli("prune", "--dry-run", "--keep", "1",
                               "--prune-orphans", "--database", str(db_path))
    assert rc == 0

    # With --prune-orphans: should show batch info
    assert "Batches to delete" in stdout_orphans, \
        "With --prune-orphans, dry-run should show batches section"

    print("  [OK] dry-run output format matches README description")


def test_prune_shows_in_history_command():
    """After a real prune, it should appear in history (as README says)."""
    test_dir = Path(tempfile.mkdtemp(prefix="inv_prune_histdoc_"))
    db_path = test_dir / "test.db"

    # Setup
    run_cli("init", "--database", str(db_path),
            "--config", str(TESTS / "config_good.json"))
    run_cli("import", str(TESTS / "store_a.csv"), "STORE001",
            "--batch", "batch_a", "--database", str(db_path))
    run_cli("merge", "--strategy", "sum", "--database", str(db_path))
    run_cli("merge", "--strategy", "average", "--database", str(db_path))

    # Do a real prune
    rc, _, _ = run_cli("prune", "--keep", "1", "--database", str(db_path))
    assert rc == 0

    # Check history shows prune
    rc, stdout, _ = run_cli("history", "--database", str(db_path))
    assert rc == 0
    assert "prune" in stdout.lower(), \
        "prune operation should appear in history output (as README says)"

    # Check audit-log can filter by prune type
    rc, stdout_csv, _ = run_cli(
        "audit-log", str(test_dir / "audit.csv"),
        "--type", "prune", "--database", str(db_path)
    )
    assert rc == 0
    csv_path = test_dir / "audit.csv"
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8-sig")
    assert "prune" in content.lower(), \
        "prune should be filterable in audit-log (type filter should include prune)"

    print("  [OK] prune appears in history and audit-log as documented")


def main():
    print(f"\n{'='*70}")
    print("Running prune documentation consistency tests")
    print(f"{'='*70}")

    tests = [
        ("README mentions prune", test_readme_mentions_prune),
        ("CLI --help matches README", test_cli_help_matches_readme),
        ("Common combos are valid commands", test_common_combos_are_valid),
        ("Error scenarios match README", test_error_scenarios_match_readme),
        ("dry-run format matches README", test_dry_run_format_matches_readme),
        ("prune shows in history command", test_prune_shows_in_history_command),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        print(f"\n--- Test: {name} ---")
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    print(f"\n{'='*70}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*70}")

    if failed > 0:
        sys.exit(1)
    else:
        print("\nAll documentation consistency tests PASSED!")
        sys.exit(0)


if __name__ == "__main__":
    main()
