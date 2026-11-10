#!/usr/bin/env python3
"""
Manifest Packaging & Selective Version Promotion Tool:
  - stamp: Pins each object's exact git commit SHA (and SHA-256) in the manifest YAML.
  - extract: Extracts the exact commit SHA of each object listed in a manifest
             from a source git repository into a target repository directory,
             preserving origin_sha and verifying cryptographic SHA-256 integrity.
"""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import yaml


def git_last_commit_for_file(repo_dir: str, rel_path: str) -> str:
    res = subprocess.run(
        ["git", "-C", repo_dir, "log", "-n", "1", "--format=%H", "--", rel_path],
        capture_output=True,
        text=True,
        check=True,
    )
    sha = res.stdout.strip()
    if not sha:
        raise RuntimeError(f"No git commit history found for '{rel_path}'")
    return sha


def git_commit_exists(repo_dir: str, sha: str) -> bool:
    res = subprocess.run(
        ["git", "-C", repo_dir, "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    return res.returncode == 0


def git_show_file_at_version(repo_dir: str, version: str, rel_path: str) -> bytes:
    if version in ("HEAD", "LATEST", "", None) or not git_commit_exists(repo_dir, version):
        version = git_last_commit_for_file(repo_dir, rel_path)
    res = subprocess.run(
        ["git", "-C", repo_dir, "show", f"{version}:{rel_path}"],
        capture_output=True,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"Failed to read '{rel_path}' at version '{version}': {res.stderr.decode('utf-8', 'replace')}"
        )
    return res.stdout


def cmd_stamp(args: argparse.Namespace) -> int:
    repo_dir = args.repo_dir
    manifest_full = os.path.join(repo_dir, args.manifest) if not os.path.isabs(args.manifest) else args.manifest
    with open(manifest_full, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for section in ("database", "unix"):
        for item in data.get("objects", {}).get(section, []) or []:
            rel_path = item["path"]
            if args.force or item.get("version") in (None, "", "HEAD", "LATEST"):
                sha = git_last_commit_for_file(repo_dir, rel_path)
                if "origin_sha" not in item:
                    item["origin_sha"] = sha
                item["version"] = sha
                content = git_show_file_at_version(repo_dir, sha, rel_path)
                item["sha256"] = hashlib.sha256(content).hexdigest()[:16]
                print(f"📌 Stamped {rel_path} -> commit={sha[:10]} (origin={item['origin_sha'][:10]}, sha256={item['sha256']})")
            else:
                print(f"ℹ️  Kept pinned {rel_path} -> {item['version'][:10]}")

    with open(manifest_full, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    print(f"✅ Updated manifest: {manifest_full}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    manifest_full = os.path.join(args.source_dir, args.manifest)
    with open(manifest_full, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    release_id = data["release_id"]
    extracted_records = []

    for section in ("database", "unix"):
        for item in data.get("objects", {}).get(section, []) or []:
            rel_path = item["path"]
            req_version = item.get("version", "HEAD")
            resolved_sha = (
                req_version
                if req_version not in ("HEAD", "LATEST", "", None) and git_commit_exists(args.source_dir, req_version)
                else git_last_commit_for_file(args.source_dir, rel_path)
            )
            content = git_show_file_at_version(args.source_dir, resolved_sha, rel_path)
            sha256 = hashlib.sha256(content).hexdigest()[:16]

            # Verify SHA-256 integrity if previously stamped
            expected_sha256 = item.get("sha256")
            if expected_sha256 and expected_sha256 != sha256:
                raise RuntimeError(
                    f"Integrity mismatch for {rel_path}: expected sha256={expected_sha256}, got {sha256}"
                )

            item["origin_sha"] = item.get("origin_sha") or resolved_sha
            item["sha256"] = sha256

            dest_path = os.path.join(args.target_dir, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as out_f:
                out_f.write(content)

            if rel_path.endswith(".sh"):
                os.chmod(dest_path, 0o755)

            extracted_records.append(
                {
                    "section": section,
                    "path": rel_path,
                    "source_commit_sha": resolved_sha,
                    "origin_sha": item["origin_sha"],
                    "sha256": sha256,
                }
            )
            print(f"📦 Extracted {rel_path} @ commit {resolved_sha[:10]} (origin={item['origin_sha'][:10]}, sha256={sha256})")

    # Save manifest into target repo
    data["promoted_from"] = args.source_env
    data["target_env"] = args.target_env
    dest_manifest = os.path.join(args.target_dir, args.manifest)
    os.makedirs(os.path.dirname(dest_manifest), exist_ok=True)
    with open(dest_manifest, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)

    # Append promotion audit trail
    audit_file = os.path.join(args.target_dir, "manifests", "promotion_audit_log.jsonl")
    audit_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release_id": release_id,
        "manifest": args.manifest,
        "from_env": args.source_env,
        "to_env": args.target_env,
        "promoted_by": args.actor,
        "objects": extracted_records,
    }
    with open(audit_file, "a", encoding="utf-8") as af:
        af.write(json.dumps(audit_entry) + "\n")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            f"## 🚀 Cross-Repo Manifest Promotion: `{release_id}` (`{args.source_env}` ➡️ `{args.target_env}`)",
            "",
            "| Category | Object Path | Source Commit SHA | Origin DEV SHA | File SHA-256 |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for r in extracted_records:
            lines.append(
                f"| `{r['section']}` | `{r['path']}` | `{r['source_commit_sha'][:10]}` | `{r['origin_sha'][:10]}` | `{r['sha256']}` |"
            )
        with open(summary_path, "a", encoding="utf-8") as sf:
            sf.write("\n".join(lines) + "\n")

    print(f"✅ Successfully packaged {len(extracted_records)} object(s) into {args.target_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manifest version stamping & cross-repo promotion")
    sub = parser.add_subparsers(dest="command", required=True)

    p_stamp = sub.add_parser("stamp", help="Stamp exact commit SHAs into manifest")
    p_stamp.add_argument("manifest", help="Path to manifest YAML")
    p_stamp.add_argument("--repo-dir", default=".", help="Git repository root")
    p_stamp.add_argument("--force", action="store_true", help="Update version SHA to target repo commit while preserving origin_sha")

    p_ext = sub.add_parser("extract", help="Extract pinned versions into target repo directory")
    p_ext.add_argument("manifest", help="Relative path to manifest YAML")
    p_ext.add_argument("--source-dir", required=True, help="Source git repo directory")
    p_ext.add_argument("--target-dir", required=True, help="Target git repo directory")
    p_ext.add_argument("--source-env", required=True, help="Source environment name")
    p_ext.add_argument("--target-env", required=True, help="Target environment name")
    p_ext.add_argument("--actor", default="github-actions", help="User triggering promotion")

    args = parser.parse_args()
    if args.command == "stamp":
        return cmd_stamp(args)
    if args.command == "extract":
        return cmd_extract(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
