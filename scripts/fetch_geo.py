#!/usr/bin/env python3
"""Resolve each reviewed property to its tax parcel geometry.

The minutes record an SBL (Section-Block-Lot) for most items, and New York
State publishes every parcel in the state keyed by exactly that number. Joining
on SBL gives the real parcel outline rather than a geocoder's guess at where an
address sits, which matters here: the commission reviews specific buildings,
and several of them share a street number with a neighbour.

Writes data/parcels.json (per-SBL centroid + simplified outline) and
data/boundary.json (the city outline, for map context).
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "decisions.json"
PARCELS = ROOT / "data" / "parcels.json"
BOUNDARY = ROOT / "data" / "boundary.json"

PARCEL_URL = (
    "https://gisservices.its.ny.gov/arcgis/rest/services/"
    "NYS_Tax_Parcels_Public/MapServer/1/query"
)
TIGER_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/"
    "TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/4/query"  # Incorporated Places
)
UA = "Mozilla/5.0 (compatible; kingston-historic-data/1.0)"

BATCH = 40  # SBLs per request; the service rejects very long where-clauses


def normalize(sbl):
    """Minutes spell an SBL loosely: '56. 43-8-61.100', '56.42 -7-12'.
    The state's PRINT_KEY has no spaces."""
    cleaned = re.sub(r"\s+", "", sbl or "")
    return cleaned.strip(" .,;-") or None


def get(url, params, timeout=120, attempts=3):
    query = urllib.parse.urlencode(params)
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                f"{url}?{query}", headers={"User-Agent": UA}
            )
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:
            if attempt == attempts - 1:
                print(f"  request failed: {exc}", file=sys.stderr)
                return None
            time.sleep(3 * (attempt + 1))


def ring_centroid(ring):
    """Area-weighted centroid of a closed ring, falling back to the mean point
    for degenerate shapes."""
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(area) < 1e-12:
        return (
            sum(p[0] for p in ring) / len(ring),
            sum(p[1] for p in ring) / len(ring),
        )
    area *= 0.5
    return cx / (6 * area), cy / (6 * area)


def simplify(ring, tolerance=0.000012):
    """Drop points that sit within `tolerance` of the previous kept point.
    Parcel outlines are drawn a few hundred pixels wide at most."""
    out = [ring[0]]
    for point in ring[1:]:
        last = out[-1]
        if abs(point[0] - last[0]) > tolerance or abs(point[1] - last[1]) > tolerance:
            out.append(point)
    if len(out) < 3:
        return ring
    return out


def fetch_parcels(keys):
    found = {}
    keys = sorted(keys)
    for start in range(0, len(keys), BATCH):
        chunk = keys[start : start + BATCH]
        quoted = ",".join("'" + k.replace("'", "''") + "'" for k in chunk)
        print(f"  parcels {start + 1}-{start + len(chunk)} of {len(keys)}", file=sys.stderr)
        data = get(
            PARCEL_URL,
            {
                "where": f"PRINT_KEY IN ({quoted}) AND MUNI_NAME='Kingston, City'",
                "outFields": "PRINT_KEY,PARCEL_ADDR",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "json",
            },
        )
        for feature in (data or {}).get("features", []):
            key = feature["attributes"]["PRINT_KEY"]
            rings = feature.get("geometry", {}).get("rings") or []
            if not rings:
                continue
            outer = max(rings, key=len)
            lon, lat = ring_centroid(outer)
            found[key] = {
                "sbl": key,
                "address": feature["attributes"].get("PARCEL_ADDR"),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "ring": [[round(x, 6), round(y, 6)] for x, y in simplify(outer)],
            }
        time.sleep(0.4)
    return found


def fetch_boundary():
    data = get(
        TIGER_URL,
        {
            # TIGER stores NAME as "Kingston city"; BASENAME is the bare name.
            "where": "BASENAME='Kingston' AND STATE='36'",
            "outFields": "NAME",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
        },
    )
    features = (data or {}).get("features", [])
    if not features:
        print("  city boundary unavailable", file=sys.stderr)
        return None
    rings = features[0]["geometry"]["rings"]
    return {
        "name": "Kingston, NY",
        "rings": [
            [[round(x, 6), round(y, 6)] for x, y in simplify(r, 0.00004)]
            for r in rings
        ],
    }


def main():
    meetings = json.loads(SOURCE.read_text())
    wanted = {}
    for meeting in meetings:
        for item in meeting["items"]:
            key = normalize(item.get("sbl"))
            if key:
                wanted.setdefault(key, item.get("address"))

    print(f"{len(wanted)} distinct parcels referenced in the minutes", file=sys.stderr)
    parcels = fetch_parcels(wanted)

    missing = sorted(set(wanted) - set(parcels))
    PARCELS.write_text(json.dumps(parcels, indent=1) + "\n")
    print(f"  matched {len(parcels)}, unmatched {len(missing)}", file=sys.stderr)
    if missing:
        print("  unmatched: " + ", ".join(missing[:20]), file=sys.stderr)

    boundary = fetch_boundary()
    if boundary:
        BOUNDARY.write_text(json.dumps(boundary) + "\n")
        print(f"  boundary: {sum(len(r) for r in boundary['rings'])} points", file=sys.stderr)


if __name__ == "__main__":
    main()
