"""Couche données des plats : constantes, normalisation, sauvegarde, requêtes."""
import json
import random
import re

from database import fold_text

REGION_ORDER = ["africain", "antillais", "asiatique", "europeen", "monde"]
REGION_LABELS = {
    "africain": "Africain",
    "antillais": "Antillais",
    "asiatique": "Asiatique",
    "europeen": "Européen",
    "monde": "Autres",
}
REGION_EMOJI = {
    "africain": "🌍",
    "antillais": "🌴",
    "asiatique": "🥢",
    "europeen": "🥖",
    "monde": "🌎",
}
# Préférence de l'utilisateur : africain > antillais > asiatique > européen.
REGION_WEIGHTS = {"africain": 5, "antillais": 4, "asiatique": 3, "europeen": 2, "monde": 1}

DIFFICULTY_LABELS = {1: "Facile", 2: "Moyen", 3: "Ambitieux"}
ACCESS_LABELS = {
    1: "Ingrédients courants",
    2: "Épicerie spécialisée",
    3: "Ingrédients difficiles à trouver",
}
CATEGORIES = ["breakfast", "lunch", "dinner", "snack", "dessert"]

_STR_LISTS = ("tags", "ingredients", "steps", "equipment")


def _int(value, default=None, lo=None, hi=None):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def _clean_list(values, lower=False):
    if isinstance(values, str):
        values = values.split(",")
    out = []
    for v in values or []:
        v = str(v).strip()
        if lower:
            v = v.lower()
        if v and v not in out:
            out.append(v)
    return out


def slugify(text):
    text = text.lower()
    for a, b in (("àâä", "a"), ("éèêë", "e"), ("îï", "i"), ("ôö", "o"), ("ùûü", "u"), ("ç", "c"), ("œ", "oe")):
        for ch in a:
            text = text.replace(ch, b)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def normalize(data):
    """Valide / nettoie un dict de plat issu d'un formulaire, d'un import ou d'un seed."""
    region = data.get("region") if data.get("region") in REGION_LABELS else "monde"
    category = data.get("category") if data.get("category") in CATEGORIES else "dinner"
    out = {
        "name": str(data.get("name", "")).strip(),
        "slug": data.get("slug") or None,
        "region": region,
        "origin": (data.get("origin") or "").strip() or None,
        "category": category,
        "prep_time": _int(data.get("prep_time"), None, lo=0),
        "cook_time": _int(data.get("cook_time"), None, lo=0),
        "difficulty": _int(data.get("difficulty"), 2, lo=1, hi=3),
        "ingredient_access": _int(data.get("ingredient_access"), 1, lo=1, hi=3),
        "servings": _int(data.get("servings"), None, lo=1),
        "batch_friendly": 1 if str(data.get("batch_friendly", "")).lower() in ("1", "true", "on", "yes") else 0,
        "keeps_days": _int(data.get("keeps_days"), None, lo=0),
        "notes": (data.get("notes") or "").strip(),
        "image_url": (data.get("image_url") or "").strip() or None,
        "image_credit": data.get("image_credit") or None,
        "tags": _clean_list(data.get("tags"), lower=True),
        "ingredients": _clean_list(data.get("ingredients")),
        "steps": _clean_list(data.get("steps")),
        "equipment": _clean_list(data.get("equipment"), lower=True),
    }
    if data.get("batch_friendly") is True:
        out["batch_friendly"] = 1
    return out


def save_meal(conn, data, user=None, meal_id=None):
    """Insère (ou met à jour si meal_id) un plat avec ses tags et ingrédients. Renvoie l'id."""
    m = normalize(data)
    if not m["name"]:
        raise ValueError("Le nom du plat est obligatoire")
    cols = (
        "name", "slug", "region", "origin", "category", "prep_time", "cook_time", "difficulty",
        "ingredient_access", "servings", "batch_friendly", "keeps_days", "notes", "image_url", "image_credit",
    )
    values = [m[c] for c in cols] + [json.dumps(m["equipment"], ensure_ascii=False), json.dumps(m["steps"], ensure_ascii=False)]
    if meal_id is None:
        cursor = conn.execute(
            f"INSERT INTO meals ({', '.join(cols)}, equipment, steps, created_by) VALUES ({', '.join('?' * (len(cols) + 3))})",
            values + [user],
        )
        meal_id = cursor.lastrowid
    else:
        conn.execute(
            f"UPDATE meals SET {', '.join(c + '=?' for c in cols)}, equipment=?, steps=? WHERE id=?",
            values + [meal_id],
        )
        conn.execute("DELETE FROM meal_tags WHERE meal_id = ?", (meal_id,))
        conn.execute("DELETE FROM meal_ingredients WHERE meal_id = ?", (meal_id,))
    conn.executemany("INSERT INTO meal_tags (meal_id, tag) VALUES (?, ?)", [(meal_id, t) for t in m["tags"]])
    conn.executemany(
        "INSERT INTO meal_ingredients (meal_id, ingredient) VALUES (?, ?)", [(meal_id, i) for i in m["ingredients"]]
    )
    return meal_id


