

import store_locator
import recipe_search
import pricing
import servings


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
        return None, None, None

    recipes = sorted(recipes, key=lambda r: r["price_per_serving"])
    print(f"\n{'#':3} {'Recipe':45} {'Est. price/serving'}")
    print("-" * 70)
    for i, r in enumerate(recipes, start=1):
        print(f"{i:<3} {r['title'][:44]:45} ${r['price_per_serving']}")

    choice = input("\nPick a recipe number: ").strip()
    try:
        chosen = recipes[int(choice) - 1]
    except (ValueError, IndexError):
        print("Invalid choice -- defaulting to the cheapest recipe.")
        chosen = recipes[0]

    return chosen, intolerances, dislikes


def handle_omissions(recipe):
    """Let the user drop ingredients up front; offer Spoonacular's substitute
    suggestion for anything they drop, and let them type in a replacement."""
    names = [i["name"] for i in recipe["ingredients"]]
    print("\nIngredients in this recipe:")
    for i, n in enumerate(names, start=1):
        print(f"  {i}. {n}")

    drop_raw = input(
        "\nAny ingredients to leave out? (numbers, comma separated, or blank): "
    ).strip()
    if not drop_raw:
        return names

    drop_indices = set()
    for tok in drop_raw.split(","):
        tok = tok.strip()
        if tok.isdigit() and 1 <= int(tok) <= len(names):
            drop_indices.add(int(tok) - 1)

    final_names = []
    for i, n in enumerate(names):
        if i not in drop_indices:
            final_names.append(n)
            continue
        subs = recipe_search.get_substitutes(n)
        if subs:
            print(f"\nDropping '{n}'. Spoonacular's suggested substitute(s):")
            for s in subs:
                print(f"  - {s}")
        else:
            print(f"\nDropping '{n}'. No substitute suggestion available for it.")
        replacement = input(
            f"  Type a replacement ingredient to price instead, or leave blank to just skip it: "
        ).strip()
        if replacement:
            final_names.append(replacement)

    return final_names


def run_servings_planner(recipe, chosen_products):
    """
    Uses the packages/prices actually chosen during pricing to figure out
    how many batches you can make, then optionally searches for the
    purchase plan that minimizes leftovers within a serving range you pick.
    """
    ingredient_by_name = {i["name"]: i for i in recipe["ingredients"]}
    servings_per_batch = recipe.get("servings") or 1

    ingredient_needs = []
    for name, product in chosen_products.items():
        if product.get("price") == 0.0 and product.get("size") is None:
            continue  # free/unpriced items like water -- not part of the batch math
        recipe_info = ingredient_by_name.get(name)
        if not recipe_info or not recipe_info.get("amount"):
            continue
        pkg_amount, pkg_unit = servings.parse_package_size(product.get("size"))
        if pkg_amount is None:
            continue
        ingredient_needs.append({
            "name": name,
            "recipe_amount": recipe_info["amount"],
            "recipe_unit": recipe_info["unit"],
            "package_amount": pkg_amount,
            "package_unit": pkg_unit,
            "price_per_package": product["price"],
        })

    if not ingredient_needs:
        print("\n(Not enough size/unit data to run the servings calculator this time.)")
        return

    print(f"\n--- Servings from what you bought (1 package each) ---")
    max_batches_overall = None
    for ing in ingredient_needs:
        batches, leftover, ok = servings.batches_from_one_ingredient(
            ing["recipe_amount"], ing["recipe_unit"], ing["name"],
            ing["package_amount"], ing["package_unit"],
        )
        if not ok:
            print(f"  {ing['name']}: can't calculate (unit conversion not available)")
            continue
        print(f"  {ing['name']}: enough for {batches} batch(es), "
              f"~{leftover:.1f} {ing['package_unit']} left over")
        if max_batches_overall is None or batches < max_batches_overall:
            max_batches_overall = batches

    if max_batches_overall is not None:
        print(f"\nLimiting ingredient allows {max_batches_overall} batch(es) "
              f"= ~{max_batches_overall * servings_per_batch} total servings "
              f"from what you'd buy by default (1 package each).")

    want_optimize = input(
        "\nWant to find the purchase plan that minimizes leftovers for a "
        "target serving range? (y/n): "
    ).strip().lower()
    if want_optimize != "y":
        return

    try:
        min_s = int(input("Minimum servings you want: ").strip())
        max_s = int(input("Maximum servings you want: ").strip())
    except ValueError:
        print("Needs whole numbers -- skipping the optimizer.")
        return

    plan = servings.plan_for_serving_range(ingredient_needs, servings_per_batch, min_s, max_s)
    if not plan:
        print("No achievable batch count fits that range given this recipe's serving size.")
        return

    print(f"\n--- Best plan for {min_s}-{max_s} servings ---")
    print(f"Makes {plan['batch_count']} batch(es) = {plan['total_servings']} servings")
    print(f"Total cost: ${plan['total_cost']:.2f}  |  Avg. leftover: {plan['avg_waste_pct']}%")
    for p in plan["purchases"]:
        leftover_str = f"~{p['leftover']:.1f} {p['unit_label']} left over" if p["leftover"] is not None else "leftover unknown"
        print(f"  {p['name']}: buy {p['packages_needed']} package(s) -- {leftover_str}")


def main():
    zip_code = input("Enter your zip code: ").strip()

    store = choose_store(zip_code)
    if not store:
        return

    recipe, intolerances, dislikes = choose_recipe()
    if not recipe:
        return

    ingredient_names = handle_omissions(recipe)

    prefer_organic = input("\nPrefer organic when available? (y/n): ").strip().lower() == "y"
    avoid_processed = input("Avoid heavily processed options when possible? (y/n): ").strip().lower() == "y"

    print(f"\nPricing '{recipe['title']}' at {store['name']}...")
    total, missing, skipped, chosen_products = pricing.price_recipe(
        ingredient_names, store["location_id"], prefer_organic, avoid_processed,
        intolerances, dislikes, interactive=True,
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
    print(f"Estimated total cost: ${total:.2f}")
    if missing:
        print(f"Ingredients not priced: {', '.join(missing)}")
    if skipped:
        print(f"Ingredients skipped by choice: {', '.join(skipped)}")

    print(f"\nInstructions:\n{recipe['instructions']}")
    if recipe.get("source_url"):
        print(f"\nSource: {recipe['source_url']}")

    run_servings_planner(recipe, chosen_products)


if __name__ == "__main__":
    main()