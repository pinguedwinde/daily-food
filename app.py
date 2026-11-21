import csv
import io
import json
import os
import random
import shutil
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import get_db, init_db, load_seed_files
from recipes import (
    ACCESS_LABELS,
    CATEGORIES,
    DIFFICULTY_LABELS,
    REGION_EMOJI,
    REGION_LABELS,
    REGION_ORDER,
    aisle_for,
    delete_meal,
    find_duplicate_groups,
    get_meal,
    merge_meals,
    query_meals,
    save_meal,
    slugify,
    weighted_pick,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}

CATEGORY_LABELS = {
    "breakfast": "Petit-déjeuner",
    "lunch": "Déjeuner",
    "dinner": "Dîner",
    "snack": "Goûter",
    "dessert": "Dessert",
}
SLOT_LABELS = {"breakfast": "Petit-déj", "lunch": "Déjeuner", "dinner": "Dîner", "snack": "Goûter"}
SLOT_COLORS = {"breakfast": "#B7950B", "lunch": "#5B8C4A", "dinner": "#2D6BB4", "snack": "#7B3FA0"}
COMMON_TAGS = [
    "rapide", "végétarien", "vegan", "sans gluten", "pas cher", "batch cooking", "one pot", "au four",
    "mijoté", "épicé", "léger", "gourmand", "enfant", "traditionnel", "soupe", "salade", "festif",
]
WEEKDAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def fr_date(d, with_year=True):
    s = f"{d.day} {MONTHS_FR[d.month - 1]}"
    return f"{s} {d.year}" if with_year else s


def asset_version() -> str:
    """Change à chaque modification du CSS/JS : évite qu'un navigateur serve une ancienne version."""
    try:
        return str(int(max(os.path.getmtime(os.path.join(BASE_DIR, "static", f)) for f in ("style.css", "script.js"))))
    except OSError:
        return "0"


def is_admin(request: Request) -> bool:
    return request.cookies.get("admin") == "1"


def render(request, name, user, **ctx):
    ctx.update(
        user=user,
        ADMIN=is_admin(request),
        ASSET_V=asset_version(),
        CATEGORY_LABELS=CATEGORY_LABELS,
        SLOT_LABELS=SLOT_LABELS,
        SLOT_COLORS=SLOT_COLORS,
        REGION_LABELS=REGION_LABELS,
        REGION_EMOJI=REGION_EMOJI,
        REGION_ORDER=REGION_ORDER,
        DIFFICULTY_LABELS=DIFFICULTY_LABELS,
        ACCESS_LABELS=ACCESS_LABELS,
        fr_date=fr_date,
        WEEKDAYS=WEEKDAYS_FR,
    )
    return templates.TemplateResponse(request, name, ctx)


def get_user(request: Request):
    username = request.cookies.get("username")
    if username:
        conn = get_db()
        conn.execute("INSERT OR IGNORE INTO users (username) VALUES (?)", (username,))
        conn.commit()
        conn.close()
    return username


def login_redirect():
    return RedirectResponse(url="/login", status_code=303)


def back(request: Request, default: str):
    """Retourne à la page d'origine, uniquement si elle est sur ce site."""
    ref = request.headers.get("referer")
    if ref:
        p = urlparse(ref)
        if p.netloc == request.headers.get("host"):
            return RedirectResponse(url=p.path + (f"?{p.query}" if p.query else ""), status_code=303)
    return RedirectResponse(url=default, status_code=303)


def get_week_dates(dt: date) -> list[date]:
    monday = dt - timedelta(days=dt.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def parse_week(week: str | None) -> date:
    try:
        ref = date.fromisoformat(week) if week else date.today()
    except ValueError:
        ref = date.today()
    return ref - timedelta(days=ref.weekday())


def handle_image_upload(image_file: UploadFile | None) -> str | None:
    if not image_file or not image_file.filename:
        return None
    ext = os.path.splitext(image_file.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=400, detail="Format d'image non supporté")
    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}{ext}"
    with open(os.path.join(UPLOAD_DIR, filename), "wb") as f:
        shutil.copyfileobj(image_file.file, f)
    return f"/static/uploads/{filename}"


def filters_from(params, keys=("region", "category", "tag", "q", "max_difficulty", "max_access", "no_equipment", "batch", "max_time")):
    out = {}
    for k in keys:
        v = params.get(k)
        if v not in (None, "", "0"):
            out[k] = v
    return out


def common_tags(conn, limit=14):
    rows = conn.execute("SELECT tag, COUNT(*) c FROM meal_tags GROUP BY tag ORDER BY c DESC, tag LIMIT ?", (limit,)).fetchall()
    return [r["tag"] for r in rows]


def recent_meal_ids(conn, days=14):
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("SELECT DISTINCT meal_id FROM history WHERE eaten_date >= ?", (since,)).fetchall()
    return {r["meal_id"] for r in rows}


def default_slot():
    h = datetime.now().hour
    return "breakfast" if h < 10 else "lunch" if h < 15 else "dinner"


# ---------- AUTH ----------


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"ASSET_V": asset_version()})


@app.post("/login")
def login_post(username: str = Form(...)):
    username = username.strip()
    if not username:
        return login_redirect()
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="username", value=username, max_age=365 * 24 * 3600)
    return response


@app.get("/logout")
def logout():
    response = login_redirect()
    response.delete_cookie("username")
    return response


