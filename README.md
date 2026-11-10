# Multi-Environment GitHub Migration & Release POC (`DEVELOP` -> `QA` -> `STG` -> `PROD`)

End-to-end reference implementation demonstrating VS Code developer workflows, object locking & audit logs, Delete-Safe & rule-based CI validation, merge/deployment approvals, selective version migration via Release Manifests, and automated PostgreSQL + Unix server deployments.

## Environment Repositories
| Environment | Repository | Database Target | Unix Target |
| :--- | :--- | :--- | :--- |
| **DEVELOP** | `poc-develop` | PostgreSQL `db_develop` | `/tmp/unix-server/DEVELOP/opt/app` |
| **QA** | `poc-qa` | PostgreSQL `db_qa` | `/tmp/unix-server/QA/opt/app` |
| **STG** | `poc-stg` | PostgreSQL `db_stg` | `/tmp/unix-server/STG/opt/app` |
| **PROD** | `poc-prod` | PostgreSQL `db_prod` | `/tmp/unix-server/PROD/opt/app` |

## VS Code Developer Tasks (`Cmd+Shift+P` -> `Tasks: Run Task`)
1. **1. Lock Object (Coordinate Edit)** — Locks a `.sql` or `.sh` object in `locks/active_locks.json` and logs to `locks/lock_audit_log.jsonl`.
2. **2. Unlock Object** — Releases an active object lock and logs to the audit ledger.
3. **3. View Active Locks & Audit Trail** — Displays all active locks and recent lock history.
4. **4. Run Pre-Checkin Rule Validation** — Runs Delete-Safe, SQL, Unix, and Manifest checks locally before pushing.
5. **5. Stamp Manifest Object Versions** — Pins exact Git commit SHAs into a manifest YAML under `manifests/`.

## Automated GitHub Workflows
- **`1-validate-pr.yml`**: Triggered on Pull Requests. Enforces Delete-Safe file & SQL checks (`DROP`/`TRUNCATE`/unfiltered `DELETE`), SQL metadata standards, Unix LF/shebang/`bash -n`/secret checks, Object Lock ownership, and Manifest YAML validation.
- **`2-deploy-env.yml`**: Triggered on merge to `main` (gated by GitHub Environment protection rules). Deploys manifest objects in order to a live PostgreSQL 16 service container and Unix server directory with rollback backups, `chmod` permissions, health checks, and `deployment_audit_log` DB recording.
- **`3-promote-manifest.yml`**: Triggered manually (`Actions -> 3. Promote Manifest`). Extracts the **exact pinned Git commit SHA** of each object listed in the manifest and opens a Pull Request in the next environment repository (`poc-qa`, `poc-stg`, `poc-prod`).
