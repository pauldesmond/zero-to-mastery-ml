"""
Extract pub names and locations from Flickr album photo titles.

Fetches photos from albums named "London Pubs (EC)", "London Pubs (EC1)", etc.
and parses the title of each photo to extract the pub name and location.

Output: pub_names.csv with columns: pub_name, location, postcode_area, photo_url

Usage:
    python extract_pub_names.py

Note: E4 album not found on Flickr (may not exist). Add its album ID
to ALBUM_IDS if you find it.
"""

import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()


load_env()

FLICKR_API_KEY = os.environ.get("FLICKR_API_KEY")
if not FLICKR_API_KEY:
    print("Error: FLICKR_API_KEY not found.")
    sys.exit(1)

FLICKR_API_URL = "https://api.flickr.com/services/rest/"
TARGET_USER_ID = "55935853@N00"

# Known album IDs for target postcode areas (from Flickr user Ewan-M)
ALBUM_IDS = {
    # East / City
    "EC":  "72157604256269088",
    "EC1": "72157616552639515",
    "EC2": "72157616567050485",
    "EC3": "72157616567143717",
    "EC4": "72157616657337064",
    "E1":  "72157615628471244",
    "E2":  "72157615377618566",
    "E3":  "72157618342821571",
    # West End / Central
    "W1":  "72157605337274095",
    "WC2": "72157616336466071",
    "NW1": "72157616447806043",
    "SW":  "72157604260714645",
    "SW1": "72157615589336765",
}
POSTCODE_AREAS = list(ALBUM_IDS.keys())


def flickr_api_call(method, **kwargs):
    params = {
        "method": method,
        "api_key": FLICKR_API_KEY,
        "format": "json",
        "nojsoncallback": 1,
        **kwargs,
    }
    url = FLICKR_API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())



def get_photoset_photos(photoset_id, user_id):
    """Get all photos in a photoset."""
    all_photos = []
    page = 1
    while True:
        data = flickr_api_call(
            "flickr.photosets.getPhotos",
            photoset_id=photoset_id,
            user_id=user_id,
            per_page="500",
            page=str(page),
        )
        if data.get("stat") != "ok":
            print(f"  Error fetching photos: {data}")
            return all_photos
        photos = data["photoset"]["photo"]
        all_photos.extend(photos)
        total = int(data["photoset"].get("total", 0))
        print(f"  Fetched page {page} ({len(all_photos)}/{total} photos)")
        if len(all_photos) >= total:
            break
        page += 1
        time.sleep(0.3)
    return all_photos


def parse_title(title):
    """Parse a photo title to extract pub name and location.

    Titles are typically formatted like:
      "The Barley Mow, Shoreditch, EC2"
      "Pub Name, Area Name, EC1"
      "Pub Name, Some Street, Area, E2"
    """
    # Clean up the title
    title = title.strip()

    # Split by comma
    parts = [p.strip() for p in title.split(",")]

    if len(parts) >= 2:
        pub_name = parts[0]
        # The location is everything between the name and the last part
        # (which is often the postcode area)
        location = ", ".join(parts[1:])
        return pub_name, location
    else:
        # No comma - just return the whole title as the name
        return title, ""


def main():
    print("Extracting pub names from Flickr albums...")
    print(f"Albums: {', '.join(f'London Pubs ({a})' for a in POSTCODE_AREAS)}")
    print()

    # Fetch photos from each album using known IDs and parse titles
    all_pubs = []
    for area, album_id in ALBUM_IDS.items():
        print(f"Fetching: London Pubs ({area}) [album {album_id}]...")
        photos = get_photoset_photos(album_id, TARGET_USER_ID)

        for photo in photos:
            title = photo.get("title", "")
            if not title:
                continue
            pub_name, location = parse_title(title)
            server = photo.get("server", "")
            photo_id = photo.get("id", "")
            secret = photo.get("secret", "")
            photo_url = f"https://live.staticflickr.com/{server}/{photo_id}_{secret}_b.jpg"
            all_pubs.append({
                "pub_name": pub_name,
                "location": location,
                "postcode_area": area,
                "photo_url": photo_url,
            })

        print(f"  Extracted {len(photos)} entries\n")
        time.sleep(0.3)

    # Step 4: Write CSV
    output_path = Path(__file__).parent / "pub_names.csv"
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["pub_name", "location", "postcode_area", "photo_url"])
        writer.writeheader()
        writer.writerows(all_pubs)

    print(f"Done! Wrote {len(all_pubs)} pubs to {output_path}")

    # Print a preview
    print(f"\nPreview (first 15 rows):")
    print(f"{'Pub Name':<40} {'Location':<30} {'Area'}")
    print("-" * 80)
    for pub in all_pubs[:15]:
        print(f"{pub['pub_name']:<40} {pub['location']:<30} {pub['postcode_area']}")
    if len(all_pubs) > 15:
        print(f"... and {len(all_pubs) - 15} more")


if __name__ == "__main__":
    main()
