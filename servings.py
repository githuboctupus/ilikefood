#servings/leftover match

import re

WEIGHT_TO_GRAMS = {
    "g": 1, "gram": 1, "grams": 1,
    "kg": 1000, "kilogram": 1000, "kilograms": 1000,
    "oz": 28.3495, "ounce": 28.3495, "ounces": 28.3495,
    "lb": 453.592, "lbs": 453.592, "pound": 453.592, "pounds": 453.592,
}

VOLUME_TO_ML = {
    "ml": 1, "milliliter": 1, "milliliters": 1,
    "l": 1000, "liter": 1000, "liters": 1000,
    "tsp": 4.92892, "teaspoon": 4.92892, "teaspoons": 4.92892,
    "tbsp": 14.7868, "tablespoon": 14.7868, "tablespoons": 14.7868,
    "cup": 236.588, "cups": 236.588,
    "fl oz": 29.5735, "fluid ounce": 29.5735, "fluid ounces": 29.5735,
}

# Whole-item units -- compared as counts, never converted to weight.
COUNT_UNITS = {"ct", "count", "each", "ea", ""}

# Approximate density (grams per mL) for common staples -- only used when
# converting a volume amount to weight or vice versa. Not exhaustive.
INGREDIENT_DENSITY = {
    "flour": 0.53, "all-purpose flour": 0.53, "cornstarch": 0.51,
    "sugar": 0.85, "brown sugar": 0.85, "powdered sugar": 0.56,
    "rice": 0.78, "salt": 1.2, "sea salt": 1.2,
    "vegetable oil": 0.92, "olive oil": 0.92, "oil": 0.92, "canola oil": 0.92,
    "butter": 0.96, "water": 1.0, "milk": 1.03, "honey": 1.42,
}


def _normalize_unit(unit):
    return (unit or "").strip().lower()


def to_grams(amount, unit, ingredient_name=""):
    """Best-effort (amount, unit) -> grams. Returns None if not confidently convertible."""
    if amount is None:
        return None
    u = _normalize_unit(unit)

    if u in WEIGHT_TO_GRAMS:
        return amount * WEIGHT_TO_GRAMS[u]

    if u in VOLUME_TO_ML:
        density = INGREDIENT_DENSITY.get(ingredient_name.strip().lower())
        if density is None:
            return None  # don't guess a density we don't actually know
        return amount * VOLUME_TO_ML[u] * density

    return None


def parse_package_size(size_str):
    """Parses a Kroger "size" string like "2 lb" or "4 ct" into (amount, unit)."""
    if not size_str:
        return None, None
    match = re.match(r"([\d.]+)\s*([a-zA-Z ]+)", size_str.strip())
    if not match:
        return None, None
    return float(match.group(1)), match.group(2).strip().lower()


def batches_from_one_ingredient(recipe_amount, recipe_unit, ingredient_name,
                                 package_amount, package_unit, num_packages=1):
    """
    Returns (max_batches, leftover, convertible: bool).
    Count-based units (e.g. "2 chicken breasts" vs a "4 ct" pack) are
    compared directly, not converted through weight.
    """
    r_unit = _normalize_unit(recipe_unit)
    p_unit = _normalize_unit(package_unit)

    if r_unit in COUNT_UNITS and p_unit in COUNT_UNITS:
        if not recipe_amount or recipe_amount <= 0:
            return None, None, False
        total_available = package_amount * num_packages
        max_batches = int(total_available // recipe_amount)
        leftover = total_available - (max_batches * recipe_amount)
        return max_batches, leftover, True

    recipe_g = to_grams(recipe_amount, recipe_unit, ingredient_name)
    package_g = to_grams(package_amount, package_unit, ingredient_name)
    if recipe_g is None or package_g is None or recipe_g <= 0:
        return None, None, False

    total_g = package_g * num_packages
    max_batches = int(total_g // recipe_g)
    leftover_g = total_g - (max_batches * recipe_g)
    return max_batches, leftover_g, True


def plan_for_serving_range(ingredient_needs, recipe_servings_per_batch,
                            min_servings, max_servings):
    """
    ingredient_needs: list of dicts, one per priced ingredient:
      {name, recipe_amount, recipe_unit, package_amount, package_unit, price_per_package}
    (skip ingredients that were free/not-priced before calling this)

    Tries every whole batch-count that lands inside [min_servings, max_servings]
    and returns the one with the lowest average leftover percentage across
    ingredients we could confidently convert. Ingredients we can't convert
    still get bought (assumed 1 package) but don't count toward the waste score.
    """
    min_batches = max(1, -(-min_servings // recipe_servings_per_batch))  # ceil
    max_batches = max_servings // recipe_servings_per_batch

    if max_batches < min_batches:
        return None

    best = None
    for batch_count in range(min_batches, max_batches + 1):
        purchases = []
        total_cost = 0.0
        waste_pcts = []

        for ing in ingredient_needs:
            r_unit = _normalize_unit(ing["recipe_unit"])
            p_unit = _normalize_unit(ing["package_unit"])
            needed = ing["recipe_amount"] * batch_count

            if r_unit in COUNT_UNITS and p_unit in COUNT_UNITS:
                packages_needed = max(1, -(-needed // ing["package_amount"]))
                bought = packages_needed * ing["package_amount"]
                leftover = bought - needed
                waste_pcts.append(leftover / bought if bought else 0)
                unit_label = ing["package_unit"]
            else:
                needed_g = to_grams(ing["recipe_amount"], ing["recipe_unit"], ing["name"])
                package_g = to_grams(ing["package_amount"], ing["package_unit"], ing["name"])
                if needed_g is None or package_g is None:
                    packages_needed = 1
                    leftover = None
                    unit_label = "?"
                else:
                    total_needed_g = needed_g * batch_count
                    packages_needed = max(1, -(-total_needed_g // package_g))
                    bought_g = packages_needed * package_g
                    leftover = bought_g - total_needed_g
                    waste_pcts.append(leftover / bought_g if bought_g else 0)
                    unit_label = "g"

            total_cost += packages_needed * ing["price_per_package"]
            purchases.append({
                "name": ing["name"],
                "packages_needed": packages_needed,
                "leftover": leftover,
                "unit_label": unit_label,
            })

        avg_waste = (sum(waste_pcts) / len(waste_pcts)) if waste_pcts else 1.0
        candidate = {
            "batch_count": batch_count,
            "total_servings": batch_count * recipe_servings_per_batch,
            "total_cost": round(total_cost, 2),
            "avg_waste_pct": round(avg_waste * 100, 1),
            "purchases": purchases,
        }
        if best is None or candidate["avg_waste_pct"] < best["avg_waste_pct"]:
            best = candidate

    return best