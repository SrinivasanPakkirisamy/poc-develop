#!/usr/bin/env python3
"""
CI & Pre-Checkin Validation Engine:
  1. Delete-Safe File Check (blocks deleted files unless ALLOW_DELETE is authorized)
  2. Delete-Safe SQL Check (blocks DROP, TRUNCATE, or unfiltered DELETE FROM)
  3. SQL Standards Check (requires -- Object: and -- Author: metadata headers)
  4. Unix Script Check (LF line endings, valid bash shebang, bash -n syntax, secret scan)
  5. Lock Coordination Check (blocks edits to files locked by another developer)
  6. Manifest Schema Validation (verifies YAML structure and referenced files)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import yaml


def run_git(args: list[str]) -> str:
    res = subprocess.run(["git"] + args, capture_output=True, text=True, check=False)
    return res.stdout.strip()


def strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    sql = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    return sql


def write_summary(markdown_lines: list[str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(markdown_lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate repository rules")
    parser.add_argument("--base", default="origin/main", help="Base git ref for diff")
    parser.add_argument("--head", default="HEAD", help="Head git ref for diff")
    parser.add_argument("--pr-author", default="", help="GitHub username of PR author")
    parser.add_argument("--allow-delete", action="store_true", help="Allow file/SQL deletions")
    args = parser.parse_args()

    errors: list[str] = []
    checks_report: list[tuple[str, str, str]] = []

    # Determine changed and deleted files
    deleted_out = run_git(["diff", "--name-only", "--diff-filter=D", f"{args.base}...{args.head}"])
    deleted_files = [f for f in deleted_out.splitlines() if f.strip()]

    changed_out = run_git(["diff", "--name-only", "--diff-filter=AMR", f"{args.base}...{args.head}"])
    changed_files = [f for f in changed_out.splitlines() if f.strip()]

    # 1. Delete-Safe File Check
    if deleted_files and not args.allow_delete:
        msg = f"Deleted files blocked ({', '.join(deleted_files)}). Add 'ALLOW_DELETE' label to authorize."
        errors.append(msg)
        checks_report.append(("Delete-Safe (Files)", "❌ FAILED", msg))
    else:
        detail = f"Authorized ({len(deleted_files)} deleted)" if deleted_files else "No deleted files"
        checks_report.append(("Delete-Safe (Files)", "✅ PASSED", detail))

    # 2 & 3. SQL Rules & Destructive Statement Check
    sql_files = [f for f in changed_files if f.endswith(".sql") and os.path.exists(f)]
    sql_errors = []
    for path in sql_files:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        if "-- Object:" not in raw or "-- Author:" not in raw:
            sql_errors.append(f"{path}: Missing required '-- Object:' or '-- Author:' header comment.")

        cleaned = strip_sql_comments(raw)
        if not args.allow_delete:
            if re.search(r"\b(DROP\s+(TABLE|VIEW|SCHEMA|DATABASE|INDEX)|TRUNCATE\s+TABLE|TRUNCATE)\b", cleaned, re.IGNORECASE):
                sql_errors.append(f"{path}: Destructive SQL (DROP/TRUNCATE) blocked by Delete-Safe policy.")
            for stmt in cleaned.split(";"):
                if re.search(r"\bDELETE\s+FROM\b", stmt, re.IGNORECASE) and not re.search(r"\bWHERE\b", stmt, re.IGNORECASE):
                    sql_errors.append(f"{path}: Unfiltered 'DELETE FROM' without WHERE clause blocked.")

    if sql_errors:
        errors.extend(sql_errors)
        checks_report.append(("SQL Rules & Delete-Safe", "❌ FAILED", "; ".join(sql_errors)))
    else:
        checks_report.append(("SQL Rules & Delete-Safe", "✅ PASSED", f"Validated {len(sql_files)} SQL file(s)"))

    # 4. Unix Script & Config Rules
    unix_files = [f for f in changed_files if f.startswith("unix/") and os.path.exists(f)]
    unix_errors = []
    for path in unix_files:
        with open(path, "rb") as bf:
            raw_bytes = bf.read()
        if b"\r\n" in raw_bytes:
            unix_errors.append(f"{path}: Windows CRLF line endings found; Unix LF required.")
        text = raw_bytes.decode("utf-8", errors="replace")
        if re.search(r"(PASSWORD|SECRET_KEY|PRIVATE_KEY)\s*=\s*['\"][^'\"]+['\"]", text, re.IGNORECASE):
            unix_errors.append(f"{path}: Hardcoded credential/secret detected.")
        if path.endswith(".sh"):
            if not (text.startswith("#!/usr/bin/env bash") or text.startswith("#!/bin/bash")):
                unix_errors.append(f"{path}: Missing standard bash shebang (#!/usr/bin/env bash).")
            syn = subprocess.run(["bash", "-n", path], capture_output=True, text=True, check=False)
            if syn.returncode != 0:
                unix_errors.append(f"{path}: Bash syntax error: {syn.stderr.strip()}")

    if unix_errors:
        errors.extend(unix_errors)
        checks_report.append(("Unix Script & Security Rules", "❌ FAILED", "; ".join(unix_errors)))
    else:
        checks_report.append(("Unix Script & Security Rules", "✅ PASSED", f"Validated {len(unix_files)} Unix file(s)"))

    # 5. Lock Coordination Check
    lock_errors = []
    if os.path.exists("locks/active_locks.json"):
        with open("locks/active_locks.json", "r", encoding="utf-8") as lf:
            active_locks = json.load(lf).get("locks", {})
        for path in changed_files + deleted_files:
            if path in active_locks:
                holder = active_locks[path]["user"]
                if args.pr_author and holder.lower() != args.pr_author.lower():
                    lock_errors.append(
                        f"{path}: Locked by '{holder}' (ticket {active_locks[path].get('ticket')}); "
                        f"PR author '{args.pr_author}' cannot modify until unlocked."
                    )

    if lock_errors:
        errors.extend(lock_errors)
        checks_report.append(("Object Lock Coordination", "❌ FAILED", "; ".join(lock_errors)))
    else:
        checks_report.append(("Object Lock Coordination", "✅ PASSED", "No conflicting object locks"))

    # 6. Manifest Validation
    manifest_files = [f for f in changed_files if f.startswith("manifests/") and f.endswith((".yaml", ".yml")) and os.path.exists(f)]
    manifest_errors = []
    for mpath in manifest_files:
        try:
            with open(mpath, "r", encoding="utf-8") as mf:
                mdata = yaml.safe_load(mf)
            if not mdata or "release_id" not in mdata or "objects" not in mdata:
                manifest_errors.append(f"{mpath}: Missing 'release_id' or 'objects' root keys.")
                continue
            for section in ("database", "unix"):
                for item in mdata["objects"].get(section, []) or []:
                    opath = item.get("path")
                    if not opath or not os.path.exists(opath):
                        manifest_errors.append(f"{mpath}: Referenced object '{opath}' does not exist.")
        except Exception as exc:
            manifest_errors.append(f"{mpath}: Invalid YAML ({exc})")

    if manifest_errors:
        errors.extend(manifest_errors)
        checks_report.append(("Manifest Package Schema", "❌ FAILED", "; ".join(manifest_errors)))
    else:
        checks_report.append(("Manifest Package Schema", "✅ PASSED", f"Validated {len(manifest_files)} manifest(s)"))

    # Print & write GitHub Summary
    summary = [
        "## 🛡️ Migration Rule & Delete-Safe Validation Report",
        "",
        "| Check | Status | Details |",
        "| :--- | :--- | :--- |",
    ]
    for name, status, detail in checks_report:
        print(f"{status} | {name}: {detail}")
        summary.append(f"| **{name}** | {status} | {detail} |")

    write_summary(summary)

    if errors:
        print("\n❌ Validation failed with errors:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("\n✅ All validation gates passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
