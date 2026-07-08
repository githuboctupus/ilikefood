

import store_locator
import recipe_search
import pricing


def choose_store(zip_code):
    print(f"\nFinding Kroger stores near {zip_code}...")
    user_lat, user_lon = store_locator.geocode_zip(zip_code)
    stores = store_locator.find_kroger_stores(zip_code)

    if not stores:
        print("No Kroger stores found near that zip code.")
        return None

    destinations = [(s["lat"], s["lon"]) for s in stores]
    drive_times = store_locator.get_drive_times((user_lat, user_lon), destinations)
    for s, (minutes, miles) in zip(stores, drive_times):
        s["drive_minutes"] = minutes
        s["drive_miles"] = miles

    stores.sort(key=lambda s: s["drive_minutes"] if s["drive_minutes"] is not None else 999)

    closest = stores[0]
    print(f"Using closest store: {closest['name']} "
          f"({closest['drive_minutes']} min drive, {closest['drive_miles']} mi)")
    return closest


def choose_recipe():
    craving = input("\nWhat are you in the mood for? (blank = surprise me): ").strip()

    print(f"Diet options: {', '.join(recipe_search.DIET_OPTIONS)}")
    diet = input("Any diet? (or blank): ").strip() or None

    print(f"Intolerance options: {', '.join(recipe_search.INTOLERANCE_OPTIONS)}")
    intolerances_raw = input("Any intolerances? (comma separated, or blank): ").strip()
    dislikes_raw = input("Any ingredients you don't like? (comma separated, or blank): ").strip()

    intolerances = [x.strip() for x in intolerances_raw.split(",") if x.strip()] or None
    dislikes = [" ".join(x.strip().split()) for x in dislikes_raw.split(",") if x.strip()] or None

    raw_results = recipe_search.search_recipes(
        query=craving,
        diet=diet,
        intolerances=intolerances,
        exclude_ingredients=dislikes,
        number=5,
    )
    recipes = [recipe_search.parse_recipe(r) for r in raw_results]

    if not recipes:
        print("No recipes matched. Try loosening a filter.")
        return None

    recipes = sorted(recipes, key=lambda r: r["price_per_serving"])
    print(f"\n{'#':3} {'Recipe':45} {'Est. price/serving'}")
    print("-" * 70)
    for i, r in enumerate(recipes, start=1):
        print(f"{i:<3} {r['title'][:44]:45} ${r['price_per_serving']}")

    choice = input("\nPick a recipe number: ").strip()
    try:
        return recipes[int(choice) - 1]
    except (ValueError, IndexError):
        print("Invalid choice -- defaulting to the cheapest recipe.")
        return recipes[0]


def main():
    zip_code = input("Enter your zip code: ").strip()

    store = choose_store(zip_code)
    if not store:
        return

    recipe = choose_recipe()
    if not recipe:
        return

    prefer_organic = input("\nPrefer organic when available? (y/n): ").strip().lower() == "y"
    avoid_processed = input("Avoid heavily processed options when possible? (y/n): ").strip().lower() == "y"

    print(f"\nPricing '{recipe['title']}' at {store['name']}...")
    ingredient_names = [i["name"] for i in recipe["ingredients"]]
    total, missing = pricing.price_recipe(
        ingredient_names, store["location_id"], prefer_organic, avoid_processed
    )

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Recipe: {recipe['title']}")
    print(f"Ready in: {recipe['ready_minutes']} min | Servings: {recipe['servings']}")
    print(f"Calories: {recipe['calories']} | Protein: {recipe['protein_g']}g | "
          f"Carbs: {recipe['carbs_g']}g | Fat: {recipe['fat_g']}g")
    print(f"Store: {store['name']} "
          f"({store['drive_minutes']} min drive, {store['drive_miles']} mi)")
    print(f"Estimated total cost (cheapest match per ingredient): ${total:.2f}")
    if missing:
        print(f"Ingredients not found at this store: {', '.join(missing)}")


if __name__ == "__main__":
    main()