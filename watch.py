"""Check Nepal river levels and post alerts to Telegram."""

import json
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta

import fetch_rivers as rw
import alert

STATE_FILE = "last_alerted.json"
STALE_MINUTES = 90
HEARTBEAT_HOUR = 8
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


def npt_now():
    return datetime.now(NPT)


def margin(s):
    if s["warning_level"] is None:
        return None
    return s["water_level"] - s["warning_level"]


def format_alert(stations):
    lines = []
    lines.append("<b>River level alert</b>")
    lines.append(npt_now().strftime("%Y-%m-%d %H:%M NPT"))
    lines.append("")

    for s in stations:
        lines.append("<b>" + rw.severity(s) + "</b> - " + s["name"])
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


def format_heartbeat(fresh, stale, skipped):
    lines = []
    lines.append("<b>Daily check</b>")
    lines.append(npt_now().strftime("%Y-%m-%d %H:%M NPT"))
    lines.append("")
    lines.append("All rivers below warning level.")
    lines.append("")
    counts = "{} stations reporting, {} stale, {} silent"
    lines.append(counts.format(len(fresh), stale, skipped))
    lines.append("")

    watch = []
    for s in fresh:
        if margin(s) is not None:
            watch.append(s)
    watch.sort(key=margin, reverse=True)

    if watch:
        lines.append("Closest to threshold:")
        for s in watch[:3]:
            gap = "{:+.2f}m".format(margin(s))
            lines.append(gap + "  " + s["name"])
        lines.append("")

    lines.append("Source: DHM, Government of Nepal.")
    return "\n".join(lines)


def heartbeat_due():
    """One heartbeat per day, at the first run after HEARTBEAT_HOUR NPT."""
    today = npt_now().strftime("%Y-%m-%d")
    state = load_state()
    if state.get("heartbeat_date") == today:
        return False
    return npt_now().hour >= HEARTBEAT_HOUR


def mark_heartbeat():
    state = load_state()
    state["heartbeat_date"] = npt_now().strftime("%Y-%m-%d")
    save_state(state)


def run():
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

    state = load_state()

    if alerting:
        current = {}
        for s in alerting:
            current[str(s["station_id"])] = rw.severity(s)

        previous = {}
        for key, value in state.items():
            if key != "heartbeat_date":
                previous[key] = value

        if current == previous:
            print("Same as last run. Not resending.")
            return

        alerting.sort(key=lambda s: rw.severity(s) != "DANGER")
        alert.send(format_alert(alerting))

        current["heartbeat_date"] = state.get("heartbeat_date", "")
        save_state(current)
        print("Alert sent for " + str(len(alerting)) + " station(s).")
        return

    print("Nothing above warning level.")
    save_state({"heartbeat_date": state.get("heartbeat_date", "")})

    if heartbeat_due():
        alert.send(format_heartbeat(fresh, stale, skipped))
        mark_heartbeat()
        print("Heartbeat sent.")


def main():
    try:
        run()
    except Exception:
        traceback.print_exc()
        try:
            when = npt_now().strftime("%Y-%m-%d %H:%M NPT")
            alert.send("<b>River Watch error</b>\n" + when +
                       "\nThe check failed. Alerts may be missing.")
        except Exception:
            print("Could not send the failure notice either.")
        sys.exit(1)


if __name__ == "__main__":
    main()