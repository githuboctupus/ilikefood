

import os

import requests
from dotenv import load_dotenv

load_dotenv()

SPOONACULAR_API_KEY = os.environ.get("SPOONACULAR_API_KEY")
SEARCH_URL = "https://api.spoonacular.com/recipes/complexSearch"
SUBSTITUTES_URL = "https://api.spoonacular.com/food/ingredients/substitutes"


def get_substitutes(ingredient_name):
    """
    Returns a list of substitute suggestion strings (e.g. "Use 1 cup
    applesauce for 1 cup oil"), or None if Spoonacular has no suggestion
    for this ingredient. These are their own curated suggestions, not
    something we compute -- treat as a suggestion to consider, not a
    guaranteed 1-for-1 swap in every recipe.
    """
    params = {"apiKey": SPOONACULAR_API_KEY, "ingredientName": ingredient_name}
    r = requests.get(SUBSTITUTES_URL, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "failure" or not data.get("substitutes"):
        return None
    return data["substitutes"]


def search_recipes(query="", diet=None, intolerances=None, exclude_ingredients=None, number=5):
    """
    query: plain text craving, e.g. "spicy chicken" -- can be left blank
    diet: e.g. "vegetarian", "vegan", "gluten free", "ketogenic"
    intolerances: list like ["dairy", "peanut"]
    exclude_ingredients: list of disliked ingredients like ["cilantro", "mushrooms"]
    number: how many recipes to return (keep modest -- costs more quota per result)
    """
    params = {
        "apiKey": SPOONACULAR_API_KEY,
        "query": query,
        "number": number,
        "addRecipeInformation": True,
        "addRecipeNutrition": True,
        "fillIngredients": True,
    }
    if diet:
        params["diet"] = diet
    if intolerances:
        params["intolerances"] = ",".join(intolerances)
    if exclude_ingredients:
        params["excludeIngredients"] = ",".join(exclude_ingredients)

    r = requests.get(SEARCH_URL, params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("results", [])


def _get_nutrient(nutrients, name):
    for n in nutrients:
        if n.get("name") == name:
            return round(n.get("amount", 0), 1)
    return None


def parse_recipe(raw):
    """Pull out just the fields we actually care about from Spoonacular's response."""
    nutrients = raw.get("nutrition", {}).get("nutrients", [])
    ingredients = [
        {
            "name": ing.get("name"),
            "amount": ing.get("amount"),
            "unit": ing.get("unit"),
            "aisle": ing.get("aisle"),
        }
        for ing in raw.get("extendedIngredients", [])
    ]

    return {
        "title": raw.get("title"),
        "ready_minutes": raw.get("readyInMinutes"),
        "servings": raw.get("servings"),
        "price_per_serving": round(raw.get("pricePerServing", 0) / 100, 2),  # cents -> dollars
        "calories": _get_nutrient(nutrients, "Calories"),
        "protein_g": _get_nutrient(nutrients, "Protein"),
        "carbs_g": _get_nutrient(nutrients, "Carbohydrates"),
        "fat_g": _get_nutrient(nutrients, "Fat"),
        "ingredients": ingredients,
        "instructions": raw.get("instructions") or "No instructions provided -- see source link.",
        "source_url": raw.get("sourceUrl"),
    }


def print_recipes(recipes):
    if not recipes:
        print("No recipes matched. Try loosening a filter or the craving text.")
        return

    recipes = sorted(recipes, key=lambda r: r["price_per_serving"])

    for r in recipes:
        print(f"\n{r['title']}")
        print(f"  Ready in: {r['ready_minutes']} min | Servings: {r['servings']}")
        print(f"  Est. price/serving: ${r['price_per_serving']}")
        print(f"  Calories: {r['calories']} | Protein: {r['protein_g']}g | "
              f"Carbs: {r['carbs_g']}g | Fat: {r['fat_g']}g")
        print(f"  Ingredients ({len(r['ingredients'])}):")
        for i in r["ingredients"]:
            amount = i["amount"]
            unit = i["unit"] or ""
            print(f"    - {amount} {unit} {i['name']}".replace("  ", " "))
        print(f"  Instructions: {r['instructions']}")
        if r["source_url"]:
            print(f"  Source: {r['source_url']}")


DIET_OPTIONS = [
    "Gluten Free", "Ketogenic", "Vegetarian", "Lacto-Vegetarian", "Ovo-Vegetarian",
    "Vegan", "Pescetarian", "Paleo", "Primal", "Low FODMAP", "Whole30",
]

INTOLERANCE_OPTIONS = [
    "Dairy", "Egg", "Gluten", "Grain", "Peanut", "Seafood",
    "Sesame", "Shellfish", "Soy", "Sulfite", "Tree Nut", "Wheat",
]


def main():
    if not SPOONACULAR_API_KEY:
        print("Missing SPOONACULAR_API_KEY in your .env file.")
        return

    craving = input("What are you in the mood for? (blank = surprise me): ").strip()

    print(f"\nDiet options: {', '.join(DIET_OPTIONS)}")
    diet = input("Any diet? (pick one from above, or blank): ").strip() or None

    print(f"\nIntolerance options: {', '.join(INTOLERANCE_OPTIONS)}")
    intolerances_raw = input("Any intolerances? (comma separated, or blank): ").strip()

    dislikes_raw = input("\nAny ingredients you just don't like? (any words, comma separated, or blank): ").strip()

    intolerances = [x.strip() for x in intolerances_raw.split(",") if x.strip()] or None
    dislikes = [" ".join(x.strip().split()) for x in dislikes_raw.split(",") if x.strip()] or None

    raw_results = search_recipes(
        query=craving,
        diet=diet,
        intolerances=intolerances,
        exclude_ingredients=dislikes,
        number=5,
    )
    recipes = [parse_recipe(r) for r in raw_results]
    print_recipes(recipes)


if __name__ == "__main__":
    main()