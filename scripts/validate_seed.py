"""Valide les fichiers data/seed/*.json (hors fichiers préfixés par _)."""
import glob
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "seed")
REGIONS = {"africain", "antillais", "asiatique", "europeen", "monde"}
CATEGORIES = {"breakfast", "lunch", "dinner", "snack", "dessert"}
REQUIRED = [
    "slug", "name", "region", "origin", "category", "prep_time", "cook_time",
    "difficulty", "ingredient_access", "equipment", "servings", "batch_friendly",
    "keeps_days", "tags", "ingredients", "steps", "notes", "image_query",
]


def load_all():
    recipes = []
    for path in sorted(glob.glob(os.path.join(ROOT, "*.json"))):
        if os.path.basename(path).startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            for r in json.load(f):
                r["_file"] = os.path.basename(path)
                recipes.append(r)
    return recipes


def validate(recipes):
    errors = []
    slugs = Counter(r.get("slug") for r in recipes)
    for r in recipes:
        label = f'{r.get("_file")}:{r.get("slug") or r.get("name")}'
        for k in REQUIRED:
            if k not in r or r[k] in (None, ""):
                if k in ("equipment", "keeps_days", "batch_friendly") and k in r:
                    continue
                errors.append(f"{label}: champ manquant « {k} »")
        if slugs[r.get("slug")] > 1:
            errors.append(f"{label}: slug en double")
        if r.get("slug") and not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", r["slug"]):
            errors.append(f"{label}: slug invalide")
        if r.get("region") not in REGIONS:
            errors.append(f"{label}: region invalide {r.get('region')!r}")
        if r.get("category") not in CATEGORIES:
            errors.append(f"{label}: category invalide {r.get('category')!r}")
        if r.get("difficulty") not in (1, 2, 3):
            errors.append(f"{label}: difficulty doit être 1, 2 ou 3")
        if r.get("ingredient_access") not in (1, 2, 3):
            errors.append(f"{label}: ingredient_access doit être 1, 2 ou 3")
        for k in ("prep_time", "cook_time", "servings", "keeps_days"):
            if not isinstance(r.get(k), int) or r.get(k) < 0:
                errors.append(f"{label}: {k} doit être un entier >= 0")
        if not isinstance(r.get("batch_friendly"), bool):
            errors.append(f"{label}: batch_friendly doit être un booléen")
        for k in ("tags", "ingredients", "steps", "equipment"):
            if not isinstance(r.get(k), list) or not all(isinstance(x, str) and x.strip() for x in r.get(k, [])):
                errors.append(f"{label}: {k} doit être une liste de chaînes")
        if len(r.get("ingredients", [])) < 4:
            errors.append(f"{label}: moins de 4 ingrédients")
        if len(r.get("steps", [])) < 3:
            errors.append(f"{label}: moins de 3 étapes")
    return errors


if __name__ == "__main__":
    recipes = load_all()
    errors = validate(recipes)
    for e in errors:
        print("ERREUR", e)
    print(f"{len(recipes)} recettes — par région : {dict(Counter(r.get('region') for r in recipes))}")
    print(f"batch_friendly: {sum(1 for r in recipes if r.get('batch_friendly') is True)}")
    sys.exit(1 if errors else 0)
