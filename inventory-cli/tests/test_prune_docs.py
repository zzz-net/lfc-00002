#!/usr/bin/env python3
"""
Documentation consistency test for prune command.

Verifies that README documentation matches actual CLI behavior:
  1. README "所有命令速查" 包含 prune 签名
  2. README "prune 常见组合速查" 表格中每条命令都能实际运行（参数合法）
  3. README 记录的 prune 参数与 prune --help 输出一致
  4. README 记录的错误场景与实际 CLI 输出一致
  5. dry-run 输出格式符合 README 描述
  6. prune 操作会写入 history 表（与 README "清理后验证"一致）

This is a regression test to catch drift between docs and implementation.
"""
import re
import subprocess
import sys
import tempfile
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
README = ROOT / "README.md"
TESTS = ROOT / "tests"


def run_cli(*args, cwd=None):
    """Run inventory CLI via subprocess, return (returncode, stdout, stderr)."""
    full_env = os.environ.copy()
    pythonpath = str(SRC)
    if "PYTHONPATH" in full_env:
        pythonpath = pythonpath + os.pathsep + full_env["PYTHONPATH"]
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


def extract_prune_common_combos(content: str):
    """从 README 的 "prune 常见组合速查" 表格中提取所有命令。

    Returns list of (场景, 命令参数字符串) tuples.
    The command args are what follows "inventory prune " in the table cell.
    """
    # Find the "prune 常见组合速查" section
    # Match from heading to next horizontal rule or heading
    pattern = re.compile(
        r"###\s+prune.*?速查.*?\n"
        r"(.*?)"
        r"(?=\n---\n|\n## |\n### |\Z)",
        re.DOTALL
    )
    match = pattern.search(content)
    assert match, "README should have 'prune 常见组合速查' section"
    section = match.group(1)

    # Extract table rows: | 场景 | 命令 |
    # Skip header (场景/命令) and separator (------) rows
    rows = re.findall(r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", section)

    # Only keep rows where the command column contains an actual prune command
    # (skip header row where the "command" column is just "命令" or "Command")
    valid_rows = []
    for scenario, cmd_text in rows:
        scenario = scenario.strip()
        cmd_text = cmd_text.strip()
        # Skip separator rows
        if "---" in scenario or "---" in cmd_text:
            continue
        # Skip header rows (command column doesn't have "prune" in it)
        if "prune" not in cmd_text.lower():
            continue
        valid_rows.append((scenario, cmd_text))

    assert len(valid_rows) >= 4, \
        f"Common combos table should have >= 4 valid rows, got {len(valid_rows)}"
    rows = valid_rows

    # Extract the args part from `inventory prune <args>` or just raw text
    result = []
    for scenario, cmd_text in rows:
        # Command may be wrapped in backticks
        cmd_clean = cmd_text.strip('`').strip()
        # Remove "inventory prune " prefix to get just the args
        args_str = re.sub(r'^inventory\s+prune\s+', '', cmd_clean)
        result.append((scenario, args_str))

    return result


def test_1_readme_has_prune_in_cheatsheet():
    """README "所有命令速查" 代码块应包含 prune 命令签名。"""
    content = read_readme()

    # Find the "所有命令速查" section
    assert "所有命令速查" in content, "README should have '所有命令速查' section"

    # Locate the code block under "所有命令速查"
    section_match = re.search(
        r"##\s+所有命令速查.*?\n```.*?\n(.*?)\n```",
        content,
        re.DOTALL
    )
    assert section_match, "Should find code block under 所有命令速查"
    cheatsheet = section_match.group(1)

    # Verify prune is listed
    assert "prune" in cheatsheet.lower(), \
        "Cheatsheet should mention prune"
    assert "inventory prune" in cheatsheet, \
        "Cheatsheet should have 'inventory prune' command line"

    # Verify all documented params appear in the signature
    for param in ["--before", "--keep", "--prune-orphans", "--dry-run", "--database"]:
        assert param in cheatsheet, \
            f"Cheatsheet prune signature should include {param}"

    print("  [OK] README 所有命令速查包含 prune 签名及所有参数")


def test_2_cli_help_matches_readme_params():
    """prune --help 输出的参数应与 README 记录的一致。"""
    rc, stdout, stderr = run_cli("prune", "--help")
    assert rc == 0, "prune --help should exit 0"
    help_text = stdout + stderr

    # All params documented in README should appear in help
    readme_params = ["--before", "--keep", "--prune-orphans", "--dry-run", "--database"]
    for param in readme_params:
        assert param in help_text, \
            f"CLI help should contain param {param}"

    # Help should describe what prune does
    assert "clean" in help_text.lower() or "prune" in help_text.lower(), \
        "Help should describe prune purpose"

    # Verify param types match expectations
    assert "--before" in help_text and "TEXT" in help_text, \
        "--before should take TEXT"
    assert "--keep" in help_text and "INTEGER" in help_text, \
        "--keep should take INTEGER"

    print("  [OK] CLI --help 参数与 README 一致")


def test_3_common_combos_are_valid_commands():
    """README "prune 常见组合速查" 表里的每条命令参数都应合法，能被 CLI 正常解析。

    Core check: each command runs without "no such option" or argument parsing errors.
    Output format details are tested separately in test_5 (dry-run format).
    """
    content = read_readme()
    combos = extract_prune_common_combos(content)

    print(f"  Found {len(combos)} common combos in README:")
    for scenario, args_str in combos:
        print(f"    - {scenario}: prune {args_str}")

    # Setup a temp DB with enough snapshots so keep-N / before-date filters have data
    test_dir = Path(tempfile.mkdtemp(prefix="inv_prune_docs_"))
    db_path = test_dir / "test.db"

    rc, _, _ = run_cli("init", "--database", str(db_path),
                       "--config", str(TESTS / "config_good.json"))
    assert rc == 0, "init should succeed"
    run_cli("import", str(TESTS / "store_a.csv"), "STORE001",
            "--batch", "batch_a", "--database", str(db_path))
    run_cli("import", str(TESTS / "store_b.json"), "STORE002",
            "--batch", "batch_b", "--database", str(db_path))
    for strategy in ["sum", "average", "first"]:
        run_cli("merge", "--strategy", strategy, "--database", str(db_path))

    # Test each combo on a fresh DB clone to avoid state pollution
    for i, (scenario, args_str) in enumerate(combos):
        args = args_str.split()
        has_database = any(a.startswith("--database") for a in args)

        # Build full args for CLI
        full_args = ["prune"] + args
        if not has_database:
            full_args.extend(["--database", str(db_path)])

        # For destructive commands that would delete everything,
        # add --dry-run to safely verify parameter parsing.
        # (The --keep 0 case is the main one, but we also protect --before dates
        #  that might match everything - those are fine as-is since they're valid.)
        is_destructive_all = ("--keep" in args and "0" in args and "--dry-run" not in args)
        if is_destructive_all:
            full_args = ["prune", "--dry-run"] + args + ["--database", str(db_path)]

        rc, stdout, stderr = run_cli(*full_args)
        output = stdout + stderr

        # Command should succeed (exit 0) - parameter parsing works
        assert rc == 0, \
            f"Common combo '{scenario}' should succeed (exit 0)\n" \
            f"  Command: prune {args_str}\n" \
            f"  Exit code: {rc}\n" \
            f"  Output: {output}"

        # No parameter parsing errors
        assert "no such option" not in output.lower(), \
            f"Command should not have unknown options: prune {args_str}"
        assert "Got unexpected extra argument" not in output, \
            f"Command should not have extra args: prune {args_str}"
        assert "requires an argument" not in output.lower(), \
            f"Command should not have missing argument errors: prune {args_str}"

        # If it's supposed to be a dry-run command, verify dry-run is actually active
        # (i.e., the flag is recognized and triggers dry-run behavior)
        if "--dry-run" in args:
            assert "DRY RUN" in output or "No changes will be made" in output or \
                   "Remove --dry-run" in output or "No data to prune" in output, \
                f"Command with --dry-run should show dry-run related output: prune {args_str}\n" \
                f"Output: {output}"

        print(f"    [{i+1}] OK: {scenario}")

    print("  [OK] All common combos have valid parameters and run successfully")


def test_4_error_scenarios_match_readme():
    """README 记录的 prune 错误场景应与实际 CLI 输出一致。"""
    test_dir = Path(tempfile.mkdtemp(prefix="inv_prune_errdoc_"))
    db_path = test_dir / "test.db"

    # Setup
    run_cli("init", "--database", str(db_path),
            "--config", str(TESTS / "config_good.json"))
    run_cli("import", str(TESTS / "store_a.csv"), "STORE001",
            "--batch", "batch_a", "--database", str(db_path))
    run_cli("merge", "--strategy", "sum", "--database", str(db_path))

    # Scenarios: (description, args, expected_exit, expected_keywords)
    scenarios = [
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
            assert kw.lower() in output.lower(), \
                f"Error scenario '{desc}': output should contain '{kw}'\nOutput: {output}"

        print(f"    [{i+1}] OK: {desc}")

    print("  [OK] 错误场景描述与 CLI 实际输出一致")


def test_5_dry_run_format_matches_readme():
    """dry-run 输出格式应与 README 描述一致：有 DRY RUN 标题、快照表、Summary、Remove --dry-run 提示。"""
    test_dir = Path(tempfile.mkdtemp(prefix="inv_prune_dryfmt_"))
    db_path = test_dir / "test.db"

    run_cli("init", "--database", str(db_path),
            "--config", str(TESTS / "config_good.json"))
    run_cli("import", str(TESTS / "store_a.csv"), "STORE001",
            "--batch", "batch_a", "--database", str(db_path))
    run_cli("import", str(TESTS / "store_b.json"), "STORE002",
            "--batch", "batch_b", "--database", str(db_path))
    run_cli("merge", "--strategy", "sum", "--database", str(db_path))
    run_cli("merge", "--strategy", "average", "--database", str(db_path))

    # Dry-run without --prune-orphans: snapshot table only
    rc, stdout, _ = run_cli("prune", "--dry-run", "--keep", "1", "--database", str(db_path))
    assert rc == 0

    # Verify key elements from README description
    assert "DRY RUN" in stdout, "Should have DRY RUN header"
    assert "Snapshots to delete" in stdout, "Should show 'Snapshots to delete'"
    assert "ID" in stdout, "Table should have ID column"
    assert "Created At" in stdout, "Table should have Created At column"
    assert "Batch ID" in stdout, "Table should have Batch ID column"
    assert "Records" in stdout, "Table should have Records column"
    assert "Summary" in stdout, "Should have Summary"
    assert "Remove --dry-run" in stdout, "Should have Remove --dry-run hint"

    # Without --prune-orphans: should NOT show "Batches to delete" section
    assert "Batches to delete" not in stdout, \
        "Without --prune-orphans, dry-run should not show batches section"

    # Dry-run WITH --prune-orphans: should show batch section
    rc, stdout2, _ = run_cli("prune", "--dry-run", "--keep", "1",
                             "--prune-orphans", "--database", str(db_path))
    assert rc == 0
    assert "Batches to delete" in stdout2, \
        "With --prune-orphans, dry-run should show batches section"

    print("  [OK] dry-run 输出格式与 README 描述一致")


def test_6_prune_appears_in_history():
    """README 说清理操作会写入 history 表，应能在 history 命令中看到。"""
    test_dir = Path(tempfile.mkdtemp(prefix="inv_prune_histdoc_"))
    db_path = test_dir / "test.db"

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
    rc, _, _ = run_cli(
        "audit-log", str(test_dir / "audit.csv"),
        "--type", "prune", "--database", str(db_path)
    )
    assert rc == 0
    csv_content = (test_dir / "audit.csv").read_text(encoding="utf-8-sig")
    assert "prune" in csv_content.lower(), \
        "prune should be filterable in audit-log (type filter includes prune)"

    print("  [OK] prune 操作写入 history，与 README 描述一致")


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print(f"\n{'='*70}")
    print("prune documentation consistency test (README vs CLI)")
    print(f"{'='*70}")

    tests = [
        ("速查表包含 prune 签名", test_1_readme_has_prune_in_cheatsheet),
        ("CLI --help 参数与 README 一致", test_2_cli_help_matches_readme_params),
        ("常见组合命令参数合法", test_3_common_combos_are_valid_commands),
        ("错误场景与 README 一致", test_4_error_scenarios_match_readme),
        ("dry-run 输出格式正确", test_5_dry_run_format_matches_readme),
        ("prune 写入 history", test_6_prune_appears_in_history),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*70}")
    print(f"结果：{passed} 通过，{failed} 失败")
    print(f"{'='*70}")

    if failed > 0:
        sys.exit(1)
    else:
        print("\n所有文档一致性测试通过！")
        sys.exit(0)


if __name__ == "__main__":
    main()
