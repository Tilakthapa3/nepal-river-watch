# Nepal River Watch

Pulls live river gauge readings from Nepal's Department of Hydrology and
Meteorology, stores them, and flags stations at or above their official
warning and danger levels.

DHM publishes this data on its River Watch page, but only as a table you have
to go and look at. This tool fetches it programmatically so the readings can be
tracked over time and acted on — the first step toward alerting people
downstream rather than expecting them to check.

## Example output

```
Nepal time: 2026-08-27 11:28 NPT
196 stations reporting.

No stations above warning level.

Closest to threshold:
  -0.25m  Roshi Khola at Panauti
           Kavrepalanchok - measured 2026-08-27 11:20 NPT
  -0.36m  Nalgad at Raulakhet
           Jajarkot - measured 2026-08-27 11:00 NPT
  -0.54m  Lungri River at Khungri (327)
           Pyuthan - measured 2026-08-27 11:10 NPT

Stored 196 readings in rivers.db. Skipped 135 with no current reading.
```

When stations cross a threshold, they are listed with severity, trend,
measurement time, and a link to the official DHM page for that station.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests
python3 fetch_rivers.py
```

`--all` lists every reporting station, not just those near threshold.

Readings are stored in a local SQLite file (`rivers.db`), keyed on station and
measurement time, so repeated runs build a history without duplicating rows.

## Data source

Department of Hydrology and Meteorology, Government of Nepal —
https://dhm.gov.np/hydrology/river-watch

The page loads its table from an unauthenticated JSON endpoint, which is what
this tool calls. Roughly 330 stations appear in the feed; about 195 report a
current reading at any given time. Telemetry updates on a 15-minute cycle.

Historical archives are not in this feed — DHM gates those behind a data
request form.

## Notes on the data

Working with this feed surfaced a few things worth knowing:

**Gauges use different datums.** Some stations report elevation above sea level
(Kathmandu valley gauges read around 1300m), others report depth above the
riverbed (a few metres). A reading is only meaningful against that station's own
warning and danger levels, so severity is computed per station and readings are
never compared across stations.

**Field types are inconsistent.** `waterLevel` arrives as an object on
reporting stations and as a blank string on silent ones. Thresholds come back as
strings, sometimes empty. Everything is parsed defensively; stations with no
usable reading are skipped and counted rather than dropped silently.

**The API's own status field is unreliable.** Several records return blank or
truncated status values, so severity is derived from the numbers instead.

**Timestamps are UTC.** DHM publishes in UTC while Nepal runs at UTC+5:45.
Readings are stored in UTC and converted to Nepal time for display.

**Some stations go stale.** Most report within minutes; a few sit hours or days
behind. A stale reading currently shows as normal, which is a gap — see below.

## Roadmap

- Flag stale readings as unknown rather than normal
- Filter rain gauges out of the river station list
- Rate-of-rise detection using stored history
- Notifications for stations crossing thresholds

## Disclaimer

This is a personal project and is not affiliated with or endorsed by the
Department of Hydrology and Meteorology or the Government of Nepal. It is not a
substitute for official warnings. For authoritative information, refer to DHM
directly.