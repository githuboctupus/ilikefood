

from __future__ import annotations

import os
import uuid
from typing import Any

from flask import Flask, redirect, render_template_string, request, url_for
from dotenv import load_dotenv

import pricing
import recipe_search
import servings
import store_locator

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")

# Simple in-memory cache. Good enough for a local student project.
# Restarting Flask clears it.
CACHE: dict[str, dict[str, Any]] = {}


DIET_OPTIONS = [""] + recipe_search.DIET_OPTIONS
INTOLERANCE_OPTIONS = recipe_search.INTOLERANCE_OPTIONS


def split_csv(value: str | None) -> list[str] | None:
    items = [" ".join(x.strip().split()) for x in (value or "").split(",") if x.strip()]
    return items or None


def check_env() -> list[str]:
    needed = [
        "SPOONACULAR_API_KEY",
        "KROGER_CLIENT_ID",
        "KROGER_CLIENT_SECRET",
        "ORS_API_KEY",
    ]
    return [name for name in needed if not os.environ.get(name)]


def find_stores(zip_code: str) -> list[dict[str, Any]]:
    user_lat, user_lon = store_locator.geocode_zip(zip_code)
    stores = [s for s in store_locator.find_kroger_stores(zip_code) if s.get("lat") and s.get("lon")]
    if not stores:
        return []
    drive_times = store_locator.get_drive_times(
        (user_lat, user_lon), [(s["lat"], s["lon"]) for s in stores]
    )
    for s, (minutes, miles) in zip(stores, drive_times):
        s["drive_minutes"] = minutes
        s["drive_miles"] = miles
    stores.sort(key=lambda s: s["drive_minutes"] if s["drive_minutes"] is not None else 999)
    return stores


def format_money(value: Any) -> str:
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return "price unavailable"


def package_details(ingredient_name: str, product: dict[str, Any]) -> dict[str, Any]:
    """Attach size details such as grams, mL, count, and unit confidence."""
    size = product.get("size")
    amount, unit = servings.parse_package_size(size)
    grams = None
    ml = None
    count = None
    detail = "Package size unavailable"

    if amount is not None and unit:
        normalized_unit = unit.strip().lower()
        grams = servings.to_grams(amount, normalized_unit, ingredient_name)
        if grams is not None:
            detail = f"{size} ≈ {grams:.1f} g"
        elif normalized_unit in servings.VOLUME_TO_ML:
            ml = amount * servings.VOLUME_TO_ML[normalized_unit]
            detail = f"{size} ≈ {ml:.1f} mL"
        elif normalized_unit in servings.COUNT_UNITS:
            count = amount
            detail = f"{size} = {amount:g} item(s)"
        else:
            detail = f"{size} (could not convert to grams confidently)"

    enriched = dict(product)
    enriched.update({
        "package_amount": amount,
        "package_unit": unit,
        "package_grams": grams,
        "package_ml": ml,
        "package_count": count,
        "package_detail": detail,
        "price_label": format_money(product.get("price")),
    })
    return enriched


