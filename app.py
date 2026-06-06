import os
import random
from datetime import datetime, timedelta, date
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
import uvicorn

from database import get_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)

env = Environment(
    loader=FileSystemLoader("templates"),
    auto_reload=False,
    cache_size=0,
)
templates = Jinja2Templates(env=env)
app.mount("/static", StaticFiles(directory="static"), name="static")

CATEGORY_LABELS = {
    "breakfast": "Petit-déjeuner",
    "lunch": "Déjeuner",
    "dinner": "Dîner",
    "snack": "Goûter",
    "dessert": "Dessert",
}

SLOT_LABELS = {
    "breakfast": "Petit-déj",
    "lunch": "Déjeuner",
    "dinner": "Dîner",
    "snack": "Goûter",
}

SLOT_COLORS = {
    "breakfast": "#B7950B",
    "lunch": "#5B8C4A",
    "dinner": "#2D6BB4",
    "snack": "#7B3FA0",
}

COMMON_TAGS = [
    "rapide", "végétarien", "vegan", "sans gluten",
    "pas cher", "batch cooking", "été", "hiver",
    "one pot", "au four", "mijoté", "salade",
    "soupe", "barbecue", "pâtes", "riz",
    "léger", "gourmand", "enfant", "meal prep",
]

WEEKDAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def get_user(request: Request):
    username = request.cookies.get("username")
    if username:
        conn = get_db()
        conn.execute("INSERT OR IGNORE INTO users (username) VALUES (?)", (username,))
        conn.commit()
        conn.close()
    return username


def get_week_dates(dt: date) -> list[date]:
    monday = dt - timedelta(days=dt.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def enrich_meals(conn, meals_list):
    result = []
    for m in meals_list:
        d = dict(m)
        tags = conn.execute(
            "SELECT tag FROM meal_tags WHERE meal_id = ?", (d["id"],)
        ).fetchall()
        d["tags"] = [t["tag"] for t in tags]
        ingredients = conn.execute(
            "SELECT ingredient FROM meal_ingredients WHERE meal_id = ?", (d["id"],)
        ).fetchall()
        d["ingredients"] = [i["ingredient"] for i in ingredients]
        result.append(d)
    return result


def get_common_tags(conn, limit=12):
    rows = conn.execute(
        "SELECT tag, COUNT(*) as cnt FROM meal_tags GROUP BY tag ORDER BY cnt DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [r["tag"] for r in rows]


# ---------- AUTH ----------


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/login")
def login_post(request: Request, username: str = Form(...)):
    username = username.strip()
    if not username:
        return RedirectResponse(url="/login", status_code=303)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="username", value=username, max_age=365 * 24 * 3600)
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("username")
    return response


# ---------- DASHBOARD ----------


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    category: str = None,
    max_time: int = None,
):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    today_str = date.today().isoformat()
    today_obj = date.today()

    # Build query with filters
    query = "SELECT * FROM meals"
    params = []
    conditions = []

    if category:
        conditions.append("category = ?")
        params.append(category)
    if max_time:
        conditions.append("(prep_time IS NULL OR prep_time <= ?)")
        params.append(max_time)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY RANDOM() LIMIT 1"
    cursor = conn.execute(query, params)
    meal = cursor.fetchone()

    suggestion = None
    if meal:
        suggestion = dict(meal)
        tags = conn.execute(
            "SELECT tag FROM meal_tags WHERE meal_id = ?", (suggestion["id"],)
        ).fetchall()
        suggestion["tags"] = [t["tag"] for t in tags]
        ingredients = conn.execute(
            "SELECT ingredient FROM meal_ingredients WHERE meal_id = ?",
            (suggestion["id"],),
        ).fetchall()
        suggestion["ingredients"] = [i["ingredient"] for i in ingredients]

    # Stats
    total_meals = conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0]
    planned_today = conn.execute(
        "SELECT COUNT(*) FROM plans WHERE plan_date = ?", (today_str,)
    ).fetchone()[0]
    week_dates = get_week_dates(today_obj)
    week_planned = conn.execute(
        "SELECT COUNT(*) FROM plans WHERE plan_date BETWEEN ? AND ?",
        (week_dates[0].isoformat(), week_dates[-1].isoformat()),
    ).fetchone()[0]
    total_history = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]

    conn.close()

    return templates.TemplateResponse(request, "dashboard.html",
        {
            "user": user,
            "suggestion": suggestion,
            "total_meals": total_meals,
            "planned_today": planned_today,
            "week_planned": week_planned,
            "total_history": total_history,
            "today": today_str,
            "filter_category": category,
            "filter_max_time": str(max_time) if max_time else None,
            "CATEGORY_LABELS": CATEGORY_LABELS,
        },
    )


