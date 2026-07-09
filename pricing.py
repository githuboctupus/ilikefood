

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


INTOLERANCE_KEYWORDS = {
    "dairy": ["milk", "cheese", "cream", "butter", "whey", "yogurt", "lactose"],
    "egg": ["egg"],
    "gluten": ["wheat", "gluten", "barley", "rye", "malt"],
    "grain": ["wheat", "rice", "oat", "corn", "barley", "rye"],
    "peanut": ["peanut"],
    "seafood": ["fish", "shrimp", "crab", "lobster", "anchovy", "salmon", "tuna"],
    "sesame": ["sesame", "tahini"],
    "shellfish": ["shrimp", "crab", "lobster", "clam", "oyster", "scallop", "mussel"],
    "soy": ["soy"],
    "sulfite": ["sulfite"],
    "tree nut": ["almond", "walnut", "pecan", "cashew", "hazelnut", "pistachio", "macadamia"],
    "wheat": ["wheat"],
}


def filter_unsafe_products(options, intolerances=None, dislikes=None):
    """
    Removes any product whose description/brand text matches a banned term
    from the user's intolerances or dislikes -- e.g. a "hoagie roll" search
    result that turns out to be topped with sesame seeds even though
    "sesame" was never in the recipe's ingredient name.

    This is a text-match heuristic against Kroger's product description,
    NOT a verified allergen database -- for anyone with a serious/medical
    allergy, always double check the actual product label before buying.
    """
    banned_terms = []
    for intol in (intolerances or []):
        banned_terms.extend(INTOLERANCE_KEYWORDS.get(intol.lower(), [intol.lower()]))
    banned_terms.extend([d.lower() for d in (dislikes or [])])

    if not banned_terms:
        return options, []

    safe, flagged = [], []
    for o in options:
        text = f"{o['description']} {o.get('brand') or ''}".lower()
        if any(term in text for term in banned_terms):
            flagged.append(o)
        else:
            safe.append(o)
    return safe, flagged


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


SKIP_PRICING_TERMS = {"water", "ice", "ice cubes", "ice water", "tap water"}


def price_ingredient(ingredient_name, location_id, prefer_organic=False,
                      avoid_processed=False, intolerances=None, dislikes=None,
                      interactive=True):
    """
    Returns the chosen product dict (with price, size, etc.) or None if
    skipped/unavailable -- not just a bare price -- so the caller can also
    use the package size for serving/leftover math.
    """
    print(f"\n{ingredient_name}:")

    if ingredient_name.strip().lower() in SKIP_PRICING_TERMS:
        print("  Assumed free (tap water) -- not priced.")
        return {"id": None, "description": ingredient_name, "price": 0.0, "size": None}

    options = search_products(ingredient_name, location_id)
    if not options:
        print("  Not found at this store.")
        return None

    safe_options, flagged = filter_unsafe_products(options, intolerances, dislikes)
    if not safe_options:
        excluded_names = ", ".join(o["description"] for o in flagged[:3])
        print(f"  Every match at this store conflicts with your intolerances/dislikes "
              f"(e.g. {excluded_names}). Not priced.")
        return None

    display = pick_display_options(safe_options, prefer_organic, avoid_processed)
    if flagged:
        print(f"  (Note: {len(flagged)} match(es) hidden for containing an excluded ingredient.)")

    best_id = display[0]["id"]
    cheapest_id = min(safe_options, key=lambda o: o["price"])["id"]

    for i, o in enumerate(display, start=1):
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
        print(f"  {i}. [{tag_str:16}] {brand}{o['description']}{size} -- ${o['price']:.2f}")

    if not interactive:
        return display[0]

    choice = input(f"  Pick 1-{len(display)} (blank = best match, 's' = skip this ingredient): ").strip().lower()
    if choice == "s":
        return "SKIP"
    if not choice:
        return display[0]
    try:
        return display[int(choice) - 1]
    except (ValueError, IndexError):
        print("  Invalid choice -- using best match.")
        return display[0]


def price_recipe(ingredient_names, location_id, prefer_organic=False,
                  avoid_processed=False, intolerances=None, dislikes=None,
                  interactive=True):
    """
    Returns (total, missing, skipped, chosen_products) where chosen_products
    is a dict of {ingredient_name: product_dict} for everything actually priced --
    needed later for the servings/leftover math, since that needs package size.
    """
    total = 0.0
    missing = []
    skipped = []
    chosen_products = {}

    for name in ingredient_names:
        result = price_ingredient(name, location_id, prefer_organic, avoid_processed,
                                   intolerances, dislikes, interactive)
        if result is None:
            missing.append(name)
        elif result == "SKIP":
            skipped.append(name)
        else:
            total += result["price"]
            chosen_products[name] = result

    print(f"\nEstimated total: ${total:.2f}")
    if missing:
        print(f"Could not be priced: {', '.join(missing)}")
    if skipped:
        print(f"Skipped by choice: {', '.join(skipped)}")

    return total, missing, skipped, chosen_products


if __name__ == "__main__":
    location_id = input("Enter the Kroger store's Location ID (from store_locator.py): ").strip()
    ingredients_raw = input("Enter ingredients, comma separated: ").strip()
    ingredient_names = [x.strip() for x in ingredients_raw.split(",") if x.strip()]

    prefer_organic = input("Prefer organic when available? (y/n): ").strip().lower() == "y"
    avoid_processed = input("Avoid heavily processed options when possible? (y/n): ").strip().lower() == "y"

    price_recipe(ingredient_names, location_id, prefer_organic, avoid_processed)