"""
Export pub_names.csv to PINtPOINT Venue format (TypeScript/JSON).

Reads the enriched pub_names.csv and outputs venue objects ready to paste
into data/venues.ts in the rork-pintpoint app.

Usage:
    python export_venues.py              # TypeScript array to stdout
    python export_venues.py --json       # JSON array to stdout
    python export_venues.py --json -o venues.json  # JSON to file
"""

import csv
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PUB_NAMES_CSV = SCRIPT_DIR / "pub_names.csv"

# Map our category names to PINtPOINT fpi_severity enum values
SEVERITY_MAP = {
    "somehow fine": "fine",
    "feeling it": "feeling_it",
    "struggling": "struggling",
    "fucked": "fucked",
    "absolutely fucked": "absolutely_fucked",
}

START_ID = 1061


def load_pubs():
    with open(PUB_NAMES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pub_to_venue(pub, venue_id):
    """Convert a pub_names.csv row to a PINtPOINT Venue dict."""
    name = pub["pub_name"]
    location = pub.get("location", "")
    postcode_area = pub.get("postcode_area", "")

    # Address: "Broadway Market, London E8"
    address = location
    if postcode_area:
        address = f"{address} {postcode_area}".strip()

    # Neighbourhood: first part of location before comma
    parts = location.split(",")
    neighborhood = parts[0].strip() if parts else postcode_area

    # Coordinates from Flickr geotags (0 if not available)
    lat = float(pub["photo_lat"]) if pub.get("photo_lat") else 0
    lng = float(pub["photo_lng"]) if pub.get("photo_lng") else 0

    # FPI data
    fpi_score = int(pub["fpi_score"]) if pub.get("fpi_score") else 0
    fpi_cat = pub.get("fpi_category", "")
    severity = SEVERITY_MAP.get(fpi_cat)
    pct_change = float(pub["fpi_pct_change"]) if pub.get("fpi_pct_change") else None

    # Flickr photo
    photo_url = pub.get("photo_url", "")

    venue = {
        "id": f"v{venue_id}",
        "name": name,
        "neighborhood": neighborhood,
        "address": address,
        "latitude": lat,
        "longitude": lng,
        "rating": 0,
        "city": "London",
        "closedDown": True,
        "tags": ["ghost pub"],
        "fpi": fpi_score,
        "beers": [],
    }

    if severity:
        venue["fpi_severity"] = severity
    if pct_change is not None:
        venue["rv_change_pct"] = pct_change
    if photo_url:
        venue["historicalPhotos"] = [{
            "url": photo_url,
            "credit": "Flickr: Ewan Munro",
            "creditUrl": "https://www.flickr.com/photos/55935853@N00/",
        }]

    return venue


def format_ts_value(val):
    """Format a Python value as TypeScript literal."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, str):
        # Escape single quotes for TS
        escaped = val.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        if not val:
            return "[]"
        items = ", ".join(format_ts_value(v) for v in val)
        return f"[{items}]"
    if isinstance(val, dict):
        pairs = []
        for k, v in val.items():
            pairs.append(f"{k}: {format_ts_value(v)}")
        return "{ " + ", ".join(pairs) + " }"
    return repr(val)


def venue_to_ts(venue):
    """Convert a venue dict to a TypeScript object literal string."""
    lines = ["  {"]
    for key, val in venue.items():
        lines.append(f"    {key}: {format_ts_value(val)},")
    lines.append("  },")
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Export pubs to PINtPOINT venue format")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of TypeScript")
    parser.add_argument("-o", "--output", help="Write to file instead of stdout")
    parser.add_argument("--start-id", type=int, default=START_ID,
                        help=f"Starting venue ID number (default: {START_ID})")
    args = parser.parse_args()

    pubs = load_pubs()
    if not pubs:
        print("No pubs found in CSV.", file=sys.stderr)
        sys.exit(1)

    venues = []
    for i, pub in enumerate(pubs):
        venue = pub_to_venue(pub, args.start_id + i)
        venues.append(venue)

    if args.json:
        output = json.dumps(venues, indent=2)
    else:
        venue_lines = [venue_to_ts(v) for v in venues]
        output = "// Ghost pubs from Flickr + VOA data\n"
        output += "// Paste into data/venues.ts\n"
        output += "[\n" + "\n".join(venue_lines) + "\n]"

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Wrote {len(venues)} venues to {args.output}", file=sys.stderr)
    else:
        print(output)

    print(f"\n// {len(venues)} ghost pubs exported (IDs v{args.start_id}–v{args.start_id + len(venues) - 1})",
          file=sys.stderr)


if __name__ == "__main__":
    main()
