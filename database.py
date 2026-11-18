import glob
import json
import os
import sqlite3
import unicodedata

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DAILY_FOOD_DB") or os.path.join(BASE_DIR, "daily_food.db")
SEED_DIR = os.path.join(BASE_DIR, "data", "seed")
RECIPE_IMG_DIR = os.path.join(BASE_DIR, "static", "img", "recipes")


def fold_text(s):
    """Minuscule sans accents : « Poulet Crème » → « poulet creme » (recherche tolérante)."""
    return unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("fold", 1, fold_text, deterministic=True)
    return conn


# Colonnes ajoutées après la première version du schéma (migration idempotente).
MEAL_MIGRATIONS = {
    "slug": "TEXT",
    "region": "TEXT NOT NULL DEFAULT 'monde'",
    "origin": "TEXT",
    "cook_time": "INTEGER",
    "difficulty": "INTEGER NOT NULL DEFAULT 2",
    "ingredient_access": "INTEGER NOT NULL DEFAULT 1",
    "equipment": "TEXT NOT NULL DEFAULT '[]'",
    "servings": "INTEGER",
    "batch_friendly": "INTEGER NOT NULL DEFAULT 0",
    "keeps_days": "INTEGER",
    "steps": "TEXT NOT NULL DEFAULT '[]'",
    "image_credit": "TEXT",
}


def _migrate(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(meals)")}
    for name, ddl in MEAL_MIGRATIONS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE meals ADD COLUMN {name} {ddl}")
    plan_cols = {r["name"] for r in conn.execute("PRAGMA table_info(plans)")}
    if "done" not in plan_cols:
        conn.execute("ALTER TABLE plans ADD COLUMN done INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_meals_slug ON meals(slug) WHERE slug IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meal_tags_meal ON meal_tags(meal_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meal_ingredients_meal ON meal_ingredients(meal_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_date ON plans(plan_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_date ON history(eaten_date)")


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'dinner',
            prep_time INTEGER,
            notes TEXT,
            created_by TEXT,
            image_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS meal_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meal_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            FOREIGN KEY (meal_id) REFERENCES meals(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS meal_ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meal_id INTEGER NOT NULL,
            ingredient TEXT NOT NULL,
            FOREIGN KEY (meal_id) REFERENCES meals(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meal_id INTEGER NOT NULL,
            plan_date DATE NOT NULL,
            meal_slot TEXT NOT NULL DEFAULT 'dinner',
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (meal_id) REFERENCES meals(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meal_id INTEGER NOT NULL,
            eaten_date DATE NOT NULL,
            meal_slot TEXT NOT NULL DEFAULT 'dinner',
            eaten_by TEXT,
            rating INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (meal_id) REFERENCES meals(id) ON DELETE CASCADE
        );

        -- Recettes d'origine supprimées par l'utilisateur : elles ne reviennent pas au redémarrage.
        CREATE TABLE IF NOT EXISTS deleted_seeds (
            slug TEXT PRIMARY KEY
        );

        -- Paires déclarées « pas des doublons » dans le mode admin.
        CREATE TABLE IF NOT EXISTS dup_ignored (
            a_id INTEGER NOT NULL,
            b_id INTEGER NOT NULL,
            PRIMARY KEY (a_id, b_id)
        );
    """)
    _migrate(conn)
    conn.commit()
    seed_recipes(conn)
    conn.close()


def load_seed_files():
    """Lit data/seed/*.json (hors fichiers préfixés par _) et renvoie la liste des recettes."""
    recipes = []
    for path in sorted(glob.glob(os.path.join(SEED_DIR, "*.json"))):
        if os.path.basename(path).startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            recipes.extend(json.load(f))
    return recipes


def _load_image_credits():
    path = os.path.join(SEED_DIR, "_images.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def seed_recipes(conn):
    """Insère les recettes d'origine absentes. Idempotent, n'écrase jamais une recette déjà présente
    sous son slug ; les plats historiques (sans slug) sont rapprochés par leur nom et enrichis."""
    from recipes import save_meal  # import tardif : recipes dépend de ce module

    credits = _load_image_credits()
    deleted = {r["slug"] for r in conn.execute("SELECT slug FROM deleted_seeds")}
    by_slug = {r["slug"] for r in conn.execute("SELECT slug FROM meals WHERE slug IS NOT NULL")}
    legacy = {
        r["name"].strip().lower(): r["id"]
        for r in conn.execute("SELECT id, name FROM meals WHERE slug IS NULL")
    }

    for recipe in load_seed_files():
        slug = recipe["slug"]
        if slug in deleted or slug in by_slug:
            continue
        local = f"/static/img/recipes/{slug}.jpg"
        if os.path.exists(os.path.join(RECIPE_IMG_DIR, f"{slug}.jpg")):
            recipe["image_url"] = local
            recipe["image_credit"] = credits.get(slug, {}).get("credit")
        legacy_id = legacy.pop(recipe["name"].strip().lower(), None)
        if legacy_id:
            existing = conn.execute("SELECT image_url FROM meals WHERE id = ?", (legacy_id,)).fetchone()
            recipe.setdefault("image_url", existing["image_url"])
            save_meal(conn, recipe, meal_id=legacy_id)
        else:
            save_meal(conn, recipe, user="Recettes d'origine")
        by_slug.add(slug)
    conn.commit()
