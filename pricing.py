
import base64
import os

import requests
from dotenv import load_dotenv

load_dotenv()

KROGER_CLIENT_ID = os.environ.get("KROGER_CLIENT_ID")
KROGER_CLIENT_SECRET = os.environ.get("KROGER_CLIENT_SECRET")

KROGER_TOKEN_URL = "https://api.kroger.com/v1/connect/oauth2/token"
KROGER_PRODUCTS_URL = "https://api.kroger.com/v1/products"


def get_kroger_token():
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


def search_products(term, location_id, limit=10):
    """
    Search Kroger's catalog for a term at a specific store.
    Returns options in Kroger's own result order (their relevance ranking
    for that search term -- treated here as the "recommended" order).
    """
    token = get_kroger_token()
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "filter.term": term,
        "filter.locationId": location_id,
        "filter.limit": limit,
    }
    r = requests.get(KROGER_PRODUCTS_URL, headers=headers, params=params, timeout=15)
    r.raise_for_status()

    options = []
    for item in r.json().get("data", []):
        items = item.get("items", [])
        price_info = items[0].get("price") if items else None
        price = None
        if price_info:
            price = price_info.get("promo") or price_info.get("regular")
        if price is None:
            continue  # no price data -- often means out of stock at this store
        options.append({
            "id": item.get("productId"),
            "description": item.get("description", "Unknown product"),
            "brand": item.get("brand"),
            "size": items[0].get("size") if items else None,
            "price": price,
            "categories": item.get("categories", []),
            "organic_claim": item.get("organicClaimName"),  # real field, not a guess
            "non_gmo": item.get("nonGmo", False),
        })
    return options


PROCESSED_CATEGORY_HINTS = [
    "frozen", "canned", "snack", "candy", "soda", "cookie", "chip",
    "instant", "prepared", "microwave", "boxed",
]
WHOLE_CATEGORY_HINTS = [
    "produce", "meat", "seafood", "dairy", "bakery", "deli", "eggs",
]


def score_product(product, prefer_organic=False, avoid_processed=False):
    """
    Higher score = better match for the user's stated preferences.
    This doesn't touch price at all -- it's purely "does this match what
    they said they want," so it can be combined with price separately.
    """
    score = 0
    text = f"{product['description']} {product.get('brand') or ''}".lower()
    categories_text = " ".join(product.get("categories", [])).lower()

    if prefer_organic:
        if product.get("organic_claim"):
            score += 15  # real, label-verified claim -- strong signal
        elif "organic" in text:
            score += 5   # only shows up in the name/brand text -- weaker signal

    if avoid_processed:
        if any(hint in categories_text for hint in WHOLE_CATEGORY_HINTS):
            score += 5
        if any(hint in categories_text for hint in PROCESSED_CATEGORY_HINTS):
            score -= 5

    return score


def pick_display_options(options, prefer_organic=False, avoid_processed=False):
    """
    Returns up to 3 options to show:
      - the best match for stated preferences (organic / avoid-processed)
      - the cheapest option (always shown, even if it's not the best match,
        so you can see the tradeoff)
      - one more from Kroger's default order, for variety
    If no preferences are set, "best match" and "cheapest" collapse to the
    same thing, same as before.
    """
    if not options:
        return []

    scored = [(o, score_product(o, prefer_organic, avoid_processed)) for o in options]
    best_match = max(scored, key=lambda pair: (pair[1], -pair[0]["price"]))[0]
    cheapest = min(options, key=lambda o: o["price"])

    display = [best_match]
    if cheapest["id"] != best_match["id"]:
        display.append(cheapest)
    for o in options:
        if len(display) >= 3:
            break
        if o["id"] not in {d["id"] for d in display}:
            display.append(o)

    return display


def price_ingredient(ingredient_name, location_id, prefer_organic=False, avoid_processed=False):
    options = search_products(ingredient_name, location_id)
    display = pick_display_options(options, prefer_organic, avoid_processed)

    print(f"\n{ingredient_name}:")
    if not display:
        print("  No matching products found at this store.")
        return None

    best_id = display[0]["id"]
    cheapest_id = min(options, key=lambda o: o["price"])["id"]

    for o in display:
        tags = []
        if o["id"] == best_id and (prefer_organic or avoid_processed):
            tags.append("BEST MATCH")
        if o["id"] == cheapest_id:
            tags.append("CHEAPEST")
        if o.get("organic_claim"):
            tags.append("ORGANIC")
        tag_str = "/".join(tags) if tags else "option"
        size = f" ({o['size']})" if o.get("size") else ""
        brand = f"{o['brand']} " if o.get("brand") else ""
        print(f"  [{tag_str:16}] {brand}{o['description']}{size} -- ${o['price']:.2f}")

    # Use the best-match option's price for the running total, not always cheapest --
    # if the user asked for organic/less-processed, the total should reflect that choice.
    return display[0]["price"]


def price_recipe(ingredient_names, location_id, prefer_organic=False, avoid_processed=False):
    total = 0.0
    missing = []

    for name in ingredient_names:
        price = price_ingredient(name, location_id, prefer_organic, avoid_processed)
        if price is None:
            missing.append(name)
        else:
            total += price

    print(f"\nEstimated total: ${total:.2f}")
    if missing:
        print(f"Not found at this store: {', '.join(missing)}")

    return total, missing


if __name__ == "__main__":
    location_id = input("Enter the Kroger store's Location ID (from store_locator.py): ").strip()
    ingredients_raw = input("Enter ingredients, comma separated: ").strip()
    ingredient_names = [x.strip() for x in ingredients_raw.split(",") if x.strip()]

    prefer_organic = input("Prefer organic when available? (y/n): ").strip().lower() == "y"
    avoid_processed = input("Avoid heavily processed options when possible? (y/n): ").strip().lower() == "y"

    price_recipe(ingredient_names, location_id, prefer_organic, avoid_processed)