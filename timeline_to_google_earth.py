#!/usr/bin/env python3
"""
timeline_to_google_earth.py - Convert a Google Timeline export to a Google Earth KML file.

Supported input formats (auto-detected):
  * Android on-device export   (Timeline.json   - "semanticSegments" / "rawSignals")
  * iOS on-device export       (location-history.json - list of segments, "geo:" points)
  * Old Takeout Records.json   ("locations" with latitudeE7/longitudeE7)
  * Old Takeout Semantic Location History monthly files ("timelineObjects")

Output: one KML with a folder per day, containing visited places (pins) and the
route travelled (line), all time-stamped so Google Earth's time slider works.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

DEFAULT_INPUTS = ["Settings.json", "Timeline.json", "location-history.json", "Records.json"]

HELP_EPILOG = """\
examples:
  timeline_to_google_earth.py -s 2024-06-01 -e 2024-06-30
      Export June 2024 (both dates inclusive).

  timeline_to_google_earth.py -s 2024-06-01
      Export from 1 June 2024 to the last record in the file.

  timeline_to_google_earth.py -e 2024-06-30
      Export from the first record in the file up to 30 June 2024.

  timeline_to_google_earth.py -a
      Export everything in the file.

  timeline_to_google_earth.py -s 2024-06-01 -e 2024-06-07 -i Timeline.json -o week.kml
      Choose the input file and output file names.

what to show (-show), default is pins only:
  -show pins                   place pins only (same as the default)
  -show routes                 route lines only
  -show pins routes            pins and route lines
  -show pins labels            pins with time/place text labels
  -show all_details            pins, labels and route lines (the lot)
  Items can also be comma-separated, e.g. -show pins,routes
  Without labels, click a pin in Google Earth to see its time and place.

notes:
  If -i is not given, the script looks in the current directory for:
  Settings.json, Timeline.json, location-history.json, Records.json (first found).
  Open the resulting .kml in Google Earth (File > Open / Import KML).
