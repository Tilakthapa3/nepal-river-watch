#!/usr/bin/env python3
"""Export the latest DHM river readings as a JSON snapshot.

The snapshot feeds the live flood board (flood-watch.html on
tilakthapa.com). It reuses fetch_rivers.py for the DHM request and
parsing, and watch.py's staleness rule: a reading older than 90 minutes
is stale, not silently treated as current.

Usage:
    python export_snapshot.py [output_path]   # default: rivers.json

Exits non-zero if the DHM request fails, so a scheduled job never
overwrites a good snapshot with an empty one.
"""

import json
import sys
from datetime import datetime, timezone, timedelta

import fetch_rivers as rw

NPT = timezone(timedelta(hours=5, minutes=45), "NPT")
STALE_MINUTES = 90


def is_stale(station, now):
    """Same rule as watch.py: older than 90 minutes counts as stale."""
    if not station["measured_at"]:
        return True
    try:
        measured = datetime.fromisoformat(station["measured_at"])
    except ValueError:
        return True
    if measured.tzinfo is None:
        measured = measured.replace(tzinfo=timezone.utc)
    return now - measured > timedelta(minutes=STALE_MINUTES)


def build_snapshot():
    stations, skipped = rw.fetch()
    now = datetime.now(timezone.utc)
    rows = []
    for s in stations:
        stale = is_stale(s, now)
        try:
            measured_npt = rw.to_npt(s["measured_at"])
        except Exception:
            measured_npt = s["measured_at"]
        rows.append({
            "id": s["station_id"],
            "name": s["name"],
            "basin": s["basin"],
            "district": s["district"],
            "water_level": s["water_level"],
            "warning_level": s["warning_level"],
            "danger_level": s["danger_level"],
            "trend": s["trend"],
            "status": s["status"],
            "measured_at": s["measured_at"],
            "measured_at_npt": measured_npt,
            "stale": stale,
            "severity": rw.severity(s),
            "margin_vs_warning": rw.margin(s),
            "station_url": rw.STATION_PAGE.format(s["station_id"]),
        })
    # Most urgent first: DANGER, then WARNING, then closest to warning.
    rank = {"DANGER": 0, "WARNING": 1, "NORMAL": 2}
    rows.sort(key=lambda r: (
        rank.get(r["severity"], 2),
        -(r["margin_vs_warning"]
          if r["margin_vs_warning"] is not None else float("-inf")),
        r["name"],
    ))
    return {
        "generated_at_utc": now.isoformat(),
        "generated_at_npt": now.astimezone(NPT).strftime("%Y-%m-%d %H:%M NPT"),
        "source": "Department of Hydrology and Meteorology (DHM), "
                  "Government of Nepal",
        "source_url": "https://dhm.gov.np/",
        "endpoint": rw.API_URL,
        "reporting": len(rows),
        "skipped": skipped,
        "fresh": sum(1 for r in rows if not r["stale"]),
        "stale": sum(1 for r in rows if r["stale"]),
        "warning": sum(1 for r in rows if r["severity"] == "WARNING"),
        "danger": sum(1 for r in rows if r["severity"] == "DANGER"),
        "stale_minutes": STALE_MINUTES,
        "stations": rows,
    }


def main(argv):
    out_path = argv[1] if len(argv) > 1 else "rivers.json"
    try:
        snapshot = build_snapshot()
    except Exception as e:
        print("Could not fetch DHM data: " + str(e), file=sys.stderr)
        return 1
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"Wrote {out_path}: {snapshot['reporting']} reporting, "
          f"{snapshot['fresh']} fresh, {snapshot['stale']} stale, "
          f"{snapshot['warning']} warning, {snapshot['danger']} danger.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
