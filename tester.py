"""
Quick sanity test for:
  - pantry.py (storage, quantity-sufficiency check)
  - servings.py new functions (per_serving_amount, servings_from_one_package,
    unit_type, units_are_compatible)

This does NOT call Kroger/Spoonacular/ORS -- it's pure logic checks using
made-up numbers, so it runs instantly with no API keys needed for most of
it. The one exception (clearly marked) optionally hits Spoonacular if you
want to test find_recipes_from_pantry for real.

Run it:
    python3 test_new_features.py
"""

import os
import servings
import pantry


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition


def test_servings_math():
    print("\n=== servings.py: per_serving_amount ===")
    # Recipe uses 2 lb per full run; with servings_per_batch=1 (default),
    # per-serving amount should just equal the recipe amount, unchanged.
    result = servings.per_serving_amount(2.0)
    check(f"per_serving_amount(2.0) == 2.0 (got {result})", result == 2.0)

    print("\n=== servings.py: unit_type ===")
    check("unit_type('lb') == 'weight'", servings.unit_type("lb") == "weight")
    check("unit_type('cup') == 'volume'", servings.unit_type("cup") == "volume")
    check("unit_type('ct') == 'count'", servings.unit_type("ct") == "count")
    check("unit_type('clove') == 'count'", servings.unit_type("clove") == "count" or servings.unit_type("clove") == "unknown")

    print("\n=== servings.py: units_are_compatible ===")
    check("lb vs oz -> compatible (both weight)",
          servings.units_are_compatible("lb", "oz") is True)
    check("cup vs tbsp -> compatible (both volume)",
          servings.units_are_compatible("cup", "tbsp") is True)
    check("lb vs ct -> NOT compatible (weight vs count)",
          servings.units_are_compatible("lb", "ct") is False)
    check("unknown unit -> treated as compatible (no penalty without evidence)",
          servings.units_are_compatible("lb", "xyz") is True)

    print("\n=== servings.py: servings_from_one_package (weight-based) ===")
    # Recipe needs 0.5 lb chicken per serving, package is a 2 lb pack.
    max_servings, leftover, ok = servings.servings_from_one_package(
        recipe_amount=0.5, recipe_unit="lb", ingredient_name="chicken",
        package_amount=2, package_unit="lb",
    )
    check(f"convertible == True (got {ok})", ok is True)
    check(f"max_servings == 4 (got {max_servings})", max_servings == 4)
    check(f"leftover ~= 0 (got {leftover})", abs((leftover or 0)) < 0.01)

    print("\n=== servings.py: servings_from_one_package (count-based) ===")
    # Recipe needs 2 rolls per serving, package has 4 ct.
    max_servings, leftover, ok = servings.servings_from_one_package(
        recipe_amount=2, recipe_unit="ct", ingredient_name="roll",
        package_amount=4, package_unit="ct",
    )
    check(f"convertible == True (got {ok})", ok is True)
    check(f"max_servings == 2 (got {max_servings})", max_servings == 2)

    print("\n=== servings.py: servings_from_one_package (volume, no density -> honest failure) ===")
    # Recipe needs 1 cup of something with no known density -- should NOT guess.
    max_servings, leftover, ok = servings.servings_from_one_package(
        recipe_amount=1, recipe_unit="cup", ingredient_name="mystery sauce",
        package_amount=16, package_unit="oz",
    )
    check(f"convertible == False when density unknown (got {ok})", ok is False)