# ---------- DASHBOARD : « On mange quoi ? » ----------


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user = get_user(request)
    if not user:
        return login_redirect()

    qp = request.query_params
    filters = filters_from(qp, ("region", "category", "max_difficulty", "max_access", "no_equipment", "max_time"))
    seen = [int(x) for x in qp.get("seen", "").split(",") if x.isdigit()]

    conn = get_db()
    candidates = query_meals(conn, filters)
    recent = recent_meal_ids(conn)

    # Jamais deux fois le même plat de suite tant qu'il en reste d'autres : on exclut les plats déjà proposés.
    fresh = [m for m in candidates if m["id"] not in seen]
    exhausted = bool(candidates) and not fresh
    if exhausted:
        seen, fresh = [], candidates
    picked = weighted_pick(fresh, 1, recent)
    suggestion = picked[0] if picked else None
    seen_next = seen + ([suggestion["id"]] if suggestion else [])

    today = date.today()
    week_dates = get_week_dates(today)
    stats = {
        "total_meals": conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0],
        "planned_today": conn.execute("SELECT COUNT(*) FROM plans WHERE plan_date = ?", (today.isoformat(),)).fetchone()[0],
        "week_planned": conn.execute(
            "SELECT COUNT(*) FROM plans WHERE plan_date BETWEEN ? AND ?", (week_dates[0].isoformat(), week_dates[-1].isoformat())
        ).fetchone()[0],
        "total_history": conn.execute("SELECT COUNT(*) FROM history").fetchone()[0],
    }
    todays = conn.execute(
        "SELECT p.id, p.meal_slot, p.done, m.id AS meal_id, m.name, m.image_url, m.region FROM plans p "
        "JOIN meals m ON m.id = p.meal_id WHERE p.plan_date = ? ORDER BY CASE p.meal_slot "
        "WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1 WHEN 'snack' THEN 2 ELSE 3 END",
        (today.isoformat(),),
    ).fetchall()
    conn.close()

    return render(
        request, "dashboard.html", user,
        suggestion=suggestion,
        candidates_count=len(candidates),
        recently_eaten=bool(suggestion and suggestion["id"] in recent),
        exhausted=exhausted,
        seen=",".join(map(str, seen_next)),
        filters=filters,
        stats=stats,
        todays=[dict(t) for t in todays],
        today=today.isoformat(),
        today_date=today,
        default_slot=default_slot(),
        PAGE="home",
    )


# ---------- MEALS ----------


@app.get("/meals", response_class=HTMLResponse)
def meals_list(request: Request):
    user = get_user(request)
    if not user:
        return login_redirect()

    qp = request.query_params
    filters = filters_from(qp)
    sort = qp.get("sort", "region")
    conn = get_db()
    meals = query_meals(conn, filters, order=sort)
    total = conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0]
    tags = common_tags(conn)
    region_counts = {r["region"]: r["c"] for r in conn.execute("SELECT region, COUNT(*) c FROM meals GROUP BY region")}
    conn.close()

    return render(
        request, "meals.html", user,
        meals=meals, total=total, filters=filters, sort=sort, common_tags=tags, region_counts=region_counts, PAGE="meals",
    )


def meal_form_context(meal=None):
    return {"meal": meal, "COMMON_TAGS": COMMON_TAGS, "PAGE": "meals"}


@app.get("/meals/add", response_class=HTMLResponse)
def meal_add_form(request: Request):
    user = get_user(request)
    if not user:
        return login_redirect()
    return render(request, "meal_form.html", user, **meal_form_context())


def form_to_dict(form, image_url, image_file):
    data = dict(form)
    data["image_url"] = (data.get("image_url") or "").strip() or handle_image_upload(image_file)
    return data


@app.post("/meals/add")
async def meal_add(request: Request, image_file: UploadFile = File(None)):
    user = get_user(request)
    if not user:
        return login_redirect()
    form = await request.form()
    data = {k: form.get(k) for k in (
        "name", "category", "region", "origin", "prep_time", "cook_time", "difficulty", "ingredient_access",
        "servings", "keeps_days", "notes", "tags", "equipment", "image_url",
    )}
    data["batch_friendly"] = form.get("batch_friendly")
    data["ingredients"] = form.getlist("ingredients")
    data["steps"] = form.getlist("steps")
    data["image_url"] = (data["image_url"] or "").strip() or handle_image_upload(form.get("image_file"))
    conn = get_db()
    try:
        meal_id = save_meal(conn, data, user=user)
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=400, detail=str(e))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/meals/{meal_id}", status_code=303)


@app.get("/meals/{meal_id}", response_class=HTMLResponse)
def meal_detail(request: Request, meal_id: int):
    user = get_user(request)
    if not user:
        return login_redirect()
    conn = get_db()
    meal = get_meal(conn, meal_id)
    if not meal:
        conn.close()
        raise HTTPException(status_code=404, detail="Plat non trouvé")
    stats = conn.execute(
        "SELECT COUNT(*) c, AVG(rating) r, MAX(eaten_date) last FROM history WHERE meal_id = ?", (meal_id,)
    ).fetchone()
    similar = query_meals(conn, {"region": meal["region"]})
    similar = [m for m in similar if m["id"] != meal_id]
    random.shuffle(similar)
    conn.close()
    return render(
        request, "meal_detail.html", user,
        meal=meal, eaten=stats, similar=similar[:3], today=date.today().isoformat(), PAGE="meals",
    )


