"""Check Nepal river levels and post alerts to Telegram."""

import html
import json
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta

import fetch_rivers as rw
import alert

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "last_alerted.json")
OUTAGE_FILE = os.path.join(BASE_DIR, "outage.json")
STALE_MINUTES = 90
WATCH_COUNT = 15
HEARTBEAT_MINUTES = 15
# Failed runs in a row before the channel hears about it. One blip stays
# quiet; a real outage is announced once, not on every run.
FAILURES_BEFORE_NOTICE = 2
NPT = timezone(timedelta(hours=5, minutes=45), "NPT")


def esc(text):
    """Station names can contain & or <, which break Telegram's HTML mode."""
    return html.escape(text, quote=False)


def is_stale(station):
    text = station["measured_at"]
    if not text:
        return True
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        measured = datetime.fromisoformat(text)
    except ValueError:
        return True
    if measured.tzinfo is None:
        # DHM publishes UTC, so read a time with no offset as UTC
        measured = measured.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - measured
    return age > timedelta(minutes=STALE_MINUTES)


def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_state():
    return load_json(STATE_FILE)


def save_state(state):
    save_json(STATE_FILE, state)


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
        lines.append("<b>" + rw.severity(s) + "</b> - " + esc(s["name"]))
        place = s["district"] or "unknown district"
        basin = s["basin"] or "unknown basin"
        lines.append(esc(place) + " | " + esc(basin))
        # Some stations have only a danger level, so list what exists
        parts = ["Level {:.2f}m".format(s["water_level"])]
        if s["warning_level"] is not None:
            parts.append("warning at {:.2f}m".format(s["warning_level"]))
        if s["danger_level"] is not None:
            parts.append("danger at {:.2f}m".format(s["danger_level"]))
        lines.append(", ".join(parts))
        lines.append("Trend: " + esc(s["trend"] or "unknown"))
        lines.append(rw.STATION_PAGE.format(s["station_id"]))
        lines.append("")

    lines.append("Source: DHM, Government of Nepal.")
    lines.append("Unofficial. Follow official warnings.")
    return "\n".join(lines)


def format_heartbeat(fresh, stale, skipped):
    lines = []
    lines.append("<b>River update</b>")
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
        for s in watch[:WATCH_COUNT]:
            gap = "{:+.2f}m".format(margin(s))
            lines.append("<b>" + gap + "</b>  " + esc(s["name"]))
            detail = "   {:.2f}m of {:.2f}m, {}".format(
                s["water_level"], s["warning_level"],
                esc(s["trend"] or "unknown"))
            lines.append(detail)
        lines.append("")

    lines.append("Source: DHM, Government of Nepal.")
    return "\n".join(lines)


def heartbeat_due():
    """Post an update every HEARTBEAT_MINUTES."""
    state = load_state()
    last = state.get("heartbeat_date")
    if not last:
        return True
    try:
        sent = datetime.fromisoformat(last)
    except ValueError:
        return True
    if sent.tzinfo is None:
        return True
    gap = npt_now() - sent
    return gap >= timedelta(minutes=0)


def mark_heartbeat():
    state = load_state()
    state["heartbeat_date"] = npt_now().isoformat()
    save_state(state)


def tell_admin(reason):
    """Send the technical reason to your private chat, if one is set up."""
    text = ("<b>River Watch failure</b>\n" +
            npt_now().strftime("%Y-%m-%d %H:%M NPT") + "\n" +
            esc(reason) + "\n\nFull traceback: watch.log on the server.")
    try:
        return alert.send_admin(text)
    except Exception:
        traceback.print_exc()
        print("Could not send the details to the admin chat.")
        return False


def post_outage_notice(outage):
    lines = [
        "<b>River Watch is down</b>",
        "Since " + rw.to_npt(outage.get("since")),
        "",
        "The river check is failing, so flood alerts may be missing.",
        "For official flood warnings, call DHM on 1155 (press 2).",
        "This channel will post again when it is working.",
    ]
    if not alert.ADMIN_CHAT:
        lines.append("")
        lines.append("Reason: " + esc(outage["reason"]))
    try:
        alert.send("\n".join(lines))
    except Exception:
        traceback.print_exc()
        print("Could not send the outage notice. Will retry next run.")
        return False
    print("Outage notice sent.")
    return True


def report_failure(exc):
    """Announce an outage once, after FAILURES_BEFORE_NOTICE failed runs."""
    outage = load_json(OUTAGE_FILE)
    if not outage:
        outage = {"since": npt_now().isoformat(), "failures": 0}
    outage["failures"] = outage.get("failures", 0) + 1
    outage["reason"] = alert.describe(exc)

    if outage.get("notified"):
        print("Still failing. The channel was already told.")
    elif outage["failures"] < FAILURES_BEFORE_NOTICE:
        print("Check failed. A notice goes out if the next run fails too.")
    else:
        if not outage.get("admin_told"):
            outage["admin_told"] = tell_admin(outage["reason"])
        outage["notified"] = post_outage_notice(outage)

    try:
        save_json(OUTAGE_FILE, outage)
    except OSError:
        print("Could not save the outage state.")


def report_recovery():
    """Once checks work again, close out any outage that was announced."""
    outage = load_json(OUTAGE_FILE)
    if not outage:
        return

    if outage.get("notified"):
        alert.send("<b>River Watch is back</b>\n" +
                   npt_now().strftime("%Y-%m-%d %H:%M NPT") + "\n\n" +
                   "Checks are running again. Down since " +
                   rw.to_npt(outage.get("since")) + ".")
        print("Recovery notice sent.")
    elif outage.get("admin_told"):
        alert.send_admin("River Watch is working again.")

    try:
        os.remove(OUTAGE_FILE)
    except OSError:
        pass


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

    # With no fresh readings, "all rivers below warning" would be a false
    # all-clear, so treat it as a failed check
    if not fresh:
        raise RuntimeError("DHM sent no fresh readings ({} stale, {} silent)"
                           .format(stale, skipped))

    report_recovery()

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
    except Exception as exc:
        traceback.print_exc()
        try:
            report_failure(exc)
        except Exception:
            traceback.print_exc()
            print("Could not record or report the failure.")
        sys.exit(1)


if __name__ == "__main__":
    main()