def attach_details(conn, rows):
    """Transforme des lignes `meals` en dicts complets (tags, ingrédients, listes JSON) sans N+1."""
    meals = [dict(r) for r in rows]
    if not meals:
        return meals
    by_id = {m["id"]: m for m in meals}
    for m in meals:
        m["tags"], m["ingredients"] = [], []
        m["steps"] = json.loads(m.get("steps") or "[]")
        m["equipment"] = json.loads(m.get("equipment") or "[]")
        m["batch_friendly"] = bool(m.get("batch_friendly"))
        m["total_time"] = (m.get("prep_time") or 0) + (m.get("cook_time") or 0) or None
    ids = list(by_id)
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(f"SELECT meal_id, tag FROM meal_tags WHERE meal_id IN ({marks}) ORDER BY id", chunk):
            by_id[r["meal_id"]]["tags"].append(r["tag"])
        for r in conn.execute(
            f"SELECT meal_id, ingredient FROM meal_ingredients WHERE meal_id IN ({marks}) ORDER BY id", chunk
        ):
            by_id[r["meal_id"]]["ingredients"].append(r["ingredient"])
    return meals


def build_filters(f):
    """f : dict de filtres → (clause WHERE, params) sur la table meals aliasée `m`."""
    cond, params = [], []
    if f.get("region") in REGION_LABELS:
        cond.append("m.region = ?")
        params.append(f["region"])
    if f.get("category") in CATEGORIES:
        cond.append("m.category = ?")
        params.append(f["category"])
    if f.get("tag"):
        cond.append("EXISTS (SELECT 1 FROM meal_tags t WHERE t.meal_id = m.id AND t.tag = ?)")
        params.append(f["tag"])
    if f.get("q"):
        # Chaque mot doit apparaître (sans tenir compte des accents ni de la casse) dans l'un des champs.
        for word in fold_text(f["q"]).split():
            like = f"%{word}%"
            cond.append(
                "(fold(m.name) LIKE ? OR fold(m.notes) LIKE ? OR fold(m.origin) LIKE ? "
                "OR EXISTS (SELECT 1 FROM meal_ingredients i WHERE i.meal_id = m.id AND fold(i.ingredient) LIKE ?) "
                "OR EXISTS (SELECT 1 FROM meal_tags t WHERE t.meal_id = m.id AND fold(t.tag) LIKE ?))"
            )
            params.extend([like] * 5)
    if f.get("max_difficulty"):
        cond.append("m.difficulty <= ?")
        params.append(int(f["max_difficulty"]))
    if f.get("max_access"):
        cond.append("m.ingredient_access <= ?")
        params.append(int(f["max_access"]))
    if f.get("no_equipment"):
        cond.append("m.equipment = '[]'")
    if f.get("batch"):
        cond.append("m.batch_friendly = 1")
    if f.get("max_time"):
        cond.append("(COALESCE(m.prep_time, 0) + COALESCE(m.cook_time, 0)) <= ?")
        params.append(int(f["max_time"]))
    return (" WHERE " + " AND ".join(cond)) if cond else "", params


REGION_ORDER_SQL = "CASE m.region " + " ".join(f"WHEN '{r}' THEN {i}" for i, r in enumerate(REGION_ORDER)) + " ELSE 9 END"


