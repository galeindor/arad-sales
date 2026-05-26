"""
monitor.py — Object status change monitor

Fetches a list of objects from a demo API (JSONPlaceholder /todos),
compares their `status` (derived from `completed` field) against a
local CSV snapshot, reports what changed, and saves the new snapshot.

Usage:
    python monitor.py              # run once
    python monitor.py --watch 30   # poll every 30 seconds
"""

import csv
import time
import argparse
import urllib.request
import urllib.error
import json
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

API_URL      = "https://jsonplaceholder.typicode.com/todos"
SNAPSHOT_CSV = Path("snapshot.csv")          # local state file
LOG_FILE     = Path("monitor.log")           # append-only change log
CSV_FIELDS   = ["id", "title", "status"]     # columns we care about

# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(lines: list[str]) -> None:
    """Append plain-text lines (no ANSI codes) to the log file."""
    with LOG_FILE.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def fetch_objects() -> list[dict]:
    """Fetch objects from the demo API and normalise to {id, title, status}."""
    with urllib.request.urlopen(API_URL, timeout=10) as resp:
        raw: list[dict] = json.loads(resp.read())

    return [
        {
            "id":     str(item["id"]),
            "title":  item["title"],
            # Map the boolean `completed` field → human-readable status string
            "status": "completed" if item["completed"] else "pending",
        }
        for item in raw
    ]


def load_snapshot() -> dict[str, dict]:
    """Read the local CSV snapshot. Returns {id: row_dict} or {} if missing."""
    if not SNAPSHOT_CSV.exists():
        return {}

    with SNAPSHOT_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["id"]: row for row in reader}


def save_snapshot(objects: list[dict]) -> None:
    """Persist the current object list to the local CSV snapshot."""
    with SNAPSHOT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(objects)


def detect_changes(
    previous: dict[str, dict],
    current: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Compare previous snapshot with current fetch.

    Returns:
        changed  — objects whose status field differs
        added    — objects not present in the snapshot
        removed  — objects present in the snapshot but missing from API
    """
    current_map = {obj["id"]: obj for obj in current}
    prev_ids    = set(previous)
    curr_ids    = set(current_map)

    changed = [
        {
            "id":       oid,
            "title":    current_map[oid]["title"],
            "old":      previous[oid]["status"],
            "new":      current_map[oid]["status"],
        }
        for oid in prev_ids & curr_ids
        if previous[oid]["status"] != current_map[oid]["status"]
    ]
    added   = [current_map[oid] for oid in curr_ids - prev_ids]
    removed = [previous[oid]    for oid in prev_ids - curr_ids]

    return changed, added, removed


# ── Reporting ─────────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
DIM    = "\033[2m"


def report(changed, added, removed, total: int) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{BOLD}{CYAN}[{ts}] Checked {total} objects{RESET}")

    log_lines = [f"\n[{ts}] Checked {total} objects"]

    if not any([changed, added, removed]):
        print(f"  {DIM}No changes detected.{RESET}")
        log_lines.append("  No changes detected.")
        _log(log_lines)
        return

    if changed:
        print(f"\n  {BOLD}{YELLOW}Status changes ({len(changed)}){RESET}")
        log_lines.append(f"\n  Status changes ({len(changed)})")
        for c in changed:
            arrow = f"{RED}{c['old']}{RESET} → {GREEN}{c['new']}{RESET}"
            print(f"    #{c['id']:>4}  {c['title'][:55]:<55}  {arrow}")
            log_lines.append(f"    #{c['id']:>4}  {c['title'][:55]:<55}  {c['old']} -> {c['new']}")

    if added:
        print(f"\n  {BOLD}{GREEN}New objects ({len(added)}){RESET}")
        log_lines.append(f"\n  New objects ({len(added)})")
        for a in added:
            print(f"    #{a['id']:>4}  {a['title'][:55]}  [{a['status']}]")
            log_lines.append(f"    #{a['id']:>4}  {a['title'][:55]}  [{a['status']}]")

    if removed:
        print(f"\n  {BOLD}{RED}Removed objects ({len(removed)}){RESET}")
        log_lines.append(f"\n  Removed objects ({len(removed)})")
        for r in removed:
            print(f"    #{r['id']:>4}  {r['title'][:55]}")
            log_lines.append(f"    #{r['id']:>4}  {r['title'][:55]}")

    _log(log_lines)


# ── Core run ──────────────────────────────────────────────────────────────────

def run_once() -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{DIM}Fetching from {API_URL} …{RESET}", end=" ", flush=True)
    try:
        current = fetch_objects()
    except urllib.error.URLError as exc:
        msg = f"Network error: {exc}"
        print(f"\n{RED}{msg}{RESET}")
        _log([f"[{ts}] {msg}"])
        return

    print(f"got {len(current)} objects.")

    previous = load_snapshot()
    first_run = not previous

    if first_run:
        save_snapshot(current)
        msg = f"Snapshot created: {SNAPSHOT_CSV} ({len(current)} objects saved)"
        print(f"{GREEN}{msg}{RESET}")
        _log([f"[{ts}] {msg}"])
        return

    changed, added, removed = detect_changes(previous, current)
    report(changed, added, removed, len(current))
    save_snapshot(current)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor object status changes via CSV snapshot.")
    parser.add_argument(
        "--watch", "-w",
        metavar="SECONDS",
        type=int,
        default=None,
        help="Poll repeatedly every N seconds (omit to run once).",
    )
    args = parser.parse_args()

    if args.watch:
        print(f"{BOLD}Watching every {args.watch}s — Ctrl-C to stop{RESET}")
        try:
            while True:
                run_once()
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print(f"\n{DIM}Stopped.{RESET}")
    else:
        run_once()


if __name__ == "__main__":
    main()