# ---------- MEALS CRUD ----------


@app.get("/meals", response_class=HTMLResponse)
def meals_list(
    request: Request,
    q: str = None,
    category: str = None,
    tag: str = None,
):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()

    query = """
        SELECT DISTINCT m.* FROM meals m
    """
    params = []
    conditions = []
    join_clauses = []

    if tag:
        join_clauses.append(
            "JOIN meal_tags mt_filter ON mt_filter.meal_id = m.id"
        )
        conditions.append("mt_filter.tag = ?")
        params.append(tag)

    if q:
        conditions.append("(m.name LIKE ? OR m.notes LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    if category:
        conditions.append("m.category = ?")
        params.append(category)

    query += " ".join(join_clauses)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY m.created_at DESC"

    meals = conn.execute(query, params).fetchall()
    meals = enrich_meals(conn, meals)
    common_tags = get_common_tags(conn)

    total = conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0]

    conn.close()

    return templates.TemplateResponse(request, "meals.html",
        {
            "user": user,
            "meals": meals,
            "total": total,
            "query": q,
            "active_category": category,
            "active_tag": tag,
            "common_tags": common_tags,
            "CATEGORY_LABELS": CATEGORY_LABELS,
        },
    )


@app.get("/meals/add", response_class=HTMLResponse)
def meal_add_form(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(request, "meal_form.html",
        {
            "user": user,
            "meal": None,
            "CATEGORY_LABELS": CATEGORY_LABELS,
            "COMMON_TAGS": COMMON_TAGS,
        },
    )


@app.post("/meals/add")
def meal_add(
    request: Request,
    name: str = Form(...),
    category: str = Form(...),
    prep_time: int = Form(None),
    notes: str = Form(""),
    tags: str = Form(""),
    ingredients: list[str] = Form([]),
):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO meals (name, category, prep_time, notes, created_by) VALUES (?, ?, ?, ?, ?)",
        (name.strip(), category, prep_time or None, notes.strip(), user),
    )
    meal_id = cursor.lastrowid

    for tag in tags.split(","):
        tag = tag.strip().lower()
        if tag:
            conn.execute(
                "INSERT INTO meal_tags (meal_id, tag) VALUES (?, ?)",
                (meal_id, tag),
            )

    for ingredient in ingredients:
        ingredient = ingredient.strip()
        if ingredient:
            conn.execute(
                "INSERT INTO meal_ingredients (meal_id, ingredient) VALUES (?, ?)",
                (meal_id, ingredient),
            )

    conn.commit()
    conn.close()

    return RedirectResponse(url="/meals", status_code=303)


@app.get("/meals/{meal_id}/edit", response_class=HTMLResponse)
def meal_edit_form(request: Request, meal_id: int):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    meal = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        conn.close()
        raise HTTPException(status_code=404, detail="Plat non trouvé")

    meal = dict(meal)
    tags = conn.execute(
        "SELECT tag FROM meal_tags WHERE meal_id = ?", (meal_id,)
    ).fetchall()
    meal["tags"] = [t["tag"] for t in tags]
    ingredients = conn.execute(
        "SELECT ingredient FROM meal_ingredients WHERE meal_id = ?", (meal_id,)
    ).fetchall()
    meal["ingredients"] = [i["ingredient"] for i in ingredients]
    conn.close()

    return templates.TemplateResponse(request, "meal_form.html",
        {
            "user": user,
            "meal": meal,
            "CATEGORY_LABELS": CATEGORY_LABELS,
            "COMMON_TAGS": COMMON_TAGS,
        },
    )


