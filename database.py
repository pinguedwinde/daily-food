import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "daily_food.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'dinner',
            prep_time INTEGER,
            notes TEXT,
            created_by TEXT,
            image_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS meal_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meal_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            FOREIGN KEY (meal_id) REFERENCES meals(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS meal_ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meal_id INTEGER NOT NULL,
            ingredient TEXT NOT NULL,
            FOREIGN KEY (meal_id) REFERENCES meals(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meal_id INTEGER NOT NULL,
            plan_date DATE NOT NULL,
            meal_slot TEXT NOT NULL DEFAULT 'dinner',
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (meal_id) REFERENCES meals(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meal_id INTEGER NOT NULL,
            eaten_date DATE NOT NULL,
            meal_slot TEXT NOT NULL DEFAULT 'dinner',
            eaten_by TEXT,
            rating INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (meal_id) REFERENCES meals(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()
