# Format des recettes seed

Chaque fichier `data/seed/<nom>.json` (hors fichiers commençant par `_`) est un **tableau JSON** de recettes.
Tout est en **français**. Les recettes sont réalistes pour une cuisine de maison en France (four, plaques, casserole,
poêle, éventuellement cocotte / robot) : pas de matériel de restaurant. Quand un plat original est infaisable chez soi
(ex. canard laqué), proposer une **version adaptée** et le dire dans `notes`.

```json
{
  "slug": "poulet-yassa",
  "name": "Poulet yassa",
  "region": "africain",
  "origin": "Sénégal",
  "category": "dinner",
  "prep_time": 20,
  "cook_time": 45,
  "difficulty": 1,
  "ingredient_access": 1,
  "equipment": [],
  "servings": 4,
  "batch_friendly": true,
  "keeps_days": 4,
  "tags": ["poulet", "mijoté", "batch cooking"],
  "ingredients": ["4 cuisses de poulet", "6 oignons", "3 citrons", "..."],
  "steps": ["Mariner le poulet ...", "..."],
  "notes": "Astuce, variante, accompagnement.",
  "image_query": "Poulet yassa"
}
```

| Champ | Règle |
|---|---|
| `slug` | minuscule, sans accent, tirets, **unique** dans tout le projet |
| `region` | `africain`, `antillais`, `asiatique`, `europeen` ou `monde` |
| `origin` | pays / région d'origine (texte libre) |
| `category` | `breakfast`, `lunch`, `dinner`, `snack`, `dessert` |
| `prep_time` / `cook_time` | minutes (entiers), préparation active / cuisson |
| `difficulty` | 1 = facile (débutant), 2 = moyen, 3 = ambitieux. **Viser surtout 1 et 2.** |
| `ingredient_access` | 1 = supermarché normal, 2 = épicerie asiatique/africaine/exotique ou rayon spécialisé, 3 = difficile à trouver (à éviter, ou donner un substitut) |
| `equipment` | uniquement le matériel **non standard** (ex. `["wok"]`, `["cocotte"]`, `["mixeur"]`, `["robot pâtissier"]`, `["cuiseur vapeur"]`, `["friteuse"]`, `["barbecue"]`) ; `[]` si poêle/casserole/four suffisent |
| `servings` | nombre de personnes |
| `batch_friendly` | `true` si ça se prépare en grosse quantité et se conserve/congèle bien |
| `keeps_days` | jours de conservation au frigo (entier) ; `0` si à manger tout de suite |
| `tags` | minuscules ; vocabulaire conseillé : `rapide`, `végétarien`, `vegan`, `sans gluten`, `pas cher`, `batch cooking`, `one pot`, `au four`, `mijoté`, `poulet`, `boeuf`, `porc`, `poisson`, `riz`, `pâtes`, `soupe`, `salade`, `frit`, `léger`, `gourmand`, `traditionnel`, `épicé`, `enfant`, `festif` |
| `ingredients` | 5 à 14 chaînes avec quantités ; noms **simples et cohérents** (« oignon », « ail », « huile », « sel, poivre ») car ils servent à fusionner la liste de courses |
| `steps` | 4 à 9 étapes, une phrase ou deux chacune, impératives, avec temps/températures |
| `notes` | 1 à 2 phrases : astuce, variante ou substitution |
| `image_query` | requête de recherche Wikimedia Commons pour trouver une photo du plat (nom du plat, éventuellement avec « plat » ou le pays) |
| `image_url` | *(optionnel)* URL à conserver telle quelle (reprise des plats existants) |

Les précisions n'ont pas besoin d'être parfaites : l'objectif est une recette crédible, simple et appétissante.