@app.post("/meals/{meal_id}/edit")
def meal_edit(
    request: Request,
    meal_id: int,
    name: str = Form(...),
    category: str = Form(...),
    prep_time: int = Form(None),
    notes: str = Form(""),
    tags: str = Form(""),
    ingredients: list[str] = Form([]),
):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    meal = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        conn.close()
        raise HTTPException(status_code=404, detail="Plat non trouvé")

    conn.execute(
        "UPDATE meals SET name=?, category=?, prep_time=?, notes=? WHERE id=?",
        (name.strip(), category, prep_time or None, notes.strip(), meal_id),
    )

    conn.execute("DELETE FROM meal_tags WHERE meal_id = ?", (meal_id,))
    for tag in tags.split(","):
        tag = tag.strip().lower()
        if tag:
            conn.execute(
                "INSERT INTO meal_tags (meal_id, tag) VALUES (?, ?)",
                (meal_id, tag),
            )

    conn.execute("DELETE FROM meal_ingredients WHERE meal_id = ?", (meal_id,))
    for ingredient in ingredients:
        ingredient = ingredient.strip()
        if ingredient:
            conn.execute(
                "INSERT INTO meal_ingredients (meal_id, ingredient) VALUES (?, ?)",
                (meal_id, ingredient),
            )

    conn.commit()
    conn.close()

    return RedirectResponse(url="/meals", status_code=303)


@app.post("/meals/{meal_id}/delete")
def meal_delete(request: Request, meal_id: int):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
    conn.commit()
    conn.close()

    return RedirectResponse(url="/meals", status_code=303)


# ---------- PLANNER ----------


@app.get("/planner", response_class=HTMLResponse)
def planner(request: Request, week: str = None):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    today_obj = date.today()

    if week:
        try:
            ref_date = date.fromisoformat(week)
        except ValueError:
            ref_date = today_obj
    else:
        ref_date = today_obj

    ref_date = ref_date - timedelta(days=ref_date.weekday())
    week_dates = get_week_dates(ref_date)
    week_start = week_dates[0]
    week_end = week_dates[-1]

    conn = get_db()

    # Get plans for the week
    plans_rows = conn.execute(
        """
        SELECT p.*, m.name FROM plans p
        JOIN meals m ON m.id = p.meal_id
        WHERE p.plan_date BETWEEN ? AND ?
        ORDER BY p.plan_date, p.meal_slot
        """,
        (week_start.isoformat(), week_end.isoformat()),
    ).fetchall()

    plans_by_date = {}
    for p in plans_rows:
        d = p["plan_date"]
        slot = p["meal_slot"]
        if d not in plans_by_date:
            plans_by_date[d] = {}
        plans_by_date[d][slot] = {"id": p["id"], "name": p["name"]}

    # Build week days data
    week_days = []
    for d in week_dates:
        ds = d.isoformat()
        day_plans = plans_by_date.get(ds, {})
        week_days.append(
            {
                "date": d,
                "day_name": WEEKDAYS_FR[d.weekday()],
                "plans": day_plans,
            }
        )

    # All meals for the modal
    all_meals_rows = conn.execute(
        "SELECT * FROM meals ORDER BY name"
    ).fetchall()
    all_meals = enrich_meals(conn, all_meals_rows)

    conn.close()

    prev_week = (week_start - timedelta(days=7)).isoformat()
    next_week = (week_start + timedelta(days=7)).isoformat()

    return templates.TemplateResponse(request, "planner.html",
        {
            "user": user,
            "week_days": week_days,
            "week_start": week_start,
            "week_end": week_end,
            "prev_week": prev_week,
            "next_week": next_week,
            "today": today_obj,
            "all_meals": all_meals,
            "CATEGORY_LABELS": CATEGORY_LABELS,
            "SLOT_LABELS": SLOT_LABELS,
            "SLOT_COLORS": SLOT_COLORS,
        },
    )


