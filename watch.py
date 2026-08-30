"""Check Nepal river levels and post alerts to Telegram."""

import json
import os
from datetime import datetime, timezone, timedelta

import fetch_rivers as rw
import alert

STATE_FILE = "last_alerted.json"
STALE_MINUTES = 90
NPT = timezone(timedelta(hours=5, minutes=45), "NPT")


def is_stale(station):
    if not station["measured_at"]:
        return True
    try:
        measured = datetime.fromisoformat(station["measured_at"])
    except ValueError:
        return True
    age = datetime.now(timezone.utc) - measured
    return age > timedelta(minutes=STALE_MINUTES)


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def format_alert(stations):
    now = datetime.now(NPT).strftime("%Y-%m-%d %H:%M NPT")
    lines = []
    lines.append("<b>River level alert</b>")
    lines.append(now)
    lines.append("")

    for s in stations:
        level = rw.severity(s)
        lines.append("<b>" + level + "</b> - " + s["name"])
        place = s["district"] or "unknown district"
        basin = s["basin"] or "unknown basin"
        lines.append(place + " | " + basin)
        reading = "Level {:.2f}m".format(s["water_level"])
        limit = "warning at {:.2f}m".format(s["warning_level"])
        lines.append(reading + ", " + limit)
        lines.append("Trend: " + (s["trend"] or "unknown"))
        lines.append(rw.STATION_PAGE.format(s["station_id"]))
        lines.append("")

    lines.append("Source: DHM, Government of Nepal.")
    lines.append("Unofficial. Follow official warnings.")
    return "\n".join(lines)


def main():
    stations, skipped = rw.fetch()

    fresh = []
    for s in stations:
        if not is_stale(s):
            fresh.append(s)
    stale = len(stations) - len(fresh)

    alerting = []
    for s in fresh:
        if rw.severity(s) != "NORMAL":
            alerting.append(s)

    conn = rw.init_db()
    rw.store(conn, stations)
    conn.close()

    summary = "{} reporting, {} fresh, {} stale, {} skipped"
    print(summary.format(len(stations), len(fresh), stale, skipped))

    if not alerting:
        print("Nothing above warning level.")
        save_state({})
        return

    state = load_state()
    current = {}
    for s in alerting:
        current[str(s["station_id"])] = rw.severity(s)

    if current == state:
        print("Same as last run. Not resending.")
        return

    alerting.sort(key=lambda s: rw.severity(s) != "DANGER")
    alert.send(format_alert(alerting))
    save_state(current)
    print("Alert sent for " + str(len(alerting)) + " station(s).")


if __name__ == "__main__":
    main()