"""

# --------------------------------------------------------------------------- helpers

FLOAT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def parse_time(value):
    """Parse ISO-8601 strings or epoch-ms values into an aware datetime."""
    if value is None:
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Trim fractional seconds to 6 digits for older Python versions
    m = re.match(r"^(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$", s)
    if m:
        frac = (m.group(2) or "")[:7]
        s = m.group(1) + frac + m.group(3)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_latlng(value):
    """Accepts '51.5°, -0.12°', 'geo:51.5,-0.12', {'latitudeE7':..}, {'latLng': ..}."""
    if value is None:
        return None
    if isinstance(value, dict):
        if "latitudeE7" in value and "longitudeE7" in value:
            return value["latitudeE7"] / 1e7, value["longitudeE7"] / 1e7
        if "latE7" in value and "lngE7" in value:
            return value["latE7"] / 1e7, value["lngE7"] / 1e7
        for key in ("latLng", "LatLng", "point", "placeLocation", "location"):
            if key in value:
                return parse_latlng(value[key])
        return None
    nums = FLOAT_RE.findall(str(value))
    if len(nums) >= 2:
        lat, lng = float(nums[0]), float(nums[1])
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return lat, lng
    return None


def kml_time(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nice(text):
    return str(text).replace("_", " ").title() if text else ""


# --------------------------------------------------------------------------- data model

class Collector:
    def __init__(self, start, end):
        self.start, self.end = start, end
        self.visits = defaultdict(list)   # date -> [dict]
        self.points = defaultdict(list)   # date -> [(dt, lat, lng)]
        self.activities = defaultdict(list)  # date -> [dict]
        self.last_date_seen = None

    def in_range(self, dt):
        if dt is None:
            return False
        d = dt.date()  # local date of the record (uses its own UTC offset)
        if self.last_date_seen is None or d > self.last_date_seen:
            self.last_date_seen = d
        return (self.start is None or self.start <= d) and (self.end is None or d <= self.end)

    def add_point(self, dt, ll):
        if ll and self.in_range(dt):
            self.points[dt.date()].append((dt, ll[0], ll[1]))

    def add_visit(self, start, end, ll, name, detail=""):
        if ll and self.in_range(start):
            self.visits[start.date()].append(
                {"start": start, "end": end or start, "ll": ll, "name": name, "detail": detail})

    def add_activity(self, start, end, kind, distance):
        if self.in_range(start):
            self.activities[start.date()].append(
                {"start": start, "end": end or start, "kind": kind, "distance": distance})

    def days(self):
        return sorted(set(self.visits) | set(self.points))


# --------------------------------------------------------------------------- parsers

def parse_android(data, c):
    """Android on-device export: semanticSegments + rawSignals."""
    for seg in data.get("semanticSegments", []):
        st, et = parse_time(seg.get("startTime")), parse_time(seg.get("endTime"))
        if "visit" in seg:
            top = seg["visit"].get("topCandidate", {})
            ll = parse_latlng(top.get("placeLocation"))
            name = nice(top.get("semanticType")) or "Visit"
            detail = f"Place ID: {top['placeId']}" if top.get("placeId") else ""
            c.add_visit(st, et, ll, name, detail)
            if ll:
                c.add_point(st, ll)
                c.add_point(et, ll)
        if "activity" in seg:
            act = seg["activity"]
            c.add_activity(st, et, act.get("topCandidate", {}).get("type"), act.get("distanceMeters"))
            c.add_point(st, parse_latlng(act.get("start")))
            c.add_point(et, parse_latlng(act.get("end")))
        for p in seg.get("timelinePath", []):
            c.add_point(parse_time(p.get("time")), parse_latlng(p.get("point")))
    for sig in data.get("rawSignals", []):
        pos = sig.get("position")
        if pos:
            c.add_point(parse_time(pos.get("timestamp")), parse_latlng(pos.get("LatLng") or pos.get("latLng")))


def parse_ios(data, c):
    """iOS on-device export: a top-level list of segments with 'geo:' strings."""
    for seg in data:
        st, et = parse_time(seg.get("startTime")), parse_time(seg.get("endTime"))
        if "visit" in seg:
            top = seg["visit"].get("topCandidate", {})
            ll = parse_latlng(top.get("placeLocation"))
            name = nice(top.get("semanticType")) or "Visit"
            detail = f"Place ID: {top['placeID']}" if top.get("placeID") else ""
            c.add_visit(st, et, ll, name, detail)
            if ll:
                c.add_point(st, ll)
                c.add_point(et, ll)
        if "activity" in seg:
            act = seg["activity"]
            dist = act.get("distanceMeters")
            c.add_activity(st, et, act.get("topCandidate", {}).get("type"),
                           float(dist) if dist else None)
            c.add_point(st, parse_latlng(act.get("start")))
            c.add_point(et, parse_latlng(act.get("end")))
        for p in seg.get("timelinePath", []):
            if st is None:
                continue
            offset = float(p.get("durationMinutesOffsetFromStartTime", 0) or 0)
            c.add_point(st + timedelta(minutes=offset), parse_latlng(p.get("point")))


def parse_records(data, c):
    """Old Takeout Records.json."""
    for loc in data.get("locations", []):
        dt = parse_time(loc.get("timestamp") or loc.get("timestampMs"))
        c.add_point(dt, parse_latlng(loc))


def parse_semantic(data, c):
    """Old Takeout Semantic Location History (timelineObjects)."""
    for obj in data.get("timelineObjects", []):
        if "placeVisit" in obj:
            pv = obj["placeVisit"]
            loc = pv.get("location", {})
            dur = pv.get("duration", {})
            st = parse_time(dur.get("startTimestamp") or dur.get("startTimestampMs"))
            et = parse_time(dur.get("endTimestamp") or dur.get("endTimestampMs"))
            ll = parse_latlng(loc)
            c.add_visit(st, et, ll, loc.get("name") or "Visit", loc.get("address", ""))
            if ll:
                c.add_point(st, ll)
                c.add_point(et, ll)
        if "activitySegment" in obj:
            a = obj["activitySegment"]
            dur = a.get("duration", {})
            st = parse_time(dur.get("startTimestamp") or dur.get("startTimestampMs"))
            et = parse_time(dur.get("endTimestamp") or dur.get("endTimestampMs"))
            c.add_activity(st, et, a.get("activityType"), a.get("distance"))
            c.add_point(st, parse_latlng(a.get("startLocation")))
            raw = a.get("simplifiedRawPath", {}).get("points", [])
            if raw:
                for p in raw:
                    c.add_point(parse_time(p.get("timestamp") or p.get("timestampMs")), parse_latlng(p))
            else:
                wps = a.get("waypointPath", {}).get("waypoints", [])
                if st and et and wps:
                    step = (et - st) / max(len(wps) + 1, 1)
                    for i, w in enumerate(wps, 1):
                        c.add_point(st + step * i, parse_latlng(w))
            c.add_point(et, parse_latlng(a.get("endLocation")))


def detect_and_parse(data, c):
    if isinstance(data, list):
        parse_ios(data, c)
        return "iOS Timeline export"
    if isinstance(data, dict):
        if "semanticSegments" in data or "rawSignals" in data:
            parse_android(data, c)
            return "Android Timeline export"
        if "locations" in data:
            parse_records(data, c)
            return "Takeout Records.json"
        if "timelineObjects" in data:
            parse_semantic(data, c)
            return "Takeout Semantic Location History"
    return None


# --------------------------------------------------------------------------- KML output

KML_HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>{title}</name>
  <Style id="visit">
    <IconStyle><scale>1.0</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/paddle/red-circle.png</href></Icon>
    </IconStyle>
    <LabelStyle><scale>{label_scale}</scale></LabelStyle>
  </Style>
  <Style id="route">
    <LineStyle><color>ff0000ff</color><width>3</width></LineStyle>
    <LabelStyle><scale>0</scale></LabelStyle>
  </Style>
"""


