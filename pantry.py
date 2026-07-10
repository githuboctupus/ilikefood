"""
Pantry tracking.

Stores what you already have (ingredient -> quantity/unit), lets you check
whether your pantry has ENOUGH of an ingredient for a given recipe (not
just whether the name matches -- Spoonacular's findByIngredients only
checks presence, not quantity), and wraps that search endpoint.

SETUP: uses the same .env as the other scripts (SPOONACULAR_API_KEY).
Pantry data is stored in pantry.json in the same folder -- delete that
file any time to reset your pantry.
"""

import json
import os

import requests
from dotenv import load_dotenv

import servings  # reuse the same unit-conversion logic, not a second copy

load_dotenv()

SPOONACULAR_API_KEY = os.environ.get("SPOONACULAR_API_KEY")
FIND_BY_INGREDIENTS_URL = "https://api.spoonacular.com/recipes/findByIngredients"
PANTRY_FILE = "pantry.json"


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def load_pantry():
    if not os.path.exists(PANTRY_FILE):
        return {}
    with open(PANTRY_FILE, "r") as f:
        return json.load(f)


def save_pantry(pantry):
    with open(PANTRY_FILE, "w") as f:
        json.dump(pantry, f, indent=2)


def add_or_update_item(pantry, name, amount, unit):
    """
    If the ingredient already exists with the SAME unit, adds to it.
    If it exists with a DIFFERENT unit, this just overwrites -- we don't
    silently convert lb to cup for you, since that needs a density lookup
    (same limitation as servings.py) and could quietly produce a wrong number.
    """
    key = name.strip().lower()
    existing = pantry.get(key)
    if existing and existing["unit"].strip().lower() == unit.strip().lower():
        existing["amount"] += amount
    else:
        pantry[key] = {"amount": amount, "unit": unit}
    return pantry


def remove_item(pantry, name):
    pantry.pop(name.strip().lower(), None)
    return pantry


# ---------------------------------------------------------------------------
# "Do I have ENOUGH?" -- the actual gap this fixes
# ---------------------------------------------------------------------------

def check_quantity_sufficient(pantry, ingredient_name, recipe_amount, recipe_unit):
    """
    Returns one of:
      "sufficient"    -- pantry has enough, confidently
      "insufficient"  -- pantry has some, but not enough (confidently)
      "unknown_qty"   -- ingredient not in pantry at all
      "not_comparable" -- in pantry, but units can't be confidently compared
                          (e.g. pantry has "cloves", recipe needs "oz")
    Also returns the pantry's current amount/unit for display, or None.
    """
    key = ingredient_name.strip().lower()
    have = pantry.get(key)
    if not have:
        return "unknown_qty", None

    have_amount, have_unit = have["amount"], have["unit"]

    # Same unit -- direct comparison, no conversion needed.
    if have_unit.strip().lower() == (recipe_unit or "").strip().lower():
        status = "sufficient" if have_amount >= recipe_amount else "insufficient"
        return status, have

    # Try converting both to grams via servings.py's existing logic.
    have_g = servings.to_grams(have_amount, have_unit, ingredient_name)
    need_g = servings.to_grams(recipe_amount, recipe_unit, ingredient_name)
    if have_g is None or need_g is None:
        return "not_comparable", have

    status = "sufficient" if have_g >= need_g else "insufficient"
    return status, have


def annotate_recipe_with_pantry_check(recipe, pantry):
    """
    Given a parsed recipe (from recipe_search.parse_recipe) and the pantry,
    tags each ingredient with a pantry_status field so the UI/terminal can
    show "you have enough" vs "you have some but not enough" vs "don't have."
    """
    for ing in recipe.get("ingredients", []):
        status, have = check_quantity_sufficient(
            pantry, ing["name"], ing.get("amount"), ing.get("unit")
        )
        ing["pantry_status"] = status
        ing["pantry_have"] = have
    return recipe


# ---------------------------------------------------------------------------
# Spoonacular findByIngredients wrapper
# ---------------------------------------------------------------------------

def find_recipes_from_pantry(pantry, ranking=1, number=5, only_use=None, exclude=None):
    """
    ranking=1: maximize use of pantry ingredients.
    ranking=2: minimize ingredients you'd still need to buy.

    only_use: optional list of ingredient names -- if given, ONLY these
              pantry items are sent to the search, even if the pantry has
              more. Use this when you want "just work with chicken and
              rice today," ignoring everything else in the pantry.
    exclude:  optional list of ingredient names to leave out of the search
              (the opposite of only_use -- "use everything except X").
              Ignored if only_use is also given.

    NOTE: this only checks ingredient NAMES, not quantities -- a recipe
    can show up here even if you don't have enough of something. Always
    run annotate_recipe_with_pantry_check() afterward for the real check.
    """
    all_names = list(pantry.keys())

    if only_use:
        wanted = {n.strip().lower() for n in only_use}
        ingredient_names = [n for n in all_names if n in wanted]
    elif exclude:
        excluded = {n.strip().lower() for n in exclude}
        ingredient_names = [n for n in all_names if n not in excluded]
    else:
        ingredient_names = all_names

    if not ingredient_names:
        return []

    params = {
        "apiKey": SPOONACULAR_API_KEY,
        "ingredients": ",".join(ingredient_names),
        "ranking": ranking,
        "ignorePantry": "true",
        "number": number,
    }
    r = requests.get(FIND_BY_INGREDIENTS_URL, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    pantry = load_pantry()
    print(f"Current pantry: {pantry}\n")

    action = input("Add/update an item? (y/n): ").strip().lower()
    if action == "y":
        name = input("Ingredient name: ").strip()
        amount = float(input("Amount: ").strip())
        unit = input("Unit (e.g. lb, cup, ct): ").strip()
        pantry = add_or_update_item(pantry, name, amount, unit)
        save_pantry(pantry)
        print(f"Saved. Pantry now: {pantry}")

    search = input("\nSearch recipes using your pantry? (y/n): ").strip().lower()
    if search == "y":
        print(f"Your pantry has: {', '.join(pantry.keys())}")
        pick = input(
            "Use ALL of these, or just some? Type 'all' or a comma-separated "
            "list of which ones to use: "
        ).strip().lower()

        if pick == "all" or not pick:
            results = find_recipes_from_pantry(pantry)
        else:
            chosen = [x.strip() for x in pick.split(",") if x.strip()]
            results = find_recipes_from_pantry(pantry, only_use=chosen)

        for r in results:
            print(f"\n{r['title']}")
            print(f"  Uses {r['usedIngredientCount']} of your ingredients, "
                  f"missing {r['missedIngredientCount']}: "
                  f"{', '.join(i['name'] for i in r['missedIngredients'])}")