def query_meals(conn, filters, order="region"):
    where, params = build_filters(filters)
    orders = {
        "region": f"{REGION_ORDER_SQL}, m.name COLLATE NOCASE",
        "name": "m.name COLLATE NOCASE",
        "recent": "m.created_at DESC, m.id DESC",
        "quick": "(COALESCE(m.prep_time,0)+COALESCE(m.cook_time,0)), m.name COLLATE NOCASE",
        "easy": "m.difficulty, m.ingredient_access, m.name COLLATE NOCASE",
    }
    rows = conn.execute(f"SELECT m.* FROM meals m{where} ORDER BY {orders.get(order, orders['region'])}", params).fetchall()
    return attach_details(conn, rows)


def get_meal(conn, meal_id):
    row = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    return attach_details(conn, [row])[0] if row else None


def weighted_pick(candidates, k=1, recent_ids=()):
    """Tirage pondéré par préférence de région ; les plats récents pèsent 10× moins."""
    pool = list(candidates)
    picked = []
    while pool and len(picked) < k:
        weights = [
            REGION_WEIGHTS.get(m["region"], 1) * (0.1 if m["id"] in recent_ids else 1.0) for m in pool
        ]
        choice = random.choices(pool, weights=weights, k=1)[0]
        picked.append(choice)
        pool.remove(choice)
    return picked


# ---------- Liste de courses ----------

AISLES = [
    ("🥬 Fruits & légumes", ("oignon", "ail", "tomate", "carotte", "poireau", "courgette", "aubergine", "poivron", "piment", "gingembre", "citron", "citronnelle", "avocat", "banane", "plantain", "igname", "manioc", "patate", "pomme", "champignon", "épinard", "salade", "chou", "haricots verts", "persil", "coriandre", "menthe", "basilic", "ciboulette", "thym", "laurier", "gombo", "concombre", "navet", "céleri", "courge", "potimarron", "citron vert", "mangue", "ananas", "noix de coco fraîche", "christophine", "feuille", "oseille", "radis", "échalote", "fenouil", "herbe", "oignon vert")),
    ("🥩 Viandes & poissons", ("poulet", "boeuf", "bœuf", "mouton", "agneau", "porc", "veau", "canard", "saucisse", "lard", "poitrine", "jambon", "viande", "poisson", "saumon", "morue", "crevette", "thon", "tilapia", "carpe", "merlan", "cabillaud", "lardons", "chorizo", "boudin", "lambi", "crabe", "calamar", "dinde")),
    ("🥛 Crèmerie & œufs", ("lait", "crème", "beurre", "fromage", "œuf", "oeuf", "yaourt", "yogourt", "mozzarella", "parmesan", "gruyère", "emmental", "cheddar", "reblochon", "raclette", "burrata", "feta", "paneer", "morbier", "tomme")),
    ("🌾 Épicerie", ("riz", "pâtes", "spaghetti", "penne", "nouilles", "vermicelle", "farine", "semoule", "couscous", "lentille", "pois", "haricot", "quinoa", "polenta", "maïs", "attiéké", "tapioca", "sucre", "sel", "huile", "vinaigre", "sauce", "bouillon", "concentré", "conserve", "lait de coco", "arachide", "cacahuète", "pâte d'arachide", "miel", "chapelure", "pain", "galette", "tortilla", "levure", "fécule", "maïzena", "lasagne", "orzo", "crozet", "gnocchi", "noix", "amande", "tofu", "tamarin", "sésame", "olive", "câpre", "chocolat", "cacao", "flocons", "avoine", "muesli", "gari")),
    ("🌶️ Épices & condiments", ("poivre", "curry", "colombo", "paprika", "cumin", "curcuma", "cannelle", "muscade", "piment en poudre", "cube", "épice", "soumbala", "moutarde", "ketchup", "mayonnaise", "gingembre en poudre", "garam", "quatre-épices", "clou de girofle", "safran", "anis", "badiane", "cardamome", "cinq épices", "massalé", "herbes de provence", "origan", "sambal", "kimchi", "wasabi", "soja", "nuoc", "miso", "mirin", "sriracha", "harissa", "ras el hanout", "estragon")),
]


def aisle_for(ingredient):
    low = ingredient.lower()
    best, best_len = "🧺 Autres", 0
    for label, words in AISLES:
        for w in words:
            if w in low and len(w) > best_len:
                best, best_len = label, len(w)
    return best


# ---------- Doublons (mode admin) ----------

import difflib
import hashlib
import os
import unicodedata

