

import base64
import os
import sys

import requests
from dotenv import load_dotenv


load_dotenv()

KROGER_CLIENT_ID = os.environ.get("KROGER_CLIENT_ID")
KROGER_CLIENT_SECRET = os.environ.get("KROGER_CLIENT_SECRET")
ORS_API_KEY = os.environ.get("ORS_API_KEY")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ORS_MATRIX_URL = "https://api.openrouteservice.org/v2/matrix/driving-car"
KROGER_TOKEN_URL = "https://api.kroger.com/v1/connect/oauth2/token"
KROGER_LOCATIONS_URL = "https://api.kroger.com/v1/locations"

HEADERS_NOMINATIM = {"User-Agent": "student-grocery-app/0.1 (personal project)"}
HEADERS_OVERPASS = {
    "User-Agent": "student-grocery-app/0.1 (personal project)",
    "Accept": "*/*",
}

SPECIALTY_SHOP_TAGS = ["seafood", "butcher", "deli", "greengrocer", "health_food"]


def geocode_zip(zip_code):
    """Turn a US zip code into (lat, lon) using Nominatim (free, no key)."""
    params = {"postalcode": zip_code, "country": "us", "format": "json", "limit": 1}
    r = requests.get(NOMINATIM_URL, params=params, headers=HEADERS_NOMINATIM, timeout=15)
    r.raise_for_status()
    results = r.json()
    if not results:
        raise ValueError(f"Couldn't geocode zip code {zip_code}")
    return float(results[0]["lat"]), float(results[0]["lon"])


def get_kroger_token():
    """OAuth2 client_credentials flow -> short-lived access token."""
    creds = f"{KROGER_CLIENT_ID}:{KROGER_CLIENT_SECRET}"
    b64_creds = base64.b64encode(creds.encode()).decode()
    headers = {
        "Authorization": f"Basic {b64_creds}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "client_credentials", "scope": "product.compact"}
    r = requests.post(KROGER_TOKEN_URL, headers=headers, data=data, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def find_kroger_stores(zip_code, radius_miles=10, limit=5):
    """Find nearby Kroger-family stores by zip code."""
    token = get_kroger_token()
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "filter.zipCode.near": zip_code,
        "filter.radiusInMiles": radius_miles,
        "filter.limit": limit,
    }
    r = requests.get(KROGER_LOCATIONS_URL, headers=headers, params=params, timeout=15)
    r.raise_for_status()

    stores = []
    for loc in r.json().get("data", []):
        geo = loc.get("geolocation", {})
        addr = loc.get("address", {})
        stores.append({
            "name": loc.get("name", "Kroger store"),
            "address": addr.get("addressLine1"),
            "city": addr.get("city"),
            "lat": geo.get("latitude"),
            "lon": geo.get("longitude"),
            "type": "kroger",
        })
    return stores


def find_specialty_markets(lat, lon, radius_m=10000):
    """Find fish markets, butchers, etc. nearby using OSM Overpass (free, no key)."""
    shop_regex = "|".join(SPECIALTY_SHOP_TAGS)
    query = (
        f'[out:json][timeout:40];'
        f'node["shop"~"^({shop_regex})$"](around:{radius_m},{lat},{lon});'
        f'out center;'
    )

    r = requests.post(OVERPASS_URL, data={"data": query}, headers=HEADERS_OVERPASS, timeout=45)
    r.raise_for_status()

    markets = []
    for el in r.json().get("elements", []):
        tags = el.get("tags", {})
        markets.append({
            "name": tags.get("name", "Unnamed market"),
            "type": tags.get("shop"),
            "lat": el.get("lat"),
            "lon": el.get("lon"),
        })
    print(markets)
    return markets


def get_drive_times(origin, destinations):
    """
    origin: (lat, lon)
    destinations: list of (lat, lon)
    Returns a list of (duration_minutes, distance_miles), same order as destinations.
    """
    locations = [[origin[1], origin[0]]] + [[d[1], d[0]] for d in destinations]
    body = {
        "locations": locations,
        "sources": [0],
        "destinations": list(range(1, len(locations))),
        "metrics": ["duration", "distance"],
    }
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
    r = requests.post(ORS_MATRIX_URL, json=body, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()

    results = []
    for duration, distance in zip(data["durations"][0], data["distances"][0]):
        minutes = round(duration / 60, 1) if duration is not None else None
        miles = round(distance / 1609.34, 1) if distance is not None else None
        results.append((minutes, miles))
    return results


def check_credentials():
    missing = [
        name for name, val in [
            ("KROGER_CLIENT_ID", KROGER_CLIENT_ID),
            ("KROGER_CLIENT_SECRET", KROGER_CLIENT_SECRET),
            ("ORS_API_KEY", ORS_API_KEY),
        ] if not val
    ]
    if missing:
        print("Missing value(s) in your .env file: " + ", ".join(missing))
        print("Make sure store_locator.py and .env are in the same folder,")
        print("and that .env has KROGER_CLIENT_ID, KROGER_CLIENT_SECRET, and ORS_API_KEY set.")
        sys.exit(1)


def main(zip_code):
    check_credentials()
    print(f"\nFinding stores near {zip_code}...\n")

    user_lat, user_lon = geocode_zip(zip_code)

    print("Searching Kroger-family stores...")
    kroger_stores = find_kroger_stores(zip_code)

    print("Searching specialty markets (OpenStreetMap)...")
    specialty_stores = find_specialty_markets(user_lat, user_lon)

    all_stores = [s for s in kroger_stores + specialty_stores if s.get("lat") and s.get("lon")]

    if not all_stores:
        print("No stores found nearby. Try a larger radius or a different zip code.")
        return

    print(f"Getting drive times to {len(all_stores)} locations...\n")
    destinations = [(s["lat"], s["lon"]) for s in all_stores]
    drive_times = get_drive_times((user_lat, user_lon), destinations)

    for store, (minutes, miles) in zip(all_stores, drive_times):
        store["drive_minutes"] = minutes
        store["drive_miles"] = miles

    all_stores.sort(key=lambda s: s["drive_minutes"] if s["drive_minutes"] is not None else 999)

    print(f"{'Store':35} {'Type':12} {'Drive time':12} {'Distance'}")
    print("-" * 75)
    for s in all_stores:
        name = (s["name"] or "Unknown")[:34]
        kind = s["type"] or ""
        mins = f"{s['drive_minutes']} min" if s["drive_minutes"] is not None else "N/A"
        miles = f"{s['drive_miles']} mi" if s["drive_miles"] is not None else "N/A"
        print(f"{name:35} {kind:12} {mins:12} {miles}")


if __name__ == "__main__":
    zip_input = input("Enter your zip code: ").strip()
    main(zip_input)