@app.get("/meals/{meal_id}/edit", response_class=HTMLResponse)
def meal_edit_form(request: Request, meal_id: int):
    user = get_user(request)
    if not user:
        return login_redirect()
    conn = get_db()
    meal = get_meal(conn, meal_id)
    conn.close()
    if not meal:
        raise HTTPException(status_code=404, detail="Plat non trouvé")
    return render(request, "meal_form.html", user, **meal_form_context(meal))


@app.post("/meals/{meal_id}/edit")
async def meal_edit(request: Request, meal_id: int):
    user = get_user(request)
    if not user:
        return login_redirect()
    conn = get_db()
    current = conn.execute("SELECT slug, image_credit FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not current:
        conn.close()
        raise HTTPException(status_code=404, detail="Plat non trouvé")
    form = await request.form()
    data = {k: form.get(k) for k in (
        "name", "category", "region", "origin", "prep_time", "cook_time", "difficulty", "ingredient_access",
        "servings", "keeps_days", "notes", "tags", "equipment", "image_url",
    )}
    data["batch_friendly"] = form.get("batch_friendly")
    data["ingredients"] = form.getlist("ingredients")
    data["steps"] = form.getlist("steps")
    data["image_url"] = (data["image_url"] or "").strip() or handle_image_upload(form.get("image_file"))
    data["slug"] = current["slug"]
    data["image_credit"] = current["image_credit"]
    try:
        save_meal(conn, data, meal_id=meal_id)
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=400, detail=str(e))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/meals/{meal_id}", status_code=303)


@app.post("/meals/{meal_id}/delete")
def meal_delete(request: Request, meal_id: int):
    user = get_user(request)
    if not user:
        return login_redirect()
    conn = get_db()
    delete_meal(conn, meal_id)
    conn.commit()
    conn.close()
    return RedirectResponse(url="/meals", status_code=303)


# ---------- PLANNER ----------


@app.get("/planner", response_class=HTMLResponse)
def planner(request: Request, week: str = None):
    user = get_user(request)
    if not user:
        return login_redirect()

    today = date.today()
    week_dates = get_week_dates(parse_week(week))
    week_start, week_end = week_dates[0], week_dates[-1]

    conn = get_db()
    rows = conn.execute(
        "SELECT p.id, p.plan_date, p.meal_slot, p.done, m.id AS meal_id, m.name, m.image_url, m.region, m.difficulty, "
        "m.batch_friendly FROM plans p JOIN meals m ON m.id = p.meal_id WHERE p.plan_date BETWEEN ? AND ?",
        (week_start.isoformat(), week_end.isoformat()),
    ).fetchall()
    plans = {}
    for r in rows:
        plans.setdefault(r["plan_date"], {})[r["meal_slot"]] = dict(r)

    week_days = [
        {"date": d, "iso": d.isoformat(), "day_name": WEEKDAYS_FR[d.weekday()], "plans": plans.get(d.isoformat(), {})}
        for d in week_dates
    ]
    all_meals = query_meals(conn, {})
    conn.close()

    return render(
        request, "planner.html", user,
        week_days=week_days, week_start=week_start, week_end=week_end,
        prev_week=(week_start - timedelta(days=7)).isoformat(),
        next_week=(week_start + timedelta(days=7)).isoformat(),
        today=today.isoformat(), is_current_week=week_start == get_week_dates(today)[0],
        all_meals=all_meals, PAGE="planner",
    )


def _assign(conn, meal_id, plan_date, meal_slot, user):
    conn.execute("DELETE FROM plans WHERE plan_date = ? AND meal_slot = ?", (plan_date, meal_slot))
    conn.execute(
        "INSERT INTO plans (meal_id, plan_date, meal_slot, created_by) VALUES (?, ?, ?, ?)",
        (meal_id, plan_date, meal_slot, user),
    )


