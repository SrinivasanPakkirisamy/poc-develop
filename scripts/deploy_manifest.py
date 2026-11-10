#!/usr/bin/env python3
"""
Database (PostgreSQL) & Unix Server Manifest Deployment Engine.
Reads a Release Manifest YAML, executes SQL migrations in order against the target
environment's PostgreSQL database, deploys Unix scripts/configs with rollback backups
and chmod permissions, runs health checks, and records a full deployment audit trail.
"""
import argparse
import datetime
import glob
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import yaml


def run_psql(sql_cmd: str = "", sql_file: str = "") -> str:
    cmd = ["psql", "-v", "ON_ERROR_STOP=1"]
    if sql_file:
        cmd.extend(["-f", sql_file])
    else:
        cmd.extend(["-c", sql_cmd])
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"PostgreSQL execution failed:\n{res.stderr}")
    return res.stdout.strip()


def find_latest_manifest() -> str:
    candidates = sorted(glob.glob("manifests/*.yaml") + glob.glob("manifests/*.yml"))
    if not candidates:
        raise RuntimeError("No manifest YAML files found in manifests/")
    # Prefer highest release number / latest modified
    return candidates[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy Manifest to DB and Unix Server")
    parser.add_argument("--manifest", default="", help="Manifest YAML path (auto-detects latest if omitted)")
    parser.add_argument("--env", required=True, help="Target Environment (DEVELOP, QA, STG, PROD)")
    parser.add_argument("--unix-root", default="/tmp/unix-server", help="Unix server root path")
    parser.add_argument("--artifact-dir", default=".deploy_artifacts", help="Output folder for packaged bundle")
    args = parser.parse_args()

    manifest_path = args.manifest if args.manifest else find_latest_manifest()
    if not os.path.exists(manifest_path):
        raise RuntimeError(f"Manifest '{manifest_path}' does not exist.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    release_id = manifest["release_id"]
    env_name = args.env.upper()
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    actor = os.environ.get("GITHUB_ACTOR", "local-runner")

    print(f"🚀 Starting Deployment | Release={release_id} | Environment={env_name} | Manifest={manifest_path}")

    # 1. Initialize Deployment Audit Table in PostgreSQL
    run_psql(
        """
        CREATE TABLE IF NOT EXISTS deployment_audit_log (
            audit_id SERIAL PRIMARY KEY,
            release_id VARCHAR(64) NOT NULL,
            environment VARCHAR(32) NOT NULL,
            object_type VARCHAR(16) NOT NULL,
            object_path VARCHAR(255) NOT NULL,
            commit_version VARCHAR(64) NOT NULL,
            sha256_checksum VARCHAR(64) NOT NULL,
            deployed_by VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL,
            deployed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    deployed_items = []

    # 2. Deploy Database Objects in Execution Order
    # Note: If baseline DDL tables aren't present in this ephemeral Postgres instance yet,
    # run baseline DDL prerequisite scripts first if needed
    db_objects = sorted(
        manifest.get("objects", {}).get("database", []) or [],
        key=lambda x: int(x.get("order", 999)),
    )
    manifest_db_paths = {item["path"] for item in db_objects}
    for ddl_prereq in sorted(glob.glob("db/ddl/*.sql")):
        if ddl_prereq not in manifest_db_paths:
            print(f"ℹ️  Ensuring baseline schema prerequisite: {ddl_prereq}")
            run_psql(sql_file=ddl_prereq)

    for item in db_objects:
        path = item["path"]
        version = str(item.get("version", "HEAD"))
        with open(path, "rb") as bf:
            sha256 = hashlib.sha256(bf.read()).hexdigest()
        print(f"🗄️  Executing DB script [{item.get('order', '-')}] {path} ...")
        run_psql(sql_file=path)
        run_psql(
            f"""
            INSERT INTO deployment_audit_log
                (release_id, environment, object_type, object_path, commit_version, sha256_checksum, deployed_by, status)
            VALUES
                ('{release_id}', '{env_name}', 'DATABASE', '{path}', '{version[:12]}', '{sha256[:16]}', '{actor}', 'SUCCESS');
            """
        )
        deployed_items.append(("DATABASE", path, version[:10], sha256[:12], f"Executed on PostgreSQL ({os.environ.get('PGDATABASE', 'db')})"))

    # 3. Deploy Unix Server Objects with Backup & Permissions
    env_unix_base = os.path.join(args.unix_root, env_name)
    rollback_dir = os.path.join(env_unix_base, "rollback", f"{release_id}_{ts}")
    os.makedirs(rollback_dir, exist_ok=True)

    unix_objects = manifest.get("objects", {}).get("unix", []) or []
    for item in unix_objects:
        path = item["path"]
        version = str(item.get("version", "HEAD"))
        target_sub = item.get("target_dir", "opt/app/bin").lstrip("/")
        perms_str = str(item.get("permissions", "0755"))
        perms_oct = int(perms_str, 8)

        with open(path, "rb") as bf:
            sha256 = hashlib.sha256(bf.read()).hexdigest()

        dest_dir = os.path.join(env_unix_base, target_sub)
        os.makedirs(dest_dir, exist_ok=True)
        dest_file = os.path.join(dest_dir, os.path.basename(path))

        if os.path.exists(dest_file):
            shutil.copy2(dest_file, os.path.join(rollback_dir, os.path.basename(path)))

        shutil.copy2(path, dest_file)
        os.chmod(dest_file, perms_oct)
        print(f"🐧 Deployed Unix object {path} -> {dest_file} (chmod {perms_str})")

        # Run health-check & sample run if executable shell script
        health_note = f"Deployed to {dest_file} ({perms_str})"
        if dest_file.endswith(".sh"):
            env_vars = os.environ.copy()
            env_vars["APP_ENV"] = env_name
            env_vars["DEPLOY_ROOT"] = os.path.join(env_unix_base, "opt/app")
            hc = subprocess.run([dest_file, "--health-check"], capture_output=True, text=True, env=env_vars, check=True)
            subprocess.run([dest_file], capture_output=True, text=True, env=env_vars, check=True)
            health_note = hc.stdout.strip()
            print(f"   Health Check: {health_note}")

        run_psql(
            f"""
            INSERT INTO deployment_audit_log
                (release_id, environment, object_type, object_path, commit_version, sha256_checksum, deployed_by, status)
            VALUES
                ('{release_id}', '{env_name}', 'UNIX', '{path}', '{version[:12]}', '{sha256[:16]}', '{actor}', 'SUCCESS');
            """
        )
        deployed_items.append(("UNIX", path, version[:10], sha256[:12], health_note))

    # 4. Package Immutable Deployment Bundle (.tar.gz)
    os.makedirs(args.artifact_dir, exist_ok=True)
    bundle_path = os.path.join(args.artifact_dir, f"{release_id}-{env_name}.tar.gz")
    with tarfile.open(bundle_path, "w:gz") as tar:
        tar.add(manifest_path)
        for item in db_objects + unix_objects:
            tar.add(item["path"])

    # 5. Query Live PostgreSQL View & Audit Table for Proof
    db_verify = run_psql("SELECT account_code, loyalty_tier, annual_spend, discount_rate FROM v_customer_discounts ORDER BY account_code;")
    audit_rows = run_psql("SELECT release_id, environment, object_type, object_path, commit_version, status, deployed_at FROM deployment_audit_log ORDER BY audit_id;")
    unix_ls = subprocess.run(["find", env_unix_base, "-maxdepth", "4", "-ls"], capture_output=True, text=True, check=False).stdout.strip()

    print("\n=== Live PostgreSQL Verification (v_customer_discounts) ===")
    print(db_verify)
    print("\n=== PostgreSQL Deployment Audit Log ===")
    print(audit_rows)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        md = [
            f"## ✅ Environment Deployment Report: `{env_name}` (`{release_id}`)",
            f"- **Manifest:** `{manifest_path}`",
            f"- **Packaged Bundle:** `{os.path.basename(bundle_path)}`",
            f"- **Deployed By:** `{actor}`",
            "",
            "### 📦 Deployed Objects",
            "| Target | Object Path | Version SHA | Checksum | Verification Result |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for target, opath, ver, csum, note in deployed_items:
            md.append(f"| **{target}** | `{opath}` | `{ver}` | `{csum}` | {note} |")

        md.extend(
            [
                "",
                "### 🗄️ Live PostgreSQL Query Verification (`v_customer_discounts`)",
                "```text",
                db_verify,
                "```",
                "",
                "### 📜 Database `deployment_audit_log` Table",
                "```text",
                audit_rows,
                "```",
                "",
                "### 🐧 Unix Target Server Filesystem Verification",
                "```text",
                unix_ls,
                "```",
            ]
        )
        with open(summary_path, "a", encoding="utf-8") as sf:
            sf.write("\n".join(md) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
