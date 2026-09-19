"""SQLite-backed place catalog."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus

from catalog import CATEGORIES


def normalize_name(name: str) -> str:
    value = unicodedata.normalize("NFKC", name).casefold().strip()
    return re.sub(r"\s+", " ", value)


def maps_search_url(name: str) -> str:
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(
        f"{name}, Chiang Mai"
    )


class CatalogDB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
                slug TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                position INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                map_url TEXT NOT NULL,
                rating REAL,
                reviews INTEGER,
                place_type TEXT,
                note TEXT,
                area TEXT,
                latitude REAL,
                longitude REAL,
                work_friendly INTEGER NOT NULL DEFAULT 0,
                beautiful INTEGER NOT NULL DEFAULT 0,
                source TEXT,
                last_verified TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS place_categories (
                place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
                category_slug TEXT NOT NULL REFERENCES categories(slug),
                PRIMARY KEY (place_id, category_slug)
            );

            CREATE INDEX IF NOT EXISTS idx_place_categories_category
                ON place_categories(category_slug, place_id);
            CREATE INDEX IF NOT EXISTS idx_places_active_name
                ON places(active, normalized_name);

            CREATE TABLE IF NOT EXISTS favorite_places (
                user_id INTEGER NOT NULL,
                place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, place_id)
            );
            """
        )
        existing_columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(places)")
        }
        migrations = {
            "area": "ALTER TABLE places ADD COLUMN area TEXT",
            "latitude": "ALTER TABLE places ADD COLUMN latitude REAL",
            "longitude": "ALTER TABLE places ADD COLUMN longitude REAL",
            "work_friendly": (
                "ALTER TABLE places ADD COLUMN work_friendly INTEGER NOT NULL DEFAULT 0"
            ),
            "beautiful": (
                "ALTER TABLE places ADD COLUMN beautiful INTEGER NOT NULL DEFAULT 0"
            ),
        }
        for column, statement in migrations.items():
            if column not in existing_columns:
                self.conn.execute(statement)
        self.conn.executemany(
            """
            INSERT INTO categories(slug, label, position)
            VALUES (?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                label = excluded.label,
                position = excluded.position
            """,
            [
                (slug, item["label"], item["position"])
                for slug, item in CATEGORIES.items()
            ],
        )
        self.conn.commit()

    def seed_from_json(self, path: str | Path) -> int:
        items = json.loads(Path(path).read_text(encoding="utf-8"))
        inserted = 0
        for item in items:
            before = self.conn.total_changes
            normalized = normalize_name(item["name"])
            self.conn.execute(
                """
                INSERT INTO places(
                    name, normalized_name, map_url, rating, reviews,
                    place_type, note, area, latitude, longitude,
                    work_friendly, beautiful, source, last_verified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_name) DO UPDATE SET
                    rating = excluded.rating,
                    reviews = excluded.reviews,
                    place_type = excluded.place_type,
                    area = excluded.area,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    work_friendly = excluded.work_friendly,
                    beautiful = excluded.beautiful,
                    source = excluded.source,
                    last_verified = excluded.last_verified
                """,
                (
                    item["name"],
                    normalized,
                    item.get("map_url") or maps_search_url(item["name"]),
                    item.get("rating"),
                    item.get("reviews"),
                    item.get("place_type"),
                    item.get("note"),
                    item.get("area"),
                    item.get("latitude"),
                    item.get("longitude"),
                    int(bool(item.get("work_friendly"))),
                    int(bool(item.get("beautiful"))),
                    item.get("source"),
                    item.get("last_verified"),
                ),
            )
            inserted += int(self.conn.total_changes > before)
            row = self.conn.execute(
                "SELECT id FROM places WHERE normalized_name = ?", (normalized,)
            ).fetchone()
            for category in item["categories"]:
                if category not in CATEGORIES:
                    raise ValueError(f"Unknown category {category!r} for {item['name']}")
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO place_categories(place_id, category_slug)
                    VALUES (?, ?)
                    """,
                    (row["id"], category),
                )
        self.conn.commit()
        return inserted

    def category_count(self, category_slug: str) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM places p
            JOIN place_categories pc ON pc.place_id = p.id
            WHERE p.active = 1 AND pc.category_slug = ?
            """,
            (category_slug,),
        ).fetchone()
        return int(row["n"])

    def group_count(self, category_slugs: Iterable[str]) -> int:
        slugs = list(category_slugs)
        if not slugs:
            return 0
        placeholders = ",".join("?" for _ in slugs)
        row = self.conn.execute(
            f"""
            SELECT COUNT(DISTINCT p.id) AS n
            FROM places p
            JOIN place_categories pc ON pc.place_id = p.id
            WHERE p.active = 1 AND pc.category_slug IN ({placeholders})
            """,
            slugs,
        ).fetchone()
        return int(row["n"])

    def list_places(
        self, category_slug: str, area: str | None = None
    ) -> list[sqlite3.Row]:
        area_clause = " AND p.area = ?" if area else ""
        params: list[str] = [category_slug]
        if area:
            params.append(area)
        return self.conn.execute(
            f"""
            SELECT p.*
            FROM places p
            JOIN place_categories pc ON pc.place_id = p.id
            WHERE p.active = 1 AND pc.category_slug = ?
            {area_clause}
            ORDER BY COALESCE(p.rating, 0) DESC, COALESCE(p.reviews, 0) DESC, p.name
            """,
            params,
        ).fetchall()

    def category_area_counts(self, category_slug: str) -> dict[str, int]:
        rows = self.conn.execute(
            """
            SELECT p.area, COUNT(*) AS n
            FROM places p
            JOIN place_categories pc ON pc.place_id = p.id
            WHERE p.active = 1 AND pc.category_slug = ? AND p.area IS NOT NULL
            GROUP BY p.area
            """,
            (category_slug,),
        ).fetchall()
        return {str(row["area"]): int(row["n"]) for row in rows}

    def list_coffee(
        self,
        *,
        area: str | None = None,
        work_friendly: bool = False,
        beautiful: bool = False,
        favorite_user_id: int | None = None,
    ) -> list[sqlite3.Row]:
        clauses = ["p.active = 1", "pc.category_slug = 'coffee'"]
        params: list[str | int] = []
        joins = ""
        if area:
            clauses.append("p.area = ?")
            params.append(area)
        if work_friendly:
            clauses.append("p.work_friendly = 1")
        if beautiful:
            clauses.append("p.beautiful = 1")
        if favorite_user_id is not None:
            joins = "JOIN favorite_places fp ON fp.place_id = p.id"
            clauses.append("fp.user_id = ?")
            params.append(favorite_user_id)
        return self.conn.execute(
            f"""
            SELECT DISTINCT p.*
            FROM places p
            JOIN place_categories pc ON pc.place_id = p.id
            {joins}
            WHERE {' AND '.join(clauses)}
            ORDER BY COALESCE(p.rating, 0) DESC,
                     COALESCE(p.reviews, 0) DESC,
                     p.name
            """,
            params,
        ).fetchall()

    def nearest_coffee(
        self, latitude: float, longitude: float, limit: int = 15
    ) -> list[dict[str, object]]:
        places = self.conn.execute(
            """
            SELECT DISTINCT p.*
            FROM places p
            JOIN place_categories pc ON pc.place_id = p.id
            WHERE p.active = 1
              AND pc.category_slug = 'coffee'
              AND p.latitude IS NOT NULL
              AND p.longitude IS NOT NULL
            """
        ).fetchall()

        def distance_km(place: sqlite3.Row) -> float:
            lat1 = math.radians(latitude)
            lon1 = math.radians(longitude)
            lat2 = math.radians(float(place["latitude"]))
            lon2 = math.radians(float(place["longitude"]))
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            value = (
                math.sin(dlat / 2) ** 2
                + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            )
            return 6371.0 * 2 * math.asin(math.sqrt(value))

        ranked = [dict(place) | {"distance_km": distance_km(place)} for place in places]
        ranked.sort(key=lambda item: float(item["distance_km"]))
        return ranked[:limit]

    def is_favorite(self, user_id: int, place_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM favorite_places WHERE user_id = ? AND place_id = ?",
            (user_id, place_id),
        ).fetchone()
        return row is not None

    def toggle_favorite(self, user_id: int, place_id: int) -> bool:
        if self.is_favorite(user_id, place_id):
            self.conn.execute(
                "DELETE FROM favorite_places WHERE user_id = ? AND place_id = ?",
                (user_id, place_id),
            )
            active = False
        else:
            self.conn.execute(
                "INSERT OR IGNORE INTO favorite_places(user_id, place_id) VALUES (?, ?)",
                (user_id, place_id),
            )
            active = True
        self.conn.commit()
        return active

    def get_place(self, place_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM places WHERE id = ? AND active = 1", (place_id,)
        ).fetchone()

    def get_place_categories(self, place_id: int) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT category_slug
            FROM place_categories
            WHERE place_id = ?
            ORDER BY category_slug
            """,
            (place_id,),
        ).fetchall()
        return [row["category_slug"] for row in rows]

    def search_places(self, query: str, limit: int = 10) -> list[sqlite3.Row]:
        words = [word for word in normalize_name(query).split(" ") if word]
        if not words:
            return []
        clauses = []
        params: list[str | int] = []
        for word in words:
            clauses.append(
                "(p.normalized_name LIKE ? OR lower(COALESCE(p.place_type,'')) LIKE ? "
                "OR lower(COALESCE(p.note,'')) LIKE ?)"
            )
            needle = f"%{word}%"
            params.extend([needle, needle, needle])
        params.append(limit)
        return self.conn.execute(
            f"""
            SELECT DISTINCT p.*
            FROM places p
            WHERE p.active = 1 AND {' AND '.join(clauses)}
            ORDER BY COALESCE(p.rating, 0) DESC, COALESCE(p.reviews, 0) DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    def add_place(
        self,
        *,
        name: str,
        category_slug: str,
        map_url: str,
        note: str | None = None,
        source: str = "telegram_admin",
    ) -> int:
        if category_slug not in CATEGORIES:
            raise ValueError(f"Unknown category: {category_slug}")
        normalized = normalize_name(name)
        self.conn.execute(
            """
            INSERT INTO places(name, normalized_name, map_url, note, source)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(normalized_name) DO UPDATE SET
                map_url = excluded.map_url,
                note = CASE
                    WHEN excluded.note IS NULL OR excluded.note = '' THEN places.note
                    ELSE excluded.note
                END,
                active = 1
            """,
            (name.strip(), normalized, map_url, note, source),
        )
        row = self.conn.execute(
            "SELECT id FROM places WHERE normalized_name = ?", (normalized,)
        ).fetchone()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO place_categories(place_id, category_slug)
            VALUES (?, ?)
            """,
            (row["id"], category_slug),
        )
        self.conn.commit()
        return int(row["id"])

    def deactivate_place(self, place_id: int) -> bool:
        cursor = self.conn.execute(
            "UPDATE places SET active = 0 WHERE id = ? AND active = 1", (place_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def total_places(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM places WHERE active = 1"
        ).fetchone()
        return int(row["n"])