@app.post("/planner/assign")
def planner_assign(
    request: Request, meal_id: int = Form(...), plan_date: str = Form(...), meal_slot: str = Form(...)
):
    user = get_user(request)
    if not user:
        return login_redirect()
    try:
        date.fromisoformat(plan_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Date invalide")
    if meal_slot not in SLOT_LABELS:
        raise HTTPException(status_code=400, detail="Créneau invalide")
    conn = get_db()
    if not conn.execute("SELECT 1 FROM meals WHERE id = ?", (meal_id,)).fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Plat non trouvé")
    _assign(conn, meal_id, plan_date, meal_slot, user)
    conn.commit()
    conn.close()
    return back(request, "/planner")


@app.post("/planner/remove")
def planner_remove(request: Request, plan_id: int = Form(...)):
    user = get_user(request)
    if not user:
        return login_redirect()
    conn = get_db()
    conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
    conn.commit()
    conn.close()
    return back(request, "/planner")


@app.post("/planner/done")
def planner_done(request: Request, plan_id: int = Form(...)):
    """Marque un repas planifié comme mangé : il entre dans l'historique."""
    user = get_user(request)
    if not user:
        return login_redirect()
    conn = get_db()
    plan = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if plan and not plan["done"]:
        conn.execute(
            "INSERT INTO history (meal_id, eaten_date, meal_slot, eaten_by) VALUES (?, ?, ?, ?)",
            (plan["meal_id"], plan["plan_date"], plan["meal_slot"], user),
        )
        conn.execute("UPDATE plans SET done = 1 WHERE id = ?", (plan_id,))
        conn.commit()
    conn.close()
    return back(request, "/planner")


@app.post("/planner/generate")
def planner_generate(
    request: Request,
    week: str = Form(None),
    mode: str = Form("varied"),
    slots: list[str] = Form(["dinner"]),
    easy: str = Form(None),
    overwrite: str = Form(None),
    region: str = Form(""),
):
    """Remplit la semaine : `varied` = un plat différent par créneau, `batch` = 3-4 plats batch répétés."""
    user = get_user(request)
    if not user:
        return login_redirect()
    week_start = parse_week(week)
    days = get_week_dates(week_start)
    slots = [s for s in slots if s in SLOT_LABELS] or ["dinner"]

    conn = get_db()
    filters = {"category": None}
    if easy:
        filters["max_difficulty"] = 1 if easy == "1" else int(easy)
    if region in REGION_LABELS:
        filters["region"] = region
    if mode == "batch":
        filters["batch"] = 1
    main = [m for m in query_meals(conn, filters) if m["category"] in ("lunch", "dinner")]
    if not main:
        conn.close()
        return RedirectResponse(url=f"/planner?week={week_start.isoformat()}&msg=nomatch", status_code=303)

    recent = recent_meal_ids(conn)
    if overwrite:
        conn.execute(
            "DELETE FROM plans WHERE plan_date BETWEEN ? AND ? AND meal_slot IN (%s)" % ",".join("?" * len(slots)),
            [days[0].isoformat(), days[-1].isoformat(), *slots],
        )
    taken = {(r["plan_date"], r["meal_slot"]) for r in conn.execute(
        "SELECT plan_date, meal_slot FROM plans WHERE plan_date BETWEEN ? AND ?", (days[0].isoformat(), days[-1].isoformat())
    )}
    today_iso = date.today().isoformat()  # on ne planifie pas dans le passé
    targets = [(d.isoformat(), s) for d in days for s in slots if (d.isoformat(), s) not in taken and d.isoformat() >= today_iso]
    if not targets:
        conn.close()
        return RedirectResponse(url=f"/planner?week={week_start.isoformat()}&msg=full", status_code=303)

    if mode == "batch":
        chosen = weighted_pick(main, min(4, len(main)), recent)
        sequence = [chosen[i % len(chosen)] for i in range(len(targets))]
    else:
        chosen = weighted_pick(main, len(targets), recent)
        # complète en recyclant si la base filtrée est plus petite que la semaine
        sequence = chosen + [random.choice(main) for _ in range(len(targets) - len(chosen))]
        # évite deux jours de suite la même région quand c'est possible
        for i in range(1, len(sequence)):
            if sequence[i]["region"] == sequence[i - 1]["region"]:
                for j in range(i + 1, len(sequence)):
                    if sequence[j]["region"] != sequence[i - 1]["region"]:
                        sequence[i], sequence[j] = sequence[j], sequence[i]
                        break

    for (plan_date, slot), meal in zip(targets, sequence):
        _assign(conn, meal["id"], plan_date, slot, user)
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/planner?week={week_start.isoformat()}&msg=generated", status_code=303)


@app.post("/planner/clear")
def planner_clear(request: Request, week: str = Form(...)):
    user = get_user(request)
    if not user:
        return login_redirect()
    days = get_week_dates(parse_week(week))
    conn = get_db()
    conn.execute(
        "DELETE FROM plans WHERE plan_date BETWEEN ? AND ? AND done = 0", (days[0].isoformat(), days[-1].isoformat())
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/planner?week={days[0].isoformat()}", status_code=303)


# ---------- HISTORY ----------


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request):
    user = get_user(request)
    if not user:
        return login_redirect()

    conn = get_db()
    rows = conn.execute(
        "SELECT h.*, m.name, m.image_url, m.region FROM history h JOIN meals m ON m.id = h.meal_id "
        "ORDER BY h.eaten_date DESC, h.id DESC LIMIT 200"
    ).fetchall()
    top = conn.execute(
        "SELECT m.id, m.name, COUNT(*) c, AVG(h.rating) r FROM history h JOIN meals m ON m.id = h.meal_id "
        "GROUP BY m.id ORDER BY c DESC, r DESC LIMIT 5"
    ).fetchall()
    conn.close()

    groups, current = [], None
    for r in rows:
        if current is None or current["iso"] != r["eaten_date"]:
            d = date.fromisoformat(r["eaten_date"])
            current = {"iso": r["eaten_date"], "date_label": f"{WEEKDAYS_FR[d.weekday()]} {fr_date(d)}", "entries": []}
            groups.append(current)
        current["entries"].append(dict(r))

    return render(request, "history.html", user, history_groups=groups, top=[dict(t) for t in top], PAGE="history")


@app.post("/history/add")
def history_add(
    request: Request,
    meal_id: int = Form(...),
    eaten_date: str = Form(None),
    meal_slot: str = Form("dinner"),
    rating: int = Form(None),
):
    """« Je mange ça » : planifie le plat pour la date/créneau choisis et l'inscrit dans l'historique."""
    user = get_user(request)
    if not user:
        return login_redirect()
    eaten_date = eaten_date or date.today().isoformat()
    try:
        date.fromisoformat(eaten_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Date invalide")
    if meal_slot not in SLOT_LABELS:
        raise HTTPException(status_code=400, detail="Créneau invalide")
    conn = get_db()
    if not conn.execute("SELECT 1 FROM meals WHERE id = ?", (meal_id,)).fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Plat non trouvé")
    _assign(conn, meal_id, eaten_date, meal_slot, user)
    plan_id = conn.execute(
        "SELECT id FROM plans WHERE plan_date = ? AND meal_slot = ?", (eaten_date, meal_slot)
    ).fetchone()["id"]
    conn.execute("UPDATE plans SET done = 1 WHERE id = ?", (plan_id,))
    conn.execute(
        "INSERT INTO history (meal_id, eaten_date, meal_slot, eaten_by, rating) VALUES (?, ?, ?, ?, ?)",
        (meal_id, eaten_date, meal_slot, user, rating),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/history", status_code=303)


@app.post("/history/{entry_id}/rate")
def history_rate(request: Request, entry_id: int, rating: int = Form(...)):
    user = get_user(request)
    if not user:
        return login_redirect()
    conn = get_db()
    conn.execute("UPDATE history SET rating = ? WHERE id = ?", (max(1, min(5, rating)), entry_id))
    conn.commit()
    conn.close()
    return back(request, "/history")


@app.post("/history/{entry_id}/delete")
def history_delete(request: Request, entry_id: int):
    user = get_user(request)
    if not user:
        return login_redirect()
    conn = get_db()
    conn.execute("DELETE FROM history WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return back(request, "/history")


# ---------- SHOPPING LIST ----------


def build_shopping(conn, plan_filter_sql, params):
    rows = conn.execute(
        f"SELECT mi.ingredient, m.name AS meal_name FROM plans p JOIN meals m ON m.id = p.meal_id "
        f"JOIN meal_ingredients mi ON mi.meal_id = m.id WHERE {plan_filter_sql} ORDER BY mi.ingredient COLLATE NOCASE",
        params,
    ).fetchall()
    items = {}
    for r in rows:
        key = r["ingredient"].strip().lower()
        item = items.setdefault(key, {"ingredient": r["ingredient"].strip(), "sources": []})
        if r["meal_name"] not in item["sources"]:
            item["sources"].append(r["meal_name"])
    aisles = {}
    for item in sorted(items.values(), key=lambda x: x["ingredient"].lower()):
        aisles.setdefault(aisle_for(item["ingredient"]), []).append(item)
    return aisles


@app.get("/shopping", response_class=HTMLResponse)
def shopping_list(request: Request, week: str = None):
    user = get_user(request)
    if not user:
        return login_redirect()

    week_start = parse_week(week)
    week_end = week_start + timedelta(days=6)
    conn = get_db()
    aisles = build_shopping(conn, "p.plan_date BETWEEN ? AND ?", (week_start.isoformat(), week_end.isoformat()))
    meals_count = conn.execute(
        "SELECT COUNT(DISTINCT meal_id) FROM plans WHERE plan_date BETWEEN ? AND ?",
        (week_start.isoformat(), week_end.isoformat()),
    ).fetchone()[0]
    conn.close()

    order = ["🥬 Fruits & légumes", "🥩 Viandes & poissons", "🥛 Crèmerie & œufs", "🌾 Épicerie", "🌶️ Épices & condiments", "🧺 Autres"]
    aisles = {k: aisles[k] for k in order if k in aisles}
    return render(
        request, "shopping.html", user,
        aisles=aisles, total_items=sum(len(v) for v in aisles.values()), meals_count=meals_count,
        week_start=week_start, week_end=week_end, week_key=week_start.isoformat(),
        prev_week=(week_start - timedelta(days=7)).isoformat(), next_week=(week_start + timedelta(days=7)).isoformat(),
        PAGE="shopping",
    )


# ---------- BATCH COOKING ----------


@app.get("/batch", response_class=HTMLResponse)
def batch_page(request: Request):
    user = get_user(request)
    if not user:
        return login_redirect()
    qp = request.query_params
    filters = filters_from(qp, ("region", "max_difficulty", "max_access", "no_equipment"))
    filters["batch"] = 1
    conn = get_db()
    meals = [m for m in query_meals(conn, filters, order="easy") if m["category"] in ("lunch", "dinner")]
    conn.close()
    return render(request, "batch.html", user, meals=meals, filters=filters, PAGE="batch")


@app.get("/batch/session", response_class=HTMLResponse)
def batch_session(request: Request):
    user = get_user(request)
    if not user:
        return login_redirect()
    ids = [int(x) for x in request.query_params.get("ids", "").split(",") if x.isdigit()][:8]
    if not ids:
        return RedirectResponse(url="/batch", status_code=303)
    conn = get_db()
    meals = [m for m in (get_meal(conn, i) for i in ids) if m]
    conn.close()

    merged = {}
    for m in meals:
        for ing in m["ingredients"]:
            item = merged.setdefault(ing.strip().lower(), {"ingredient": ing.strip(), "sources": []})
            item["sources"].append(m["name"])
    aisles = {}
    for item in sorted(merged.values(), key=lambda x: x["ingredient"].lower()):
        aisles.setdefault(aisle_for(item["ingredient"]), []).append(item)
    equipment = sorted({e for m in meals for e in m["equipment"]})
    # Les plats longs (mijotés) démarrent en premier pour que tout soit prêt en même temps.
    ordered = sorted(meals, key=lambda m: -(m.get("cook_time") or 0))
    return render(
        request, "batch_session.html", user,
        meals=ordered, aisles=aisles, equipment=equipment, ids=",".join(map(str, ids)),
        active_time=sum(m.get("prep_time") or 0 for m in meals),
        portions=sum(m.get("servings") or 4 for m in meals),
        longest=max((m.get("cook_time") or 0 for m in meals), default=0),
        start_default=get_week_dates(date.today())[0].isoformat(), PAGE="batch",
    )


@app.post("/batch/plan")
def batch_plan(
    request: Request,
    ids: str = Form(...),
    start: str = Form(...),
    days: int = Form(7),
    slot: str = Form("dinner"),
):
    """Répartit les plats préparés en batch sur plusieurs jours."""
    user = get_user(request)
    if not user:
        return login_redirect()
    meal_ids = [int(x) for x in ids.split(",") if x.isdigit()]
    try:
        start_date = date.fromisoformat(start)
    except ValueError:
        raise HTTPException(status_code=400, detail="Date invalide")
    if not meal_ids or slot not in SLOT_LABELS:
        raise HTTPException(status_code=400, detail="Paramètres invalides")
    conn = get_db()
    valid = {r["id"] for r in conn.execute("SELECT id FROM meals")}
    meal_ids = [i for i in meal_ids if i in valid]
    for n in range(max(1, min(days, 14))):
        d = (start_date + timedelta(days=n)).isoformat()
        _assign(conn, meal_ids[n % len(meal_ids)], d, slot, user)
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/planner?week={start_date.isoformat()}&msg=generated", status_code=303)


# ---------- EXPORT / IMPORT ----------


def export_records(conn, region=None):
    meals = query_meals(conn, {"region": region} if region else {})
    credits = {}
    out = []
    for m in meals:
        out.append({
            "slug": m["slug"] or slugify(m["name"]),
            "name": m["name"], "region": m["region"], "origin": m["origin"], "category": m["category"],
            "prep_time": m["prep_time"], "cook_time": m["cook_time"], "difficulty": m["difficulty"],
            "ingredient_access": m["ingredient_access"], "equipment": m["equipment"], "servings": m["servings"],
            "batch_friendly": m["batch_friendly"], "keeps_days": m["keeps_days"], "tags": m["tags"],
            "ingredients": m["ingredients"], "steps": m["steps"], "notes": m["notes"], "image_url": m["image_url"],
        })
    return out


@app.get("/export", response_class=HTMLResponse)
def export_page(request: Request):
    user = get_user(request)
    if not user:
        return login_redirect()
    conn = get_db()
    counts = {r["region"]: r["c"] for r in conn.execute("SELECT region, COUNT(*) c FROM meals GROUP BY region")}
    deleted = conn.execute("SELECT COUNT(*) FROM deleted_seeds").fetchone()[0]
    conn.close()
    return render(
        request, "export.html", user,
        counts=counts, total=sum(counts.values()), deleted=deleted,
        msg=request.query_params.get("msg"), n=request.query_params.get("n"), skipped=request.query_params.get("skipped"),
        PAGE="export",
    )


@app.get("/export/download")
def export_download(request: Request, format: str = "json", region: str = None):
    user = get_user(request)
    if not user:
        return login_redirect()
    conn = get_db()
    data = export_records(conn, region if region in REGION_LABELS else None)
    conn.close()
    stem = f"daily-food-{region or 'tout'}"

    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["nom", "région", "origine", "type", "préparation (min)", "cuisson (min)", "difficulté", "accès ingrédients",
                    "matériel", "portions", "batch", "conservation (j)", "tags", "ingrédients", "étapes", "notes"])
        for m in data:
            w.writerow([
                m["name"], REGION_LABELS[m["region"]], m["origin"] or "", CATEGORY_LABELS[m["category"]], m["prep_time"] or "",
                m["cook_time"] or "", DIFFICULTY_LABELS[m["difficulty"]], ACCESS_LABELS[m["ingredient_access"]],
                ", ".join(m["equipment"]), m["servings"] or "", "oui" if m["batch_friendly"] else "non", m["keeps_days"] or "",
                ", ".join(m["tags"]), " | ".join(m["ingredients"]), " | ".join(f"{i + 1}. {s}" for i, s in enumerate(m["steps"])),
                m["notes"] or "",
            ])
        return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename={stem}.csv"})
    if format == "jsonl":
        body = "\n".join(json.dumps(m, ensure_ascii=False) for m in data)
        return Response(body, media_type="application/x-ndjson; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename={stem}.jsonl"})
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={stem}.json"})


@app.get("/export/book", response_class=HTMLResponse)
def export_book(request: Request, region: str = None, batch: str = None):
    """Livre de recettes imprimable (Ctrl+P → PDF)."""
    user = get_user(request)
    if not user:
        return login_redirect()
    conn = get_db()
    filters = {}
    if region in REGION_LABELS:
        filters["region"] = region
    if batch:
        filters["batch"] = 1
    meals = query_meals(conn, filters)
    conn.close()
    return render(request, "book.html", user, meals=meals, region=region, PAGE="export")


def parse_import(raw: str):
    raw = raw.strip().lstrip("﻿")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = [json.loads(line) for line in raw.splitlines() if line.strip()]  # JSON Lines
    if isinstance(data, dict):
        data = data.get("meals") or data.get("recipes") or [data]
    if not isinstance(data, list):
        raise ValueError("Format inattendu")
    return data


@app.post("/import")
async def import_data(request: Request):
    user = get_user(request)
    if not user:
        return login_redirect()
    form = await request.form()
    raw = form.get("data") or ""
    upload = form.get("file")
    if upload is not None and getattr(upload, "filename", ""):
        raw = (await upload.read()).decode("utf-8", errors="replace")
    try:
        meals = parse_import(raw)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="JSON invalide")

    update = form.get("update") == "on"
    conn = get_db()
    added = skipped = 0
    for meal in meals:
        if not isinstance(meal, dict) or not str(meal.get("name", "")).strip():
            skipped += 1
            continue
        slug = meal.get("slug") or slugify(meal["name"])
        existing = conn.execute(
            "SELECT id, slug FROM meals WHERE slug = ? OR lower(name) = lower(?)", (slug, meal["name"].strip())
        ).fetchone()
        if existing and not update:
            skipped += 1
            continue
        meal["slug"] = existing["slug"] if existing else slug
        if not existing and conn.execute("SELECT 1 FROM meals WHERE slug = ?", (slug,)).fetchone():
            meal["slug"] = None
        save_meal(conn, meal, user=user, meal_id=existing["id"] if existing else None)
        if not existing:
            conn.execute("DELETE FROM deleted_seeds WHERE slug = ?", (meal["slug"],))
        added += 1
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/export?msg=imported&n={added}&skipped={skipped}", status_code=303)


@app.post("/export/restore-seed")
def restore_seed(request: Request):
    """Réinsère les recettes d'origine supprimées."""
    user = get_user(request)
    if not user:
        return login_redirect()
    from database import seed_recipes

    conn = get_db()
    before = conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0]
    conn.execute("DELETE FROM deleted_seeds")
    seed_recipes(conn)
    after = conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0]
    conn.close()
    return RedirectResponse(url=f"/export?msg=restored&n={after - before}", status_code=303)