_DUP_STOP = {"de", "du", "des", "aux", "au", "la", "le", "les", "et", "en", "a", "d", "l", "avec", "sauce", "simplifie", "maison", "facon"}
_ING_STOP = _DUP_STOP | {"g", "kg", "cl", "ml", "l", "cuillere", "cuilleres", "soupe", "cafe", "pincee", "gousse", "gousses", "sel", "poivre",
                         "huile", "eau", "oignon", "ail", "environ", "morceaux", "frais", "fraiche", "petit", "petite", "gros", "grosse"}


def _fold(s):
    s = unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _tokens(s, stop):
    return {w for w in _fold(s).split() if w not in stop and len(w) > 2 and not w.isdigit()}


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def _image_key(base_dir, url):
    if not url:
        return None
    if url.startswith("/static/"):
        path = os.path.join(base_dir, url.lstrip("/"))
        if os.path.exists(path):
            with open(path, "rb") as f:
                return "h:" + hashlib.md5(f.read()).hexdigest()
    return "u:" + url


def find_duplicate_groups(conn, base_dir):
    """Regroupe les plats probablement identiques. Renvoie [{'meals': [...], 'reasons': [...]}]."""
    meals = attach_details(conn, conn.execute("SELECT * FROM meals").fetchall())
    ignored = {tuple(sorted((r["a_id"], r["b_id"]))) for r in conn.execute("SELECT a_id, b_id FROM dup_ignored")}
    info = {}
    for m in meals:
        ing = set()
        for i in m["ingredients"]:
            ing |= _tokens(i, _ING_STOP)
        info[m["id"]] = {"name": _fold(m["name"]), "ntok": _tokens(m["name"], _DUP_STOP), "ing": ing, "img": _image_key(base_dir, m["image_url"])}

    parent = {m["id"]: m["id"] for m in meals}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    reasons = {}
    for i, a in enumerate(meals):
        for b in meals[i + 1:]:
            if tuple(sorted((a["id"], b["id"]))) in ignored:
                continue
            ia, ib = info[a["id"]], info[b["id"]]
            why = []
            if ia["img"] and ia["img"] == ib["img"]:
                why.append("même photo")
            ratio = difflib.SequenceMatcher(None, ia["name"], ib["name"]).ratio()
            if ratio >= 0.88 or (len(ia["ntok"]) > 1 and _jaccard(ia["ntok"], ib["ntok"]) >= 0.75):
                why.append("nom très proche")
            if a["region"] == b["region"] and _jaccard(ia["ing"], ib["ing"]) >= 0.6 and (ia["ntok"] & ib["ntok"] or ratio >= 0.6):
                why.append("ingrédients quasi identiques")
            if why:
                parent[find(a["id"])] = find(b["id"])
                reasons.setdefault(a["id"], set()).update(why)
                reasons.setdefault(b["id"], set()).update(why)

    groups = {}
    for m in meals:
        groups.setdefault(find(m["id"]), []).append(m)
    out = []
    for g in groups.values():
        if len(g) > 1:
            why = sorted({r for m in g for r in reasons.get(m["id"], ())})
            out.append({"meals": sorted(g, key=lambda m: (m["image_url"] is None, m["name"])), "reasons": why})
    return sorted(out, key=lambda x: x["meals"][0]["name"])


def delete_meal(conn, meal_id):
    """Supprime un plat ; une recette d'origine supprimée ne revient pas au redémarrage."""
    row = conn.execute("SELECT slug FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if row and row["slug"]:
        conn.execute("INSERT OR IGNORE INTO deleted_seeds (slug) VALUES (?)", (row["slug"],))
    conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))


def merge_meals(conn, keep_id, remove_ids):
    """Fusionne des doublons : planning et historique pointent vers le plat conservé."""
    keep = conn.execute("SELECT image_url FROM meals WHERE id = ?", (keep_id,)).fetchone()
    for rid in remove_ids:
        if rid == keep_id:
            continue
        other = conn.execute("SELECT image_url FROM meals WHERE id = ?", (rid,)).fetchone()
        if other and other["image_url"] and not keep["image_url"]:
            conn.execute("UPDATE meals SET image_url = ? WHERE id = ?", (other["image_url"], keep_id))
            keep = {"image_url": other["image_url"]}
        conn.execute("UPDATE plans SET meal_id = ? WHERE meal_id = ?", (keep_id, rid))
        conn.execute("UPDATE history SET meal_id = ? WHERE meal_id = ?", (keep_id, rid))
        delete_meal(conn, rid)
