"""
Fetch geotag coordinates from Flickr for each pub photo in pub_names.csv.

Extracts photo IDs from the staticflickr.com URLs in the photo_url column,
calls the Flickr API to get latitude/longitude, and adds those columns to
the CSV.

Usage:
    python fetch_geotags.py

    Requires a .env file with: FLICKR_API_KEY=your_key_here
"""

import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PUB_NAMES_CSV = SCRIPT_DIR / "pub_names.csv"

FLICKR_API_URL = "https://api.flickr.com/services/rest/"


def load_env():
    env_path = SCRIPT_DIR / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()


def flickr_api_call(method, **kwargs):
    params = {
        "method": method,
        "api_key": os.environ["FLICKR_API_KEY"],
        "format": "json",
        "nojsoncallback": 1,
        **kwargs,
    }
    url = FLICKR_API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def extract_photo_id(url):
    """Extract photo ID from a staticflickr URL.

    URLs look like: https://live.staticflickr.com/{server}/{photo_id}_{secret}.jpg
    or: https://farm{N}.staticflickr.com/{server}/{photo_id}_{secret}_{size}.jpg
    """
    if not url:
        return None
    m = re.search(r"staticflickr\.com/\d+/(\d+)_", url)
    return m.group(1) if m else None


def get_photo_location(photo_id):
    """Fetch geotag for a photo. Returns (lat, lng) or (None, None)."""
    try:
        data = flickr_api_call("flickr.photos.getInfo", photo_id=photo_id)
        if data.get("stat") != "ok":
            return None, None
        location = data.get("photo", {}).get("location", {})
        lat = location.get("latitude")
        lng = location.get("longitude")
        if lat and lng and lat != "0" and lng != "0":
            return lat, lng
    except Exception as e:
        print(f"  Error fetching photo {photo_id}: {e}")
    return None, None


def main():
    load_env()

    if not os.environ.get("FLICKR_API_KEY"):
        print("Error: FLICKR_API_KEY not found.")
        print("Create a .env file with: FLICKR_API_KEY=your_key_here")
        sys.exit(1)

    if not PUB_NAMES_CSV.exists():
        print(f"Error: {PUB_NAMES_CSV} not found.")
        sys.exit(1)

    with open(PUB_NAMES_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        pubs = list(reader)

    print(f"Loaded {len(pubs)} pubs from {PUB_NAMES_CSV}")

    geo_found = 0
    geo_skipped = 0

    for pub in pubs:
        name = pub["pub_name"]

        # Skip if already has coordinates
        if pub.get("latitude") and pub["latitude"] != "0":
            print(f"  {name}: already has coordinates, skipping")
            geo_skipped += 1
            continue

        photo_url = pub.get("photo_url", "")
        photo_id = extract_photo_id(photo_url)

        if not photo_id:
            print(f"  {name}: no photo ID in URL '{photo_url}'")
            pub.setdefault("latitude", "")
            pub.setdefault("longitude", "")
            continue

        lat, lng = get_photo_location(photo_id)

        if lat and lng:
            pub["latitude"] = str(lat)
            pub["longitude"] = str(lng)
            print(f"  {name}: {lat}, {lng}")
            geo_found += 1
        else:
            pub["latitude"] = ""
            pub["longitude"] = ""
            print(f"  {name}: no geotag")

        time.sleep(0.5)  # Rate limiting

    # Determine fieldnames — preserve existing, add lat/lng if missing
    fieldnames = list(pubs[0].keys()) if pubs else []
    for col in ["latitude", "longitude"]:
        if col not in fieldnames:
            fieldnames.append(col)

    with open(PUB_NAMES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(pubs)

    total_geo = geo_found + geo_skipped
    print(f"\nDone! {total_geo}/{len(pubs)} pubs have coordinates "
          f"({geo_found} new, {geo_skipped} existing)")
    print(f"Updated {PUB_NAMES_CSV}")


if __name__ == "__main__":
    main()
