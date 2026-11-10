#!/usr/bin/env python3
"""
Object Lock & Audit Ledger Manager for VS Code and GitHub Actions CI.
Enables developers to coordinate edits on Database (.sql) and Unix (.sh, .conf) objects
and maintains an append-only audit trail in locks/lock_audit_log.jsonl.
"""
import argparse
import datetime
import json
import os
import sys

ACTIVE_LOCKS_FILE = "locks/active_locks.json"
AUDIT_LOG_FILE = "locks/lock_audit_log.jsonl"


def now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_locks() -> dict:
    if not os.path.exists(ACTIVE_LOCKS_FILE):
        return {"locks": {}}
    with open(ACTIVE_LOCKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_locks(data: dict) -> None:
    os.makedirs(os.path.dirname(ACTIVE_LOCKS_FILE), exist_ok=True)
    with open(ACTIVE_LOCKS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def append_audit(action: str, obj_path: str, user: str, ticket: str, note: str) -> None:
    os.makedirs(os.path.dirname(AUDIT_LOG_FILE), exist_ok=True)
    entry = {
        "timestamp": now_utc(),
        "action": action,
        "object": obj_path,
        "user": user,
        "ticket": ticket,
        "note": note,
    }
    with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def cmd_lock(args: argparse.Namespace) -> int:
    obj = args.file.lstrip("./")
    data = load_locks()
    locks = data.setdefault("locks", {})

    if obj in locks and locks[obj]["user"] != args.user:
        holder = locks[obj]
        print(
            f"❌ LOCK CONFLICT: '{obj}' is currently locked by '{holder['user']}' "
            f"(ticket: {holder['ticket']}, since: {holder['locked_at']})."
        )
        append_audit("LOCK_DENIED", obj, args.user, args.ticket, f"Held by {holder['user']}")
        return 1

    locks[obj] = {
        "user": args.user,
        "ticket": args.ticket,
        "locked_at": now_utc(),
    }
    save_locks(data)
    append_audit("LOCK", obj, args.user, args.ticket, "Object locked for editing")
    print(f"✅ Locked '{obj}' for user '{args.user}' (ticket: {args.ticket}).")
    return 0


def cmd_unlock(args: argparse.Namespace) -> int:
    obj = args.file.lstrip("./")
    data = load_locks()
    locks = data.setdefault("locks", {})

    if obj not in locks:
        print(f"ℹ️  '{obj}' is not currently locked.")
        return 0

    holder = locks[obj]
    if holder["user"] != args.user and not args.force:
        print(
            f"❌ CANNOT UNLOCK: '{obj}' is locked by '{holder['user']}'. "
            f"Use --force if admin override is authorized."
        )
        return 1

    ticket = holder.get("ticket", "N/A")
    del locks[obj]
    save_locks(data)
    append_audit("UNLOCK", obj, args.user, ticket, "Object lock released")
    print(f"✅ Unlocked '{obj}'.")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    data = load_locks()
    locks = data.get("locks", {})
    print("=== Active Object Locks ===")
    if not locks:
        print("  (No active locks)")
    else:
        for obj, info in sorted(locks.items()):
            print(f"  🔒 {obj} -> user={info['user']} | ticket={info['ticket']} | since={info['locked_at']}")

    print("\n=== Recent Lock Audit History (Last 10) ===")
    if os.path.exists(AUDIT_LOG_FILE):
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        for line in lines[-10:]:
            rec = json.loads(line)
            print(f"  [{rec['timestamp']}] {rec['action']:11s} | {rec['object']} | user={rec['user']} | ticket={rec['ticket']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Object Lock & Audit Manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p_lock = sub.add_parser("lock", help="Lock an object for editing")
    p_lock.add_argument("file", help="Relative file path")
    p_lock.add_argument("--user", required=True, help="Developer username")
    p_lock.add_argument("--ticket", default="ADHOC", help="Ticket or Release ID")

    p_unlock = sub.add_parser("unlock", help="Release lock on an object")
    p_unlock.add_argument("file", help="Relative file path")
    p_unlock.add_argument("--user", required=True, help="Developer username")
    p_unlock.add_argument("--force", action="store_true", help="Admin override unlock")

    sub.add_parser("status", help="Show active locks and recent audit trail")

    args = parser.parse_args()
    if args.command == "lock":
        return cmd_lock(args)
    if args.command == "unlock":
        return cmd_unlock(args)
    if args.command == "status":
        return cmd_status(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