# ---------- MODE ADMIN ----------

UA = "daily-food/1.0 (usage personnel)"
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/avif": ".avif"}


def admin_only(request: Request):
    user = get_user(request)
    if not user:
        return None, login_redirect()
    if not is_admin(request):
        return user, RedirectResponse(url="/", status_code=303)
    return user, None


@app.post("/admin/toggle")
def admin_toggle(request: Request):
    user = get_user(request)
    if not user:
        return login_redirect()
    on = not is_admin(request)
    response = RedirectResponse(url="/admin" if on else "/", status_code=303)
    if on:
        response.set_cookie("admin", "1", max_age=365 * 24 * 3600)
    else:
        response.delete_cookie("admin")
    return response


def photo_status(url):
    if not url:
        return "none"
    if url.startswith("/static/uploads/"):
        return "custom"
    if url.startswith("/static/img/"):
        return "seed"
    return "remote"


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    if get_user(request) and not is_admin(request):
        return render(request, "admin_enable.html", request.cookies.get("username"), PAGE="admin")
    user, redirect = admin_only(request)
    if redirect:
        return redirect
    qp = request.query_params
    filters = filters_from(qp, ("region", "category", "q"))
    photo = qp.get("photo", "")
    conn = get_db()
    meals = query_meals(conn, filters, order=qp.get("sort", "region") if qp.get("sort") in ("region", "name", "recent") else "region")
    for m in meals:
        m["photo_status"] = photo_status(m["image_url"])
    dup_ids = {m["id"] for g in find_duplicate_groups(conn, BASE_DIR) for m in g["meals"]}
    for m in meals:
        m["is_dup"] = m["id"] in dup_ids
    if photo in ("none", "custom", "seed", "remote"):
        meals = [m for m in meals if m["photo_status"] == photo]
    elif photo == "dup":
        meals = [m for m in meals if m["is_dup"]]
    counts = {
        "total": conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0],
        "nophoto": conn.execute("SELECT COUNT(*) FROM meals WHERE image_url IS NULL OR image_url = ''").fetchone()[0],
        "dups": len(dup_ids),
    }
    conn.close()
    return render(request, "admin.html", user, meals=meals, filters=filters, photo=photo, counts=counts, PAGE="admin")


