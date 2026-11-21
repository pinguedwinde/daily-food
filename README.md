# On mange quoi aujourd'hui ?

Application web multi-utilisateur pour en finir avec la question existentielle, planifier la semaine et préparer un batch cooking le week-end.
Elle démarre avec **139 recettes illustrées** (africaines, antillaises, asiatiques, européennes — dans cet ordre de préférence), chacune avec ingrédients, étapes, difficulté, matériel et facilité à trouver les ingrédients.

## Démarrage rapide

```bash
make run          # puis http://localhost:8421  (make run PORT=8090 pour changer de port)
make dev          # idem avec rechargement automatique
make help         # liste des commandes
```

Au premier lancement, la base `daily_food.db` est créée et remplie depuis `data/seed/*.json`. Rien d'autre à faire.

## Fonctionnalités

- **On mange quoi ?** — une suggestion à la fois, tirée selon tes préférences de cuisine ; « Autre chose » ne reboucle jamais tant qu'il reste des plats ; les plats mangés il y a moins de 2 semaines sont rares. Filtres : cuisine, repas, temps, **facile**, **ingrédients courants**, **sans matériel spécial**.
- **Recettes** — fiches complètes (photo, étapes, ingrédients, matériel, conservation), recherche (nom, pays, ingrédient), tris, CRUD complet avec upload de photo.
- **Planning** — semaine par créneau, **génération automatique** (varié ou batch), marquage « mangé » → historique.
- **Batch cooking** — choisis des plats qui se conservent : liste de courses unique, plan de cuisine (plats longs en premier), répartition sur la semaine.
- **Courses** — générée depuis le planning, triée par rayon, cases mémorisées, copie / impression.
- **Historique** — ce qui a été mangé, notes ★, top des plats.
- **Export / Import** — JSON, JSONL, CSV, livre de recettes imprimable (PDF) ; import dédupliqué.
- **Mode admin** — onglet « Admin » : tableau de gestion (renommer, changer cuisine / repas en ligne, suppression et changement en masse), **remplacement de photo** (recherche Wikimedia, lien, fichier, glisser-déposer ou coller), **détection et fusion des doublons** (nom, ingrédients, photo identique).
- **Multi-utilisateur** — pseudo par cookie, sans mot de passe.

## Données

| Chemin | Rôle |
|---|---|
| `data/seed/*.json` | Recettes d'origine, versionnées (format : `data/seed/SCHEMA.md`) |
| `data/seed/_images.json` | Crédits des photos (Wikimedia Commons) |
| `static/img/recipes/` | Photos des recettes d'origine |
| `daily_food.db` | Base SQLite locale (planning, historique, recettes perso) — non versionnée |

Les recettes d'origine ne sont insérées que si elles manquent : tes modifications ne sont jamais écrasées, et une recette supprimée ne revient pas (bouton « Restaurer » dans Export).
Pour ajouter des recettes au catalogue : éditer/ajouter un JSON dans `data/seed/`, puis `python3 scripts/validate_seed.py` et `python3 scripts/fetch_images.py` (photos).

## Développement

```bash
pip install -r requirements-dev.txt
python -m pytest tests
```

## Stack

FastAPI · SQLite · Jinja2 · CSS maison · JS vanilla.
