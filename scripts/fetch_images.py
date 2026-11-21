"""Télécharge une photo par recette depuis Wikimedia Commons dans static/img/recipes/<slug>.jpg.

Usage : python3 scripts/fetch_images.py [--force] [slug ...]
Écrit data/seed/_images.json (crédits) ; les images déjà présentes sont conservées.
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from validate_seed import load_all  # noqa: E402

OUT_DIR = os.path.join(ROOT, "static", "img", "recipes")
CREDITS = os.path.join(ROOT, "data", "seed", "_images.json")
API = "https://commons.wikimedia.org/w/api.php"
UA = "daily-food-seed/1.0 (recettes perso; contact: local)"
STOP = {"plat", "recette", "avec", "sauce", "aux", "des", "les", "une", "the", "and", "food", "dish"}


def fold(s):
    return unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()


def http(url, binary=False, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
                return data if binary else json.loads(data)
        except urllib.error.HTTPError as e:  # 429 : on respecte Retry-After
            last = e
            wait = int(e.headers.get("Retry-After", 0) or 0) if e.code == 429 else 0
            time.sleep(max(wait, 15 * (i + 1)) if e.code == 429 else 2 * (i + 1))
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def search(query):
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": 8, "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata", "iiurlwidth": 640,
    }
    data = http(f"{API}?{urllib.parse.urlencode(params)}")
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    return pages


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def pick(pages, words):
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        if info.get("width", 0) < 400 or info.get("width", 0) < info.get("height", 0) * 0.7:
            continue  # trop petit ou trop vertical
        title = fold(p["title"])
        if words and not any(w in title for w in words):
            continue
        return p, info
    return None, None


def fetch(recipe, force):
    slug = recipe["slug"]
    dest = os.path.join(OUT_DIR, f"{slug}.jpg")
    if os.path.exists(dest) and not force:
        return slug, "exists", None
    time.sleep(1.5)  # politesse envers l'API
    short = " ".join(re.sub(r"\(.*?\)", "", recipe["name"]).replace(":", " ").split()[:3])
    queries = list(dict.fromkeys([recipe["image_query"], recipe["name"], short, fold(short), f'{short} {recipe.get("origin") or ""}'.strip()]))
    for q in queries:
        words = [w for w in re.findall(r"[a-z0-9]+", fold(q)) if len(w) > 3 and w not in STOP]
        try:
            page, info = pick(search(q), words)
        except Exception as e:
            return slug, f"erreur {e}", None
        if page:
            thumb = info.get("thumburl") or info["url"]
            try:
                blob = http(thumb, binary=True)
            except Exception as e:
                return slug, f"erreur téléchargement {e}", None
            with open(dest, "wb") as f:
                f.write(blob)
            meta = info.get("extmetadata", {})
            artist = strip_html(meta.get("Artist", {}).get("value")) or "auteur inconnu"
            lic = meta.get("LicenseShortName", {}).get("value", "licence libre")
            return slug, "ok", {
                "credit": f"{artist[:80]} — {lic} — Wikimedia Commons",
                "source": info.get("descriptionurl"),
                "file": page["title"],
            }
    return slug, "introuvable", None


def main():
    force = "--force" in sys.argv
    only = {a for a in sys.argv[1:] if not a.startswith("--")}
    os.makedirs(OUT_DIR, exist_ok=True)
    credits = json.load(open(CREDITS, encoding="utf-8")) if os.path.exists(CREDITS) else {}
    recipes = [r for r in load_all() if not only or r["slug"] in only]
    missing = []
    with ThreadPoolExecutor(max_workers=1) as ex:
        for slug, status, meta in ex.map(lambda r: fetch(r, force), recipes):
            if meta:
                credits[slug] = meta
            if status not in ("ok", "exists"):
                missing.append((slug, status))
            print(f"{status:12} {slug}", flush=True)
    with open(CREDITS, "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"\n{len(recipes) - len(missing)}/{len(recipes)} images ; manquantes : {missing}")


if __name__ == "__main__":
    main()