@app.post("/admin/bulk")
async def admin_bulk(request: Request):
    user, redirect = admin_only(request)
    if redirect:
        return redirect
    form = await request.form()
    ids = [int(i) for i in form.getlist("ids") if str(i).isdigit()]
    action = form.get("action")
    value = form.get("region_value", "") if action == "region" else form.get("category_value", "")
    conn = get_db()
    if ids:
        marks = ",".join("?" * len(ids))
        if action == "delete":
            for i in ids:
                delete_meal(conn, i)
        elif action == "region" and value in REGION_LABELS:
            conn.execute(f"UPDATE meals SET region = ? WHERE id IN ({marks})", [value, *ids])
        elif action == "category" and value in CATEGORIES:
            conn.execute(f"UPDATE meals SET category = ? WHERE id IN ({marks})", [value, *ids])
        elif action == "clear_photo":
            conn.execute(f"UPDATE meals SET image_url = NULL, image_credit = NULL WHERE id IN ({marks})", ids)
        elif action == "merge" and len(ids) > 1:
            merge_meals(conn, ids[0], ids[1:])
    conn.commit()
    conn.close()
    return back(request, "/admin")


@app.post("/admin/meals/{meal_id}/field")
async def admin_field(request: Request, meal_id: int):
    """Édition rapide d'un champ depuis le tableau (appelée en fetch)."""
    user, redirect = admin_only(request)
    if redirect:
        raise HTTPException(status_code=403)
    form = await request.form()
    field, value = form.get("field"), (form.get("value") or "").strip()
    allowed = {
        "name": lambda v: v or None,
        "region": lambda v: v if v in REGION_LABELS else None,
        "category": lambda v: v if v in CATEGORIES else None,
        "difficulty": lambda v: int(v) if v in ("1", "2", "3") else None,
    }
    if field not in allowed or allowed[field](value) is None:
        raise HTTPException(status_code=400, detail="Valeur invalide")
    conn = get_db()
    conn.execute(f"UPDATE meals SET {field} = ? WHERE id = ?", (allowed[field](value), meal_id))
    conn.commit()
    conn.close()
    return {"ok": True}