def build_ingredient_options(
    recipe: dict[str, Any],
    location_id: str,
    prefer_organic: bool,
    avoid_processed: bool,
    intolerances: list[str] | None,
    dislikes: list[str] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    ingredient_blocks: list[dict[str, Any]] = []
    errors: list[str] = []

    for index, ing in enumerate(recipe.get("ingredients", [])):
        name = ing.get("name") or "unknown ingredient"
        amount = ing.get("amount")
        unit = ing.get("unit") or ""

        if name.strip().lower() in pricing.SKIP_PRICING_TERMS:
            ingredient_blocks.append({
                "index": index,
                "name": name,
                "recipe_amount": amount,
                "recipe_unit": unit,
                "aisle": ing.get("aisle"),
                "options": [{
                    "id": "FREE",
                    "description": name,
                    "brand": "",
                    "size": "free",
                    "price": 0.0,
                    "price_label": "$0.00",
                    "package_detail": "Water/ice is automatically treated as free and not added to the shopping list.",
                    "tags": ["free", "auto"],
                    "categories": [],
                }],
                "flagged_count": 0,
                "is_free": True,
            })
            continue

        try:
            raw_options = pricing.search_products(name, location_id, limit=10)
            safe_options, flagged = pricing.filter_unsafe_products(raw_options, intolerances, dislikes)
        except Exception as exc:  # display the failure but keep the page alive
            safe_options, flagged = [], []
            errors.append(f"Could not load product options for {name}: {exc}")

        display_order = pricing.pick_display_options(safe_options, prefer_organic, avoid_processed)
        best_id = display_order[0]["id"] if display_order else None
        cheapest_id = min(safe_options, key=lambda o: o["price"])["id"] if safe_options else None

        options = []
        for o in safe_options:
            enriched = package_details(name, o)
            tags = []
            if o.get("id") == best_id:
                tags.append("recommended")
            if o.get("id") == cheapest_id:
                tags.append("cheapest")
            if o.get("organic_claim"):
                tags.append("organic")
            if o.get("non_gmo"):
                tags.append("non-GMO")
            enriched["tags"] = tags
            options.append(enriched)

        ingredient_blocks.append({
            "index": index,
            "name": name,
            "recipe_amount": amount,
            "recipe_unit": unit,
            "aisle": ing.get("aisle"),
            "options": options,
            "flagged_count": len(flagged),
            "is_free": False,
        })

    return ingredient_blocks, errors


BASE_CSS = """
<style>
:root { --bg:#f6f7fb; --card:#fff; --ink:#18202f; --muted:#657083; --line:#e4e8f0; --accent:#355cff; --soft:#eef2ff; --danger:#a13b26; }
* { box-sizing: border-box; }
body { margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Arial, sans-serif; background:var(--bg); color:var(--ink); }
header { padding:34px 22px 24px; background:linear-gradient(135deg, #17213b, #374b91); color:white; }
main { max-width:1120px; margin:0 auto; padding:24px 18px 50px; }
h1 { margin:0; font-size:32px; letter-spacing:-.03em; }
h2 { margin:28px 0 12px; font-size:22px; }
h3 { margin:0 0 8px; font-size:18px; }
p { line-height:1.45; }
.sub { opacity:.84; max-width:760px; margin:8px 0 0; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; box-shadow:0 8px 20px rgba(20, 30, 60, .05); padding:16px; margin:12px 0; }
.grid { display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:14px; }
.grid3 { display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:14px; }
label { display:block; font-weight:650; margin:0 0 6px; }
input[type='text'], input[type='number'], select, textarea { width:100%; border:1px solid var(--line); border-radius:10px; padding:11px 12px; background:#fff; font:inherit; }
textarea { min-height:72px; }
.checks { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:8px; }
.check { font-weight:500; background:#fafbff; border:1px solid var(--line); border-radius:10px; padding:9px 10px; }
button, .button { border:0; border-radius:10px; background:var(--accent); color:white; font-weight:750; padding:12px 18px; cursor:pointer; text-decoration:none; display:inline-block; }
.button.secondary { background:#edf1ff; color:#233a85; }
.muted { color:var(--muted); }
.row { display:flex; gap:12px; align-items:center; justify-content:space-between; }
.recipe-list { display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:14px; }
.badge { display:inline-flex; align-items:center; border-radius:999px; padding:4px 9px; font-size:12px; font-weight:750; background:var(--soft); color:#223a95; margin:2px 4px 2px 0; }
.badge.warn { background:#fff2df; color:#8a5200; }
.badge.danger { background:#ffece8; color:var(--danger); }
.product-option { border:1px solid var(--line); border-radius:10px; padding:10px; margin:8px 0; display:block; }
.product-option:has(input:checked) { border-color:var(--accent); background:#fbfcff; box-shadow:0 0 0 3px rgba(53,92,255,.10); }
.ingredient-summary { cursor:pointer; list-style:none; }
.ingredient-summary::-webkit-details-marker { display:none; }
.ingredient-toolbar { position:sticky; top:0; z-index:2; }
.filter-row { display:flex; gap:10px; align-items:center; }
.count-pill { white-space:nowrap; border:1px solid var(--line); border-radius:999px; padding:8px 11px; color:var(--muted); font-weight:750; background:#fafbff; }
.no-ingredient-results[hidden] { display:none; }
.status { min-width:135px; text-align:right; font-weight:800; color:var(--muted); }
.status.done { color:#17803d; }
.status.ignore { color:#8a5200; }
.status.free { color:#17803d; }
.search-box { margin:12px 0; }
.choice-row { display:flex; align-items:flex-start; gap:10px; }
.choice-row input { margin-top:4px; flex:0 0 auto; }
.quick-choice { background:#fbfcff; }
.hidden-by-search { display:none; }
.option-list { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:10px; align-items:stretch; }
.option-list .product-option { margin:0; height:100%; }
.product-title { display:block; font-weight:760; line-height:1.25; }
.product-meta { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
.meta { background:#f8f9fc; border-radius:8px; padding:6px 8px; font-size:13px; }
.meta b { display:inline; font-size:11px; color:var(--muted); margin-right:4px; }
.size-note { margin-top:8px; font-size:13px; color:var(--muted); }
.product-id { margin-top:6px; font-size:11px; color:var(--muted); word-break:break-word; }
.category-line { margin:6px 0 0; font-size:12px; color:var(--muted); }
.error { background:#fff2f0; color:#8d2b1e; border:1px solid #ffd6cf; padding:12px; border-radius:14px; }
.total { font-size:30px; font-weight:850; letter-spacing:-.03em; }
@media (max-width:760px) { .grid, .grid3, .recipe-list, .checks, .product-meta, .option-list { grid-template-columns:1fr; } .row, .filter-row { display:block; } .count-pill { display:inline-flex; margin-top:8px; } .status { text-align:left; margin-top:8px; } }
</style>
"""


HOME_TEMPLATE = BASE_CSS + """
<header>
  <h1>Recipe Grocery Planner</h1>
  <p class="sub">Search recipes, choose a nearby Kroger store, then compare every product option for each ingredient with price and package-size details.</p>
</header>
<main>
  {% if missing_env %}
    <div class="error"><b>Missing API keys:</b> {{ missing_env|join(', ') }}. Add them to your <code>.env</code> file before using the live app.</div>
  {% endif %}
  <form class="card" method="post" action="{{ url_for('search') }}">
    <div class="grid">
      <div>
        <label>Zip code</label>
        <input name="zip_code" type="text" placeholder="77005" required>
      </div>
      <div>
        <label>What are you in the mood for?</label>
        <input name="craving" type="text" placeholder="spicy chicken, pasta, cookies...">
      </div>
      <div>
        <label>Diet</label>
        <select name="diet">
          {% for d in diet_options %}<option value="{{ d }}">{{ d or 'No diet filter' }}</option>{% endfor %}
        </select>
      </div>
      <div>
        <label>Ingredients you dislike</label>
        <input name="dislikes" type="text" placeholder="cilantro, mushrooms">
      </div>
    </div>
    <h3 style="margin-top:20px">Intolerances</h3>
    <div class="checks">
      {% for option in intolerance_options %}
        <label class="check"><input type="checkbox" name="intolerances" value="{{ option }}"> {{ option }}</label>
      {% endfor %}
    </div>
    <div style="margin-top:18px">
      <button type="submit">Search recipes</button>
    </div>
  </form>
</main>
"""


SEARCH_TEMPLATE = BASE_CSS + """
<header>
  <h1>Pick a recipe and store</h1>
  <p class="sub">Recipes are sorted by Spoonacular estimated price per serving. Store drive times use your zip code.</p>
</header>
<main>
  {% if errors %}{% for error in errors %}<div class="error">{{ error }}</div>{% endfor %}{% endif %}
  <form method="post" action="{{ url_for('price') }}">
    <input type="hidden" name="cache_id" value="{{ cache_id }}">
    <div class="card">
      <h2 style="margin-top:0">Nearby stores</h2>
      {% for s in stores %}
        <label class="product-option">
          <input type="radio" name="store_i" value="{{ loop.index0 }}" {% if loop.first %}checked{% endif %}>
          <span class="product-title">{{ s.name }}</span>
          <div class="muted">{{ s.address }}, {{ s.city }} · {{ s.drive_minutes }} min · {{ s.drive_miles }} mi · Location ID {{ s.location_id }}</div>
        </label>
      {% endfor %}
    </div>

    <h2>Recipes</h2>
    <div class="recipe-list">
      {% for r in recipes %}
        <label class="card">
          <input type="radio" name="recipe_i" value="{{ loop.index0 }}" {% if loop.first %}checked{% endif %}>
          <h3>{{ r.title }}</h3>
          <p class="muted">{{ r.ready_minutes }} min · {{ r.servings }} servings · estimated {{ money(r.price_per_serving) }}/serving</p>
          <p><span class="badge">{{ r.calories }} cal</span><span class="badge">{{ r.protein_g }}g protein</span><span class="badge">{{ r.carbs_g }}g carbs</span><span class="badge">{{ r.fat_g }}g fat</span></p>
        </label>
      {% endfor %}
    </div>

    <div class="card">
      <h2 style="margin-top:0">Product preferences</h2>
      <label class="check"><input type="checkbox" name="prefer_organic" value="yes"> Prefer organic when available</label>
      <label class="check" style="margin-top:8px"><input type="checkbox" name="avoid_processed" value="yes"> Avoid heavily processed options when possible</label>
      <div style="margin-top:16px"><button type="submit">Show product options</button> <a class="button secondary" href="{{ url_for('home') }}">Start over</a></div>
    </div>
  </form>
</main>
"""


PRICE_TEMPLATE = BASE_CSS + """
<header>
  <h1>Choose products</h1>
  <p class="sub">Filter the ingredient list, open only the ingredient you need, then search or choose from compact product options.</p>
</header>
<main>
  {% if errors %}{% for error in errors %}<div class="error">{{ error }}</div>{% endfor %}{% endif %}
  <div class="card row">
    <div>
      <h2 style="margin:0">{{ recipe.title }}</h2>
      <p class="muted">{{ recipe.ready_minutes }} min · {{ recipe.servings }} servings · {{ store.name }} · {{ store.drive_minutes }} min away</p>
    </div>
    <a class="button secondary" href="{{ url_for('home') }}">Start over</a>
  </div>

  <form method="post" action="{{ url_for('summary') }}">
    <input type="hidden" name="cache_id" value="{{ cache_id }}">
    <div class="card ingredient-toolbar">
      <label for="ingredient-filter">Find an ingredient</label>
      <div class="filter-row">
        <input id="ingredient-filter" type="text" placeholder="Search by ingredient or aisle..." data-ingredient-filter>
        <span class="count-pill" id="ingredient-count">{{ ingredients|length }} ingredients</span>
      </div>
    </div>
    <div class="error no-ingredient-results" id="no-ingredient-results" hidden>No ingredients match that search.</div>
    {% for ing in ingredients %}
      <details class="card ingredient-card" {% if loop.first %}open{% endif %} data-ingredient-index="{{ ing.index }}" data-ingredient-text="{{ ing.name }} {{ ing.aisle or '' }}">
        <summary class="ingredient-summary row">
          <div>
            <h2 style="margin:0">{{ ing.name }}</h2>
            <p class="muted">Recipe needs: {{ ing.recipe_amount }} {{ ing.recipe_unit }}{% if ing.aisle %} · Aisle: {{ ing.aisle }}{% endif %}</p>
            {% if ing.flagged_count %}<span class="badge warn">{{ ing.flagged_count }} hidden by filters</span>{% endif %}
          </div>
          <div class="status {% if ing.is_free %}free{% endif %}" id="status_{{ ing.index }}">{% if ing.is_free %}✓ free{% else %}auto ✓{% endif %}</div>
        </summary>

        {% if ing.is_free %}
          <input type="hidden" name="choice_{{ ing.index }}" value="FREE">
          <p class="badge">✓ Auto-free</p>
          <p class="muted">Water/ice is treated as free by itself, so it is not searched at Kroger and does not add cost.</p>
        {% else %}
          {% if not ing.options %}
            <p class="error">No safe priced product options found for this ingredient at this store.</p>
            <label class="product-option quick-choice">
              <span class="choice-row"><input type="radio" name="choice_{{ ing.index }}" value="IGNORE" checked data-choice-label="ignored"> <span><b>Ignore this ingredient</b><br><span class="muted">Use this if you already have it or do not want to buy it.</span></span></span>
            </label>
          {% else %}
            <div class="option-list">
              <label class="product-option quick-choice">
                <span class="choice-row"><input type="radio" name="choice_{{ ing.index }}" value="AUTO" checked data-choice-label="auto ✓"> <span><b>Auto-pick best/cheapest option</b><br><span class="muted">Uses the option marked recommended, then cheapest/default.</span></span></span>
              </label>
              <label class="product-option quick-choice">
                <span class="choice-row"><input type="radio" name="choice_{{ ing.index }}" value="IGNORE" data-choice-label="ignored"> <span><b>Ignore this ingredient</b><br><span class="muted">Use this if you already have it.</span></span></span>
              </label>
            </div>

            <input class="search-box" type="text" placeholder="Search {{ ing.name }} options by brand, price, size, category..." data-search-for="{{ ing.index }}">

            <div class="option-list">
            {% for o in ing.options %}
              <label class="product-option searchable-option" data-search-block="{{ ing.index }}" data-search-text="{{ (o.brand or '') ~ ' ' ~ o.description ~ ' ' ~ (o.size or '') ~ ' ' ~ o.price_label ~ ' ' ~ o.package_detail ~ ' ' ~ (o.categories|join(' ')) ~ ' ' ~ (o.tags|join(' ')) }}">
                <span class="choice-row">
                  <input type="radio" name="choice_{{ ing.index }}" value="{{ o.id }}" data-choice-label="✓ chosen">
                  <span style="width:100%">
                    <span class="product-title">{% if o.brand %}{{ o.brand }} · {% endif %}{{ o.description }}</span>
                    <div>{% for tag in o.tags %}<span class="badge">{{ tag }}</span>{% endfor %}</div>
                    <div class="product-meta">
                      <div class="meta"><b>Price</b>{{ o.price_label }}</div>
                      <div class="meta"><b>Size</b>{{ o.size or 'not listed' }}</div>
                    </div>
                    <div class="size-note">{{ o.package_detail }}</div>
                    {% if o.categories %}<p class="category-line">{{ o.categories|join(' › ') }}</p>{% endif %}
                    <div class="product-id">ID {{ o.id }}</div>
                  </span>
                </span>
              </label>
            {% endfor %}
            </div>
          {% endif %}
        {% endif %}
      </details>
    {% endfor %}
    <div class="card">
      <button type="submit">Calculate total and leftovers</button>
    </div>
  </form>
</main>
<script>
function updateStatuses() {
  document.querySelectorAll('.ingredient-card').forEach(card => {
    const idx = card.dataset.ingredientIndex;
    const status = document.getElementById('status_' + idx);
    const checked = card.querySelector('input[name="choice_' + idx + '"]:checked');
    if (!status || !checked) return;
    status.classList.remove('done', 'ignore');
    const label = checked.dataset.choiceLabel || (checked.value === 'FREE' ? '✓ free' : '✓ chosen');
    status.textContent = label;
    if (checked.value === 'IGNORE') status.classList.add('ignore');
    else status.classList.add('done');
  });
}

function updateIngredientFilter() {
  const input = document.querySelector('[data-ingredient-filter]');
  const count = document.getElementById('ingredient-count');
  const empty = document.getElementById('no-ingredient-results');
  const cards = Array.from(document.querySelectorAll('.ingredient-card'));
  if (!input || !count) return;
  const q = input.value.trim().toLowerCase();
  let visible = 0;
  cards.forEach(card => {
    const text = (card.dataset.ingredientText || '').toLowerCase();
    const show = !q || text.includes(q);
    card.classList.toggle('hidden-by-search', !show);
    if (show) visible += 1;
  });
  count.textContent = visible + ' of ' + cards.length + ' ingredients';
  if (empty) empty.hidden = visible !== 0;
}

document.addEventListener('change', event => {
  if (event.target.matches('input[type="radio"]')) updateStatuses();
});

document.querySelectorAll('[data-search-for]').forEach(input => {
  input.addEventListener('input', () => {
    const idx = input.dataset.searchFor;
    const q = input.value.trim().toLowerCase();
    document.querySelectorAll('[data-search-block="' + idx + '"]').forEach(block => {
      const text = (block.dataset.searchText || '').toLowerCase();
      block.classList.toggle('hidden-by-search', q && !text.includes(q));
    });
  });
});

const ingredientFilter = document.querySelector('[data-ingredient-filter]');
if (ingredientFilter) ingredientFilter.addEventListener('input', updateIngredientFilter);
updateStatuses();
updateIngredientFilter();
</script>
"""


SUMMARY_TEMPLATE = BASE_CSS + """
<header>
  <h1>Summary</h1>
  <p class="sub">Your selected grocery products, ignored ingredients, auto-free items, total estimated store cost, and what the package-size math can infer.</p>
</header>
<main>
  <div class="card">
    <h2 style="margin-top:0">{{ recipe.title }}</h2>
    <p class="muted">Store: {{ store.name }} · {{ recipe.servings }} servings per batch</p>
    <div class="total">{{ money(total) }}</div>
    <p class="muted">Estimated total for selected purchasable items only. Ignored items and water/ice are not included.</p>
  </div>

  <div class="card">
    <h2 style="margin-top:0">Ingredient decisions</h2>
    {% for row in selected %}
      <div class="product-option">
        <div class="row">
          <div>
            <h3>{{ row.ingredient }}</h3>
            {% if row.status == 'ignored' %}
              <p><span class="badge warn">ignored</span> <span class="muted">Not added to shopping total.</span></p>
            {% elif row.status == 'free' %}
              <p><span class="badge">free</span> <span class="muted">Water/ice is auto-free and not added to shopping total.</span></p>
            {% else %}
              <p class="product-title">{% if row.product.brand %}{{ row.product.brand }} · {% endif %}{{ row.product.description }}</p>
              <p class="muted">{{ row.product.price_label }} · {{ row.product.package_detail }}{% if row.status == 'auto' %} · auto-picked{% endif %}</p>
            {% endif %}
          </div>
        </div>
      </div>
    {% endfor %}
  </div>

  {% if leftovers %}
    <div class="card">
      <h2 style="margin-top:0">Servings from one package each</h2>
      {% for row in leftovers %}
        <p><b>{{ row.name }}</b>: {{ row.message }}</p>
      {% endfor %}
      {% if limiting_batches is not none %}
        <p class="badge">Limiting ingredient allows about {{ limiting_batches }} batch(es), or {{ limiting_servings }} serving(s).</p>
      {% endif %}
    </div>
  {% endif %}

  <div class="card">
    <h2 style="margin-top:0">Instructions</h2>
    <p>{{ recipe.instructions|safe }}</p>
    {% if recipe.source_url %}<p><a href="{{ recipe.source_url }}" target="_blank">Open original recipe source</a></p>{% endif %}
    <a class="button secondary" href="{{ url_for('home') }}">Start over</a>
  </div>
</main>
"""


@app.context_processor
def inject_helpers():
    return {"money": format_money}


@app.get("/")
def home():
    return render_template_string(
        HOME_TEMPLATE,
        diet_options=DIET_OPTIONS,
        intolerance_options=INTOLERANCE_OPTIONS,
        missing_env=check_env(),
    )


@app.post("/search")
def search():
    zip_code = request.form.get("zip_code", "").strip()
    craving = request.form.get("craving", "").strip()
    diet = request.form.get("diet") or None
    intolerances = request.form.getlist("intolerances") or None
    dislikes = split_csv(request.form.get("dislikes"))

    errors = []
    try:
        stores = find_stores(zip_code)
        if not stores:
            errors.append("No Kroger-family stores were found near that zip code.")
    except Exception as exc:
        stores = []
        errors.append(f"Could not find stores: {exc}")

    try:
        raw = recipe_search.search_recipes(
            query=craving,
            diet=diet,
            intolerances=intolerances,
            exclude_ingredients=dislikes,
            number=5,
        )
        recipes = sorted([recipe_search.parse_recipe(r) for r in raw], key=lambda r: r["price_per_serving"])
        if not recipes:
            errors.append("No recipes matched. Try loosening your filters.")
    except Exception as exc:
        recipes = []
        errors.append(f"Could not search recipes: {exc}")

    cache_id = uuid.uuid4().hex
    CACHE[cache_id] = {
        "zip_code": zip_code,
        "stores": stores,
        "recipes": recipes,
        "intolerances": intolerances,
        "dislikes": dislikes,
    }
    return render_template_string(SEARCH_TEMPLATE, cache_id=cache_id, stores=stores, recipes=recipes, errors=errors)


@app.post("/price")
def price():
    cache_id = request.form.get("cache_id", "")
    data = CACHE.get(cache_id)
    if not data:
        return redirect(url_for("home"))

    try:
        recipe = data["recipes"][int(request.form.get("recipe_i", "0"))]
        store = data["stores"][int(request.form.get("store_i", "0"))]
    except (IndexError, ValueError):
        return redirect(url_for("home"))

    prefer_organic = request.form.get("prefer_organic") == "yes"
    avoid_processed = request.form.get("avoid_processed") == "yes"
    ingredients, errors = build_ingredient_options(
        recipe=recipe,
        location_id=store["location_id"],
        prefer_organic=prefer_organic,
        avoid_processed=avoid_processed,
        intolerances=data.get("intolerances"),
        dislikes=data.get("dislikes"),
    )
    data.update({"recipe": recipe, "store": store, "ingredient_options": ingredients})
    return render_template_string(
        PRICE_TEMPLATE,
        cache_id=cache_id,
        recipe=recipe,
        store=store,
        ingredients=ingredients,
        errors=errors,
    )


@app.post("/summary")
def summary():
    cache_id = request.form.get("cache_id", "")
    data = CACHE.get(cache_id)
    if not data:
        return redirect(url_for("home"))

    recipe = data["recipe"]
    store = data["store"]
    ingredient_options = data.get("ingredient_options", [])

    selected = []
    total = 0.0
    ingredient_by_name = {i["name"]: i for i in recipe.get("ingredients", [])}
    leftovers = []
    limiting_batches = None

    for ing in ingredient_options:
        choice_id = request.form.get(f"choice_{ing['index']}")

        if choice_id == "IGNORE":
            selected.append({"ingredient": ing["name"], "status": "ignored", "product": None})
            continue

        if choice_id == "FREE":
            selected.append({"ingredient": ing["name"], "status": "free", "product": None})
            continue

        options = ing.get("options", [])
        if choice_id == "AUTO":
            product = next((o for o in options if "recommended" in o.get("tags", [])), None)
            if product is None:
                product = next((o for o in options if "cheapest" in o.get("tags", [])), None)
            if product is None and options:
                product = options[0]
            status = "auto"
        else:
            product = next((o for o in options if str(o.get("id")) == str(choice_id)), None)
            status = "chosen"

        if not product:
            selected.append({"ingredient": ing["name"], "status": "ignored", "product": None})
            continue

        total += float(product.get("price") or 0)
        selected.append({"ingredient": ing["name"], "product": product, "status": status})

        recipe_info = ingredient_by_name.get(ing["name"])
        if not recipe_info or product.get("price") == 0.0:
            continue
        pkg_amount, pkg_unit = product.get("package_amount"), product.get("package_unit")
        if pkg_amount is None or pkg_unit is None:
            leftovers.append({"name": ing["name"], "message": "package size was not available, so leftover math could not run."})
            continue
        batches, leftover, ok = servings.batches_from_one_ingredient(
            recipe_info.get("amount"), recipe_info.get("unit"), ing["name"], pkg_amount, pkg_unit
        )
        if not ok:
            leftovers.append({"name": ing["name"], "message": "unit conversion is not confidently available."})
            continue
        leftovers.append({
            "name": ing["name"],
            "message": f"enough for {batches} batch(es), about {leftover:.1f} {pkg_unit if pkg_unit in servings.COUNT_UNITS else 'g'} left over.",
        })
        if limiting_batches is None or batches < limiting_batches:
            limiting_batches = batches

    limiting_servings = None
    if limiting_batches is not None:
        limiting_servings = limiting_batches * (recipe.get("servings") or 1)

    return render_template_string(
        SUMMARY_TEMPLATE,
        recipe=recipe,
        store=store,
        selected=selected,
        total=round(total, 2),
        leftovers=leftovers,
        limiting_batches=limiting_batches,
        limiting_servings=limiting_servings,
    )


if __name__ == "__main__":
    app.run(debug=True)
