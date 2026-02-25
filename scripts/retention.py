#!/usr/bin/env python3
"""
Data retention for Claude Code observability.

Handles what Langfuse's built-in retention does NOT: local state files,
hook logs, and on-demand trace pruning via the Langfuse API.

Usage:
    python3 scripts/retention.py                # Prune traces older than 30 days
    python3 scripts/retention.py --days 14      # Custom retention period
    python3 scripts/retention.py --dry-run      # Show what would be deleted
    python3 scripts/retention.py --log-only     # Skip Langfuse API, only rotate logs
    python3 scripts/retention.py --json         # Machine-readable output

Environment variables:
    LANGFUSE_PUBLIC_KEY  — Project public key
    LANGFUSE_SECRET_KEY  — Project secret key
    LANGFUSE_HOST        — Langfuse URL (default: http://localhost:3050)

Cron example (weekly, Sunday 3am):
    0 3 * * 0 cd /path/to/personal-llm-o11y && \
        ~/.claude/hooks/venv/bin/python scripts/retention.py --days 30 \
        >> ~/.claude/state/retention.log 2>&1
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None

STATE_DIR = Path.home() / ".claude" / "state"
LOG_FILE = STATE_DIR / "langfuse_hook.log"
STATE_FILE = STATE_DIR / "langfuse_state.json"
QUEUE_FILE = STATE_DIR / "pending_traces.jsonl"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Data retention for Claude Code observability"
    )
    parser.add_argument(
        "--days", type=int, default=30, help="Delete data older than N days (default: 30)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be deleted without acting"
    )
    parser.add_argument(
        "--log-only", action="store_true", help="Skip Langfuse API, only rotate local files"
    )
    parser.add_argument(
        "--max-log-mb", type=float, default=10, help="Truncate hook log if larger than N MB (default: 10)"
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    return parser.parse_args()


def prune_traces(client, cutoff: datetime, dry_run: bool) -> int:
    """Delete Langfuse traces older than cutoff. Returns count deleted."""
    deleted = 0
    page = 1
    while True:
        batch = client.api.trace.list(limit=100, page=page)
        if not batch.data:
            break
        for t in batch.data:
            ts = t.timestamp
            if ts and ts < cutoff:
                if dry_run:
                    deleted += 1
                else:
                    try:
                        client.api.trace.delete(t.id)
                        deleted += 1
                    except Exception as e:
                        print(f"  Warning: failed to delete trace {t.id}: {e}", file=sys.stderr)
        if page >= batch.meta.total_pages:
            break
        page += 1
        if page % 10 == 0:
            action = "found" if dry_run else "deleted"
            print(f"  Scanning page {page}/{batch.meta.total_pages} ({deleted} {action})...", file=sys.stderr)
    return deleted


def rotate_log(max_mb: float, dry_run: bool) -> int:
    """Truncate hook log if it exceeds max_mb. Returns bytes reclaimed."""
    if not LOG_FILE.exists():
        return 0
    size = LOG_FILE.stat().st_size
    threshold = int(max_mb * 1024 * 1024)
    if size <= threshold:
        return 0
    if dry_run:
        return size  # would reclaim all but ~last 1000 lines
    lines = LOG_FILE.read_text().splitlines()
    keep = lines[-1000:] if len(lines) > 1000 else lines
    new_content = "\n".join(keep) + "\n"
    reclaimed = size - len(new_content.encode())
    LOG_FILE.write_text(new_content)
    return max(reclaimed, 0)


def prune_state_file(cutoff: datetime, dry_run: bool) -> int:
    """Remove stale sessions from langfuse_state.json. Returns count pruned."""
    if not STATE_FILE.exists():
        return 0
    try:
        data = json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(data, dict):
        return 0
    to_remove = []
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        updated = value.get("updated") or value.get("last_seen")
        if not updated:
            continue
        try:
            ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            if ts < cutoff:
                to_remove.append(key)
        except (ValueError, AttributeError):
            continue
    if not dry_run and to_remove:
        for key in to_remove:
            del data[key]
        STATE_FILE.write_text(json.dumps(data, indent=2) + "\n")
    return len(to_remove)


def prune_queue(cutoff: datetime, dry_run: bool) -> int:
    """Remove old entries from pending_traces.jsonl. Returns count pruned."""
    if not QUEUE_FILE.exists():
        return 0
    try:
        lines = QUEUE_FILE.read_text().splitlines()
    except OSError:
        return 0
    keep = []
    pruned = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            queued_at = entry.get("queued_at")
            if queued_at:
                ts = datetime.fromisoformat(queued_at.replace("Z", "+00:00"))
                if ts < cutoff:
                    pruned += 1
                    continue
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass
        keep.append(line)
    if not dry_run and pruned > 0:
        QUEUE_FILE.write_text("\n".join(keep) + "\n" if keep else "")
    return pruned


def main():
    args = parse_args()
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    summary = {
        "retention_days": args.days,
        "cutoff": cutoff.isoformat(),
        "dry_run": args.dry_run,
        "traces_deleted": 0,
        "log_bytes_reclaimed": 0,
        "sessions_pruned": 0,
        "queue_entries_removed": 0,
    }

    if not args.json:
        mode = "DRY RUN" if args.dry_run else "LIVE"
        print(f"\n  Retention [{mode}]: delete data older than {args.days} days (before {cutoff.date()})")

    # 1. Prune old Langfuse traces
    if not args.log_only:
        if Langfuse is None:
            print("  Warning: langfuse package not installed, skipping trace pruning.", file=sys.stderr)
        else:
            host = os.environ.get("LANGFUSE_HOST", "http://localhost:3050")
            public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
            secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
            if not public_key or not secret_key:
                print("  Warning: LANGFUSE_PUBLIC_KEY/SECRET_KEY not set, skipping trace pruning.", file=sys.stderr)
            else:
                client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
                try:
                    client.api.health.health()
                    if not args.json:
                        print(f"  Connected to Langfuse at {host}")
                        print("  Scanning traces...")
                    summary["traces_deleted"] = prune_traces(client, cutoff, args.dry_run)
                except Exception as e:
                    print(f"  Warning: Langfuse unavailable ({e}), skipping trace pruning.", file=sys.stderr)
                finally:
                    client.shutdown()

    # 2. Rotate hook log
    if not args.json:
        print("  Checking hook log...")
    summary["log_bytes_reclaimed"] = rotate_log(args.max_log_mb, args.dry_run)

    # 3. Prune stale sessions from state file
    if not args.json:
        print("  Checking state file...")
    summary["sessions_pruned"] = prune_state_file(cutoff, args.dry_run)

    # 4. Clean pending queue
    if not args.json:
        print("  Checking pending queue...")
    summary["queue_entries_removed"] = prune_queue(cutoff, args.dry_run)

    # 5. Print summary
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        label = "would delete" if args.dry_run else "deleted"
        print(f"\n  Summary:")
        print(f"    Traces {label}:       {summary['traces_deleted']}")
        print(f"    Log bytes reclaimed:   {summary['log_bytes_reclaimed']}")
        print(f"    Sessions pruned:       {summary['sessions_pruned']}")
        print(f"    Queue entries removed: {summary['queue_entries_removed']}")
        print()


if __name__ == "__main__":
    main()