def download_image(url: str) -> str:
    """Télécharge une image distante dans static/uploads et renvoie son chemin local."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="URL invalide")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ctype = r.headers.get_content_type()
            if ctype not in IMAGE_TYPES:
                raise HTTPException(status_code=400, detail="Ce lien n'est pas une image")
            data = r.read(8 * 1024 * 1024 + 1)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Téléchargement impossible")
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image trop lourde (8 Mo max)")
    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}{IMAGE_TYPES[ctype]}"
    with open(os.path.join(UPLOAD_DIR, filename), "wb") as f:
        f.write(data)
    return f"/static/uploads/{filename}"


@app.post("/admin/meals/{meal_id}/image")
async def admin_image(request: Request, meal_id: int):
    user, redirect = admin_only(request)
    if redirect:
        raise HTTPException(status_code=403)
    form = await request.form()
    credit = None
    if form.get("clear"):
        image = None
    elif form.get("file") is not None and getattr(form.get("file"), "filename", ""):
        image = handle_image_upload(form.get("file"))
    elif (form.get("url") or "").strip():
        url = form["url"].strip()
        # les images de Commons sont copiées en local pour ne pas dépendre du site distant
        image = download_image(url) if form.get("download") else url
        credit = form.get("credit") or None
    else:
        raise HTTPException(status_code=400, detail="Aucune image fournie")
    conn = get_db()
    if not conn.execute("SELECT 1 FROM meals WHERE id = ?", (meal_id,)).fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Plat non trouvé")
    conn.execute("UPDATE meals SET image_url = ?, image_credit = ? WHERE id = ?", (image, credit, meal_id))
    conn.commit()
    conn.close()
    return {"ok": True, "image_url": image}


@app.get("/admin/image-search")
def admin_image_search(request: Request, q: str):
    """Cherche des photos libres sur Wikimedia Commons pour remplacer l'image d'un plat."""
    user, redirect = admin_only(request)
    if redirect:
        raise HTTPException(status_code=403)
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"{q} filetype:bitmap", "gsrlimit": 18, "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata", "iiurlwidth": 800,
    }
    req = urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except Exception:
        raise HTTPException(status_code=502, detail="Recherche indisponible pour le moment (réessaie dans une minute)")
    import re as _re
    results = []
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        meta = info.get("extmetadata", {})
        artist = _re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "") or "").strip() or "auteur inconnu"
        licence = meta.get("LicenseShortName", {}).get("value", "licence libre")
        results.append({
            "thumb": info.get("thumburl") or info.get("url"),
            "full": info.get("thumburl") or info.get("url"),
            "title": p["title"].replace("File:", ""),
            "credit": f"{artist[:80]} — {licence} — Wikimedia Commons",
        })
    return results


@app.get("/admin/duplicates", response_class=HTMLResponse)
def admin_duplicates(request: Request):
    user, redirect = admin_only(request)
    if redirect:
        return redirect
    conn = get_db()
    groups = find_duplicate_groups(conn, BASE_DIR)
    conn.close()
    return render(request, "admin_duplicates.html", user, groups=groups, PAGE="admin")


@app.post("/admin/duplicates/merge")
async def admin_merge(request: Request):
    user, redirect = admin_only(request)
    if redirect:
        return redirect
    form = await request.form()
    keep = int(form.get("keep", 0))
    remove = [int(i) for i in form.getlist("remove") if str(i).isdigit()]
    conn = get_db()
    if keep and remove:
        merge_meals(conn, keep, remove)
        conn.commit()
    conn.close()
    return RedirectResponse(url="/admin/duplicates", status_code=303)


@app.post("/admin/duplicates/ignore")
async def admin_ignore(request: Request):
    user, redirect = admin_only(request)
    if redirect:
        return redirect
    form = await request.form()
    ids = sorted(int(i) for i in form.getlist("ids") if str(i).isdigit())
    conn = get_db()
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            conn.execute("INSERT OR IGNORE INTO dup_ignored (a_id, b_id) VALUES (?, ?)", (a, b))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin/duplicates", status_code=303)


# ---------- MAIN ----------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8421))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run("app:app", host=host, port=port, reload=os.environ.get("RELOAD") == "1")
