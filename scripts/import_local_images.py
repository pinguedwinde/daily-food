"""Importe les photos déposées dans data/images/ : conversion JPEG, redimensionnement, compression,
copie vers static/img/recipes/<slug>.jpg et mise à jour de la base (recettes existantes).

Les nouvelles recettes se déclarent dans data/seed/ajouts_perso.json (puis relancer ce script).
Le rattachement fichier → recette se fait dans data/images/_mapping.json {"fichier": "slug"}.
"""
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageOps

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
SRC = os.path.join(ROOT, "data", "images")
DST = os.path.join(ROOT, "static", "img", "recipes")
CREDITS = os.path.join(ROOT, "data", "seed", "_images.json")
MAX_SIDE = 1200
QUALITY = 82


def to_jpeg(src, dst):
    path = src
    tmp = None
    try:
        Image.open(src).verify()
    except Exception:  # format non géré par Pillow (ex. AVIF) : conversion via sips (macOS)
        tmp = tempfile.mktemp(suffix=".jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", src, "--out", tmp], check=True, capture_output=True)
        path = tmp
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    im.save(dst, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    if tmp:
        os.remove(tmp)


def main():
    from database import get_db, init_db

    with open(os.path.join(SRC, "_mapping.json"), encoding="utf-8") as f:
        mapping = json.load(f)
    init_db()  # insère aussi les nouvelles recettes des seeds
    credits = json.load(open(CREDITS, encoding="utf-8"))
    conn = get_db()
    for fname, slug in sorted(mapping.items()):
        dst = os.path.join(DST, f"{slug}.jpg")
        before = os.path.getsize(dst) // 1024 if os.path.exists(dst) else 0
        to_jpeg(os.path.join(SRC, fname), dst)
        credits.pop(slug, None)
        cur = conn.execute(
            "UPDATE meals SET image_url = ?, image_credit = NULL WHERE slug = ?",
            (f"/static/img/recipes/{slug}.jpg", slug),
        )
        status = "OK" if cur.rowcount else "RECETTE INTROUVABLE"
        print(f"{status:20} {fname} → {slug}.jpg ({before} → {os.path.getsize(dst)//1024} Ko)")
    conn.commit()
    conn.close()
    with open(CREDITS, "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