@app.post("/planner/assign")
def planner_assign(
    request: Request,
    meal_id: int = Form(...),
    plan_date: str = Form(...),
    meal_slot: str = Form(...),
):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    # Check if slot already has a plan
    existing = conn.execute(
        "SELECT id FROM plans WHERE plan_date = ? AND meal_slot = ?",
        (plan_date, meal_slot),
    ).fetchone()
    if existing:
        conn.execute("DELETE FROM plans WHERE id = ?", (existing["id"],))

    conn.execute(
        "INSERT INTO plans (meal_id, plan_date, meal_slot, created_by) VALUES (?, ?, ?, ?)",
        (meal_id, plan_date, meal_slot, user),
    )
    conn.commit()
    conn.close()

    referer = request.headers.get("referer", "/planner")
    return RedirectResponse(url=referer, status_code=303)


@app.post("/planner/remove")
def planner_remove(
    request: Request,
    plan_id: int = Form(...),
):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
    conn.commit()
    conn.close()

    referer = request.headers.get("referer", "/planner")
    return RedirectResponse(url=referer, status_code=303)


# ---------- HISTORY ----------


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    rows = conn.execute(
        """
        SELECT h.*, m.name FROM history h
        JOIN meals m ON m.id = h.meal_id
        ORDER BY h.eaten_date DESC, h.meal_slot
        LIMIT 100
        """
    ).fetchall()

    groups = []
    current_date = None
    current_group = None

    for r in rows:
        d = r["eaten_date"]
        dt = datetime.strptime(d, "%Y-%m-%d")
        label = dt.strftime("%A %d %B %Y").capitalize()

        if d != current_date:
            current_group = {"date_label": label, "entries": []}
            groups.append(current_group)
            current_date = d

        current_group["entries"].append(
            {
                "meal_id": r["meal_id"],
                "name": r["name"],
                "meal_slot": r["meal_slot"],
                "eaten_by": r["eaten_by"],
                "rating": r["rating"],
            }
        )

    conn.close()

    return templates.TemplateResponse(request, "history.html",
        {
            "user": user,
            "history_groups": groups,
            "SLOT_LABELS": SLOT_LABELS,
            "SLOT_COLORS": SLOT_COLORS,
        },
    )


# ---------- SHOPPING LIST ----------


@app.get("/shopping", response_class=HTMLResponse)
def shopping_list(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    today_obj = date.today()
    week_dates = get_week_dates(today_obj)
    week_start = week_dates[0]
    week_end = week_dates[-1]

    conn = get_db()

    # Get all planned meals for this week with their ingredients
    rows = conn.execute(
        """
        SELECT mi.ingredient, m.name as meal_name
        FROM plans p
        JOIN meals m ON m.id = p.meal_id
        JOIN meal_ingredients mi ON mi.meal_id = m.id
        WHERE p.plan_date BETWEEN ? AND ?
        ORDER BY mi.ingredient
        """,
        (week_start.isoformat(), week_end.isoformat()),
    ).fetchall()

    # Deduplicate and aggregate sources
    ingredient_map = {}
    for r in rows:
        ing = r["ingredient"]
        if ing not in ingredient_map:
            ingredient_map[ing] = {"ingredient": ing, "sources": []}
        if r["meal_name"] not in ingredient_map[ing]["sources"]:
            ingredient_map[ing]["sources"].append(r["meal_name"])

    ingredients = sorted(ingredient_map.values(), key=lambda x: x["ingredient"])

    conn.close()

    return templates.TemplateResponse(request, "shopping.html",
        {
            "user": user,
            "ingredients": ingredients,
            "week_start": week_start,
            "week_end": week_end,
        },
    )


# ---------- MAIN ----------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