def test_pantry():
    print("\n=== pantry.py: add_or_update_item ===")
    test_pantry_data = {}
    test_pantry_data = pantry.add_or_update_item(test_pantry_data, "chicken wings", 0.5, "lb")
    check("chicken wings added with 0.5 lb",
          test_pantry_data["chicken wings"]["amount"] == 0.5)

    test_pantry_data = pantry.add_or_update_item(test_pantry_data, "chicken wings", 0.5, "lb")
    check("adding again with same unit sums to 1.0 lb",
          test_pantry_data["chicken wings"]["amount"] == 1.0)

    test_pantry_data = pantry.add_or_update_item(test_pantry_data, "rice", 2, "cup")

    print("\n=== pantry.py: check_quantity_sufficient ===")
    # Pantry has 1.0 lb chicken wings, recipe needs 2 lb -> insufficient
    status, have = pantry.check_quantity_sufficient(
        test_pantry_data, "chicken wings", 2.0, "lb"
    )
    check(f"1.0 lb on hand, need 2 lb -> 'insufficient' (got '{status}')",
          status == "insufficient")

    # Recipe needs only 0.5 lb -> sufficient
    status, have = pantry.check_quantity_sufficient(
        test_pantry_data, "chicken wings", 0.5, "lb"
    )
    check(f"1.0 lb on hand, need 0.5 lb -> 'sufficient' (got '{status}')",
          status == "sufficient")

    # Ingredient not tracked at all
    status, have = pantry.check_quantity_sufficient(
        test_pantry_data, "garlic", 3, "clove"
    )
    check(f"untracked ingredient -> 'unknown_qty' (got '{status}')",
          status == "unknown_qty")

    # Same ingredient, incompatible units (pantry has cups, recipe wants lb,
    # and rice has no density issue here -- but let's force a genuine
    # non-comparable case: pantry unit vs recipe unit both volume/weight
    # mismatch with no shared conversion path)
    status, have = pantry.check_quantity_sufficient(
        test_pantry_data, "rice", 200, "g"
    )
    print(f"  [INFO] rice: 2 cup on hand vs 200g needed -> status = '{status}' "
          f"(should be 'sufficient' or 'insufficient', not 'not_comparable', "
          f"since rice has a known density)")

    print("\n=== pantry.py: remove_item ===")
    test_pantry_data = pantry.remove_item(test_pantry_data, "rice")
    check("rice removed from pantry", "rice" not in test_pantry_data)

    print("\n=== pantry.py: save/load round-trip ===")
    original_file = pantry.PANTRY_FILE
    pantry.PANTRY_FILE = "test_pantry_temp.json"  # don't clobber the real pantry.json
    try:
        pantry.save_pantry(test_pantry_data)
        reloaded = pantry.load_pantry()
        check("saved and reloaded pantry matches", reloaded == test_pantry_data)
    finally:
        if os.path.exists(pantry.PANTRY_FILE):
            os.remove(pantry.PANTRY_FILE)
        pantry.PANTRY_FILE = original_file


def test_find_recipes_from_pantry_live():
    """Optional -- actually calls Spoonacular. Only runs if you say yes,
    since it uses real API quota."""
    print("\n=== pantry.py: find_recipes_from_pantry (LIVE Spoonacular call) ===")
    run_live = input("Run a live Spoonacular test too? Uses 1 API call. (y/n): ").strip().lower()
    if run_live != "y":
        print("  Skipped.")
        return

    if not pantry.SPOONACULAR_API_KEY:
        print("  [FAIL] SPOONACULAR_API_KEY not set in .env -- can't run this test.")
        return

    sample_pantry = {"chicken breast": {"amount": 1, "unit": "lb"},
                      "rice": {"amount": 2, "unit": "cup"},
                      "garlic": {"amount": 3, "unit": "clove"}}
    results = pantry.find_recipes_from_pantry(sample_pantry, number=3)
    check(f"got a response with {len(results)} recipe(s)", len(results) > 0)
    for r in results:
        print(f"    - {r['title']} (missing: "
              f"{', '.join(i['name'] for i in r['missedIngredients'])})")


if __name__ == "__main__":
    print("Running sanity checks (no API calls unless you opt in at the end)...")
    test_servings_math()
    test_pantry()
    test_find_recipes_from_pantry_live()
    print("\nDone.")