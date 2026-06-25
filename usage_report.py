"""
IDMC MCP Server & AI Assistant — Usage Report

Fetches structured log events from Cloud Run and prints a summary
grouped by year-month.

Usage:
    python usage_report.py              # last 30 days
    python usage_report.py --days 7     # last 7 days
    python usage_report.py --days 90    # last 90 days
"""

import argparse
import json
import subprocess
import sys
from collections import defaultdict

SERVICES = {
    "idmc-mcp-server": 'textPayload:"USAGE"',
    "idmc-ai-assistant": 'textPayload:"USAGE"',
}


def fetch_logs(service: str, filter_str: str, days: int) -> list[dict]:
    log_filter = f"resource.type=cloud_run_revision AND resource.labels.service_name={service} AND {filter_str}"
    cmd = f'gcloud logging read "{log_filter}" --limit=2000 --freshness={days}d --format=json'
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    events = []
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return events

    for entry in entries:
        payload = entry.get("textPayload", "")
        if "USAGE " not in payload:
            continue
        json_str = payload[payload.index("USAGE ") + 6:].strip()
        if not json_str.startswith("{"):
            continue
        try:
            d = json.loads(json_str)
            ts = entry.get("timestamp", "0000-00-00")[:7]
            d["_ts"] = ts
            events.append(d)
        except json.JSONDecodeError:
            continue
    return events


def print_section(title: str, data: dict):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    if not data:
        print("  (no data)")
        return
    for ym in sorted(data.keys(), reverse=True):
        print(f"\n  {ym}")
        for key, count in sorted(data[ym].items(), key=lambda x: -x[1]):
            print(f"    {count:5d}  {key}")


def main():
    parser = argparse.ArgumentParser(description="IDMC usage report")
    parser.add_argument("--days", type=int, default=30, help="Number of days to look back (default: 30)")
    args = parser.parse_args()

    print(f"\nFetching logs for the last {args.days} days…\n")

    # ── MCP Server connections ────────────────────────────────────
    mcp_events = fetch_logs("idmc-mcp-server", SERVICES["idmc-mcp-server"], args.days)

    mcp_connects: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    mcp_enrolls: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for e in mcp_events:
        ym = e["_ts"]
        if e.get("event") == "enroll":
            key = f"{e.get('user','?')}  (pod: {e.get('pod','?')})"
            mcp_enrolls[ym][key] += 1
        elif e.get("event") == "mcp_connect":
            key = f"{e.get('user','?')}  (pod: {e.get('pod','?')})"
            mcp_connects[ym][key] += 1

    print_section("MCP Server — Token enrollments", mcp_enrolls)
    print_section("MCP Server — Connections by user", mcp_connects)

    # ── AI Assistant ─────────────────────────────────────────────
    ai_events = fetch_logs("idmc-ai-assistant", SERVICES["idmc-ai-assistant"], args.days)

    enrollments: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    chats: dict[str, dict] = defaultdict(lambda: defaultdict(int))

    for e in ai_events:
        ym = e["_ts"]
        if e.get("event") == "ui_connect":
            key = f"{e.get('user','?')}  [{e.get('org','?')}]  (pod: {e.get('pod','?')})"
            enrollments[ym][key] += 1
        elif e.get("event") == "ui_chat":
            key = f"{e.get('user','?')}  (pod: {e.get('pod','?')})"
            chats[ym][key] += 1

    print_section("AI Assistant — Enrollments / Token logins", enrollments)
    print_section("AI Assistant — Chat requests by user", chats)

    # ── Totals ───────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  TOTALS")
    print(f"{'='*60}")
    print(f"  Token enrollments:  {sum(1 for e in mcp_events if e.get('event')=='enroll'):5d}")
    print(f"  MCP connections:    {sum(1 for e in mcp_events if e.get('event')=='mcp_connect'):5d}")
    print(f"  AI UI logins:       {sum(1 for e in ai_events if e.get('event')=='ui_connect'):5d}")
    print(f"  AI chat requests:   {sum(1 for e in ai_events if e.get('event')=='ui_chat'):5d}")
    print()


if __name__ == "__main__":
    main()
