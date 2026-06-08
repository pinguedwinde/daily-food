# On mange quoi aujourd'hui ?

Application web multi-utilisateur de planification de repas. Crée ta base de plats, planifie ta semaine, génère une liste de courses et retrouve ton historique.

## Démarrage rapide

```bash
./start.sh
```

Puis ouvre http://localhost:8000.

## Fonctionnalités

- **Plats** — CRUD complet avec catégories (petit-déj, déjeuner, dîner, goûter, dessert), tags, ingrédients, temps de préparation, notes
- **Photos** — URL distante ou upload de fichier
- **Planning** — Glisse tes plats sur la semaine par créneau
- **Suggestion aléatoire** — L'app te propose quoi manger aujourd'hui avec filtres
- **Courses** — Liste de courses générée automatiquement depuis le planning
- **Historique** — Garde trace de ce que tu as mangé
- **Multi-utilisateur** — Connexion par pseudo (cookie), sans mot de passe
- **Export/Import** — Sauvegarde et restaure ta base de plats en JSON
- **Recherche** — Filtre par nom, catégorie et tags

## Stack

- [FastAPI](https://fastapi.tiangolo.com/) — backend Python
- [SQLite](https://sqlite.org/) — base de données embarquée
- [Jinja2](https://jinja.palletsprojects.com/) — templates serveur
- [Pico CSS](https://picocss.com/) — CSS minimal
- [python-multipart](https://github.com/andrew-d/python-multipart) — upload de fichiers

## Structure

```
app.py              # Routes et logique métier
database.py         # Connexion SQLite et schéma
static/style.css    # Styles personnalisés
static/script.js    # Interactions frontend
templates/          # Templates Jinja2
start.sh            # Lancement one-command
requirements.txt    # Dépendances Python
```
