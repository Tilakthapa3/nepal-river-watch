import sys
import sqlite3
from datetime import datetime, timezone, timedelta

import requests

API_URL = "https://dhm.gov.np/site/riverWatchTableViewData"
STATION_PAGE = "https://dhm.gov.np/hydrology/hms-Single/{}"
DB_PATH = "rivers.db"
TIMEOUT = 30

# Nepal Standard Time is UTC+5:45, no daylight saving
NPT = timezone(timedelta(hours=5, minutes=45), "NPT")

SCHEMA = """
CREATE TABLE IF NOT EXISTS reading (
    station_id    INTEGER NOT NULL,
    name          TEXT    NOT NULL,
    basin         TEXT,
    district      TEXT,
    water_level   REAL,
    warning_level REAL,
    danger_level  REAL,
    min_value     REAL,
    max_value     REAL,
    trend         TEXT,
    status        TEXT,
    measured_at   TEXT,
    fetched_at    TEXT    NOT NULL,
    PRIMARY KEY (station_id, measured_at)
);
CREATE INDEX IF NOT EXISTS idx_reading_status ON reading (status);
"""


def init_db(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def to_npt(iso_string):
    """Render a DHM timestamp in Nepal local time."""
    if not iso_string:
        return "unknown"
    try:
        return datetime.fromisoformat(iso_string).astimezone(NPT).strftime(
            "%Y-%m-%d %H:%M NPT")
    except ValueError:
        return iso_string


def to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    value = str(value).strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_station(raw):
    level_field = raw.get("waterLevel")
    if isinstance(level_field, dict):
        water_level = to_float(level_field.get("value"))
        measured_at = (level_field.get("datetime") or "").strip()
    else:
        water_level = None
        measured_at = ""

    if water_level is None:
        return None

    return {
        "station_id": raw.get("id"),
        "name": (raw.get("name") or "").strip(),
        "basin": (raw.get("basin") or "").strip() or None,
        "district": (raw.get("district") or "").strip() or None,
        "water_level": water_level,
        "warning_level": to_float(raw.get("warning_level")),
        "danger_level": to_float(raw.get("danger_level")),
        "min_value": to_float(raw.get("minvalue")),
        "max_value": to_float(raw.get("maxvalue")),
        "trend": (raw.get("steady") or "").strip() or None,
        "status": (raw.get("status") or "").strip() or None,
        "measured_at": measured_at,
    }


def fetch():
    resp = requests.post(API_URL, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("status") != "success":
        raise RuntimeError("API returned status: " + str(payload.get("status")))

    stations = []
    skipped = 0
    for raw in payload.get("data", []):
        parsed = parse_station(raw)
        if parsed:
            stations.append(parsed)
        else:
            skipped += 1

    return stations, skipped


def severity(s):
    """Compare against the station's own thresholds. Gauges use different
    datums (some elevation above sea level, some depth above bed), so a
    reading only means anything relative to that station's own levels."""
    level = s["water_level"]
    if s["danger_level"] is not None and level >= s["danger_level"]:
        return "DANGER"
    if s["warning_level"] is not None and level >= s["warning_level"]:
        return "WARNING"
    return "NORMAL"


def store(conn, stations):
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            s["station_id"], s["name"], s["basin"], s["district"],
            s["water_level"], s["warning_level"], s["danger_level"],
            s["min_value"], s["max_value"],
            s["trend"], severity(s), s["measured_at"], now,
        )
        for s in stations
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO reading "
        "(station_id, name, basin, district, water_level, warning_level, "
        "danger_level, min_value, max_value, trend, status, measured_at, "
        "fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return len(rows)


def margin(s):
    if s["warning_level"] is None:
        return None
    return s["water_level"] - s["warning_level"]


def report(stations, show_all=False):
    alerts = [s for s in stations if severity(s) != "NORMAL"]
    alerts.sort(key=lambda s: (severity(s) != "DANGER", s["name"]))

    print("")
    print("Nepal time: " + datetime.now(NPT).strftime("%Y-%m-%d %H:%M NPT"))
    print(str(len(stations)) + " stations reporting.")
    print("")

    if not alerts:
        print("No stations above warning level.")
        print("")
        print("Closest to threshold:")
        watch = [s for s in stations if margin(s) is not None]
        watch.sort(key=lambda s: margin(s), reverse=True)
        for s in watch[:5]:
            print("  {:+.2f}m  {}".format(margin(s), s["name"]))
            print("           " + (s["district"] or "unknown district") +
                  " - measured " + to_npt(s["measured_at"]))
    else:
        print(str(len(alerts)) + " station(s) at or above warning level:")
        print("")
        for s in alerts:
            print("  [" + severity(s) + "] " + s["name"])
            print("      " + (s["district"] or "unknown district") +
                  " - " + (s["basin"] or "unknown basin"))
            print("      {:.2f}m".format(s["water_level"]) +
                  " ({:+.2f}m vs warning)".format(margin(s)) +
                  " - trend: " + (s["trend"] or "unknown"))
            print("      measured " + to_npt(s["measured_at"]))
            print("      " + STATION_PAGE.format(s["station_id"]))
            print("")

    if show_all:
        print("")
        print("All reporting stations:")
        print("")
        for s in sorted(stations, key=lambda x: x["name"]):
            print("  {:>10.2f}  {:<8} {}".format(
                s["water_level"], severity(s), s["name"]))


def main():
    show_all = "--all" in sys.argv

    try:
        stations, skipped = fetch()
    except requests.RequestException as e:
        print("Could not reach DHM: " + str(e))
        sys.exit(1)
    except (ValueError, RuntimeError) as e:
        print("Unexpected response: " + str(e))
        sys.exit(1)

    conn = init_db()
    stored = store(conn, stations)
    conn.close()

    report(stations, show_all)
    print("")
    print("Stored " + str(stored) + " readings in " + DB_PATH +
          ". Skipped " + str(skipped) + " with no current reading.")
    print("Source: Department of Hydrology and Meteorology, Government of Nepal")


if __name__ == "__main__":
    main()