def day_name(d):
    return f"{d.isoformat()} ({d.strftime('%A')})"


def write_kml(c, path, title, pins=True, labels=False, routes=False):
    out = [KML_HEAD.format(title=escape(title), label_scale=1 if labels else 0)]

    # ---- Places (pins), one sub-folder per day
    if pins:
        out.append("  <Folder>\n    <name>Places</name>\n")
    for d in (c.days() if pins else []):
        visits = sorted(c.visits.get(d, []), key=lambda x: x["start"])
        if not visits:
            continue
        out.append(f"    <Folder>\n      <name>{day_name(d)}</name>\n")
        for v in visits:
            lat, lng = v["ll"]
            desc = (f"{v['start'].strftime('%Y-%m-%d %H:%M')} - {v['end'].strftime('%H:%M')}"
                    + (f"<br/>{escape(v['detail'])}" if v["detail"] else ""))
            out.append(
                "      <Placemark>\n"
                f"        <name>{escape(v['start'].strftime('%H:%M'))} {escape(v['name'])}</name>\n"
                f"        <description><![CDATA[{desc}]]></description>\n"
                f"        <TimeSpan><begin>{kml_time(v['start'])}</begin><end>{kml_time(v['end'])}</end></TimeSpan>\n"
                "        <styleUrl>#visit</styleUrl>\n"
                f"        <Point><coordinates>{lng:.7f},{lat:.7f},0</coordinates></Point>\n"
                "      </Placemark>\n")
        out.append("    </Folder>\n")
    if pins:
        out.append("  </Folder>\n")

    # ---- Routes (lines), one per day
    if routes:
        out.append("  <Folder>\n    <name>Routes</name>\n")
        for d in c.days():
            pts = sorted(set(c.points.get(d, [])))
            if len(pts) < 2:
                continue
            acts = c.activities.get(d, [])
            dist = sum(a["distance"] or 0 for a in acts)
            kinds = sorted({nice(a["kind"]) for a in acts if a["kind"]})
            desc = f"{len(pts)} points"
            if dist:
                desc += f"<br/>Distance: {dist / 1000:.1f} km"
            if kinds:
                desc += f"<br/>Activities: {escape(', '.join(kinds))}"
            coords = " ".join(f"{lng:.7f},{lat:.7f},0" for _, lat, lng in pts)
            out.append(
                "    <Placemark>\n"
                f"      <name>Route {day_name(d)}</name>\n"
                f"      <description><![CDATA[{desc}]]></description>\n"
                f"      <TimeSpan><begin>{kml_time(pts[0][0])}</begin><end>{kml_time(pts[-1][0])}</end></TimeSpan>\n"
                "      <styleUrl>#route</styleUrl>\n"
                "      <LineString><tessellate>1</tessellate>\n"
                f"        <coordinates>{coords}</coordinates>\n"
                "      </LineString>\n"
                "    </Placemark>\n")
        out.append("  </Folder>\n")

    out.append("</Document>\n</kml>\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(out))


# --------------------------------------------------------------------------- main

def valid_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date '{s}' - use YYYY-MM-DD")


def main():
    parser = argparse.ArgumentParser(
        prog="timeline_to_google_earth.py",
        description="Convert a Google Timeline export (JSON) into a Google Earth KML file "
                    "for a given date range.",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-s", "--start", metavar="YYYY-MM-DD", type=valid_date,
                        help="start date (inclusive). If omitted, starts from the first record")
    parser.add_argument("-e", "--end", metavar="YYYY-MM-DD", type=valid_date,
                        help="end date (inclusive). If omitted, runs to the last record")
    parser.add_argument("-a", "--all", action="store_true",
                        help="export every record in the file (same as no -s and no -e)")
    parser.add_argument("-i", "--input", metavar="FILE",
                        help="Timeline JSON file (default: first of %s found)" % ", ".join(DEFAULT_INPUTS))
    parser.add_argument("-o", "--output", metavar="FILE",
                        help="output KML file (default: timeline_START_to_END.kml)")
    parser.add_argument("-show", "--show", metavar="ITEM", nargs="+", default=["pins"],
                        help="what to include: any of pins, routes, labels, all_details "
                             "(default: pins). See 'what to show' below")

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)
    args = parser.parse_args()

    show = set()
    for item in args.show:
        for part in item.lower().split(","):
            part = part.strip()
            if not part:
                continue
            if part in ("all_details", "all"):
                show |= {"pins", "labels", "routes"}
            elif part in ("pins", "pin", "routes", "route", "labels", "label"):
                show.add(part.rstrip("s") + "s")
            else:
                parser.error(f"unknown -show item '{part}' "
                             "(choose from: pins, routes, labels, all_details)")
    if "labels" in show and "pins" not in show:
        show.add("pins")  # labels belong to pins
    if not show:
        show = {"pins"}

    if not (args.start or args.end or args.all):
        parser.error("give -s and/or -e, or -a for the whole file (see -h)")
    if args.start and args.end and args.end < args.start:
        parser.error("end date is before start date")

    infile = args.input
    if not infile:
        infile = next((f for f in DEFAULT_INPUTS if os.path.isfile(f)), None)
        if not infile:
            parser.error("no input file given and none of %s found" % ", ".join(DEFAULT_INPUTS))
    if not os.path.isfile(infile):
        parser.error(f"input file not found: {infile}")

    print(f"Reading {infile} ...")
    try:
        with open(infile, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        sys.exit(f"Error: {infile} is not valid JSON ({exc})")

    c = Collector(args.start, args.end)
    fmt = detect_and_parse(data, c)
    if fmt is None:
        keys = ", ".join(list(data.keys())[:10]) if isinstance(data, dict) else type(data).__name__
        sys.exit(
            f"Error: no location data found in {infile} (top-level keys: {keys}).\n"
            "A Google Takeout 'Settings.json' usually contains only Timeline settings.\n"
            "Export the data from your phone instead:\n"
            "  Android: Settings > Location > Location services > Timeline > Export Timeline data\n"
            "  iPhone : Google Maps > Your Timeline > ... > Location & privacy settings > Export Timeline data")
    print(f"Detected format: {fmt}")

    days = c.days()
    if not days:
        last = f" Last record in file is {c.last_date_seen}." if c.last_date_seen else ""
        sys.exit(f"No records between {args.start or 'start of data'} and "
                 f"{args.end or 'end of data'}.{last}")

    start_label = args.start or days[0]
    end_label = args.end or days[-1]
    outfile = args.output or f"timeline_{start_label}_to_{end_label}.kml"
    title = f"Google Timeline {start_label} to {end_label}"
    write_kml(c, outfile, title, pins="pins" in show, labels="labels" in show,
              routes="routes" in show)
    print("Showing: " + ", ".join(i for i in ("pins", "labels", "routes") if i in show))

    n_visits = sum(len(v) for v in c.visits.values())
    n_points = sum(len(p) for p in c.points.values())
    print(f"Days: {len(days)}  Visits: {n_visits}  Route points: {n_points}")
    print(f"Written: {outfile}")


if __name__ == "__main__":
    main()
