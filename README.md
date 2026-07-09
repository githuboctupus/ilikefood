# Recipe Grocery Planner UI

A small Flask UI for your recipe + Kroger pricing app.

## What it does

- Searches recipes with Spoonacular.
- Finds nearby Kroger-family stores by zip code.
- Shows every Kroger product option found for each recipe ingredient.
- Shows useful product details from the food item/package, including:
  - product ID
  - brand
  - description
  - price
  - Kroger package size
  - grams/mL/count when the package size can be converted confidently
  - categories
  - organic / non-GMO tags when Kroger provides them
- Lets the user choose which product to buy for each ingredient.
- Calculates estimated total cost and basic leftover math.

## Setup

```bash
cd grocery_ui
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env` with your real API keys:

```bash
SPOONACULAR_API_KEY=...
KROGER_CLIENT_ID=...
KROGER_CLIENT_SECRET=...
ORS_API_KEY=...
FLASK_SECRET_KEY=any-random-string
```

Then run:

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Notes

- This is built for local development, not production hosting.
- Product allergy filtering is only text matching against product name/brand, not a verified allergen database.
- Gram conversions are only shown when the package unit is weight-based or when your `servings.py` has a known density for that ingredient.
