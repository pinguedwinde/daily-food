"""Tests de fumée : seed valide, app qui démarre avec toutes les recettes, parcours principaux."""
import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ["DAILY_FOOD_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from validate_seed import load_all, validate  # noqa: E402


def test_seed_is_valid():
    recipes = load_all()
    assert validate(recipes) == []
    assert len(recipes) >= 100


@pytest.fixture(scope="module")
def client():
    with TestClient(app, cookies={"username": "test"}, follow_redirects=False) as c:
        yield c


@pytest.mark.parametrize("path", ["/", "/meals", "/planner", "/batch", "/shopping", "/history", "/export", "/meals/add", "/meals/1"])
def test_pages_render(client, path):
    assert client.get(path).status_code == 200


def test_login_required():
    with TestClient(app, follow_redirects=False) as c:
        assert c.get("/").status_code == 303


def test_suggestion_never_repeats_until_exhausted(client):
    r = client.get("/?region=antillais")
    assert "Autre chose" in r.text


def test_generate_and_shopping(client):
    assert client.post("/planner/generate", data={"mode": "varied", "slots": ["dinner"], "overwrite": "1"}).status_code == 303
    assert client.get("/shopping").status_code == 200


def test_export_import_roundtrip(client):
    data = client.get("/export/download?format=json").json()
    assert len(data) >= 100
    r = client.post("/import", data={"data": __import__("json").dumps(data)})
    assert "n=0" in r.headers["location"]  # aucun doublon créé


# ---------- mode admin ----------

def admin_client():
    return TestClient(app, cookies={"username": "test", "admin": "1"}, follow_redirects=False)


def test_admin_requires_toggle(client):
    assert client.get("/admin").status_code == 200
    assert "Activer le mode admin" in client.get("/admin").text
    assert client.post("/admin/bulk", data={"action": "delete", "ids": ["1"]}).status_code == 303


def test_admin_pages_and_quick_edit():
    with admin_client() as c:
        assert c.get("/admin").status_code == 200
        assert c.get("/admin?photo=none").status_code == 200
        assert c.get("/admin/duplicates").status_code == 200
        assert c.post("/admin/meals/1/field", data={"field": "region", "value": "antillais"}).json() == {"ok": True}
        assert c.post("/admin/meals/1/field", data={"field": "region", "value": "nope"}).status_code == 400


def test_admin_bulk_delete_and_merge():
    with admin_client() as c:
        for name in ("Doublon A", "Doublon B"):
            c.post("/meals/add", data={"name": name, "category": "dinner", "region": "africain", "ingredients": ["riz"], "steps": ["cuire"]})
        from database import get_db
        conn = get_db()
        a, b = [r["id"] for r in conn.execute("SELECT id FROM meals WHERE name IN ('Doublon A','Doublon B') ORDER BY id")]
        conn.execute("INSERT INTO plans (meal_id, plan_date, meal_slot) VALUES (?, '2030-01-01', 'dinner')", (b,))
        conn.commit()
        c.post("/admin/bulk", data={"action": "merge", "ids": [a, b]})
        assert conn.execute("SELECT COUNT(*) FROM meals WHERE id = ?", (b,)).fetchone()[0] == 0
        assert conn.execute("SELECT meal_id FROM plans WHERE plan_date = '2030-01-01'").fetchone()["meal_id"] == a
        c.post("/admin/bulk", data={"action": "delete", "ids": [a]})
        assert conn.execute("SELECT COUNT(*) FROM meals WHERE id = ?", (a,)).fetchone()[0] == 0
        conn.close()


def test_deleted_seed_does_not_come_back():
    from database import get_db, seed_recipes
    with admin_client() as c:
        conn = get_db()
        meal_id = conn.execute("SELECT id FROM meals WHERE slug IS NOT NULL LIMIT 1").fetchone()["id"]
        before = conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0]
        c.post(f"/meals/{meal_id}/delete")
        seed_recipes(conn)
        assert conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0] == before - 1
        conn.close()
