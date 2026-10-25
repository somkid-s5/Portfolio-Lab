from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.schema import metadata, products

CATEGORIES = ("books", "electronics", "home", "sports")
PRODUCT_COUNT = 2000
LIST_LIMIT = 50
WRITABLE_FIELDS = frozenset({"category", "name", "description", "image_url", "active"})


class ProductNotFound(Exception):
    pass


class VersionConflict(Exception):
    pass


def seed_rows():
    rows = []
    for product_id in range(1, PRODUCT_COUNT + 1):
        category = CATEGORIES[(product_id - 1) // 500]
        rows.append({
            "id": product_id,
            "category": category,
            "name": f"{category.title()} Item {product_id:04d}",
            "description": (
                f"Synthetic catalog metadata for {category} item {product_id:04d}. "
                "This record contains no customer, pricing, or inventory data."
            ),
            "image_url": "/static/product-placeholder.svg",
            "active": True,
            "version": 1,
        })
    return rows


def initialize_schema(engine):
    metadata.create_all(engine)


def seed_catalog(engine):
    statement = pg_insert(products).values(seed_rows()).on_conflict_do_nothing(
        index_elements=[products.c.id]
    )
    with engine.begin() as connection:
        result = connection.execute(statement)
    return {"seed_version": "catalog-v1", "expected": PRODUCT_COUNT, "inserted": result.rowcount}


def get_product(engine, product_id):
    with engine.connect() as connection:
        row = connection.execute(
            select(products).where(products.c.id == product_id, products.c.active.is_(True))
        ).mappings().first()
    return dict(row) if row else None


def get_category_products(engine, category):
    with engine.connect() as connection:
        rows = connection.execute(
            select(products)
            .where(products.c.category == category, products.c.active.is_(True))
            .order_by(products.c.id)
            .limit(LIST_LIMIT)
        ).mappings().all()
    return [dict(row) for row in rows]


def update_product(engine, product_id, expected_version, changes):
    invalid = set(changes) - WRITABLE_FIELDS
    if invalid or not changes:
        raise ValueError("Only non-empty catalog metadata fields can be updated.")
    if "category" in changes and changes["category"] not in CATEGORIES:
        raise ValueError("Category is not in the allowlist.")
    if "name" in changes and (not isinstance(changes["name"], str) or not 1 <= len(changes["name"]) <= 120):
        raise ValueError("Name must contain 1 to 120 characters.")
    if "description" in changes and (
        not isinstance(changes["description"], str) or len(changes["description"]) > 2000
    ):
        raise ValueError("Description must be at most 2,000 characters.")
    if "image_url" in changes and (
        not isinstance(changes["image_url"], str) or len(changes["image_url"]) > 240
    ):
        raise ValueError("Image URL must be at most 240 characters.")
    if "active" in changes and not isinstance(changes["active"], bool):
        raise ValueError("Active must be a boolean.")

    with engine.begin() as connection:
        current = connection.execute(
            select(products.c.category, products.c.version).where(products.c.id == product_id)
        ).mappings().first()
        if current is None:
            raise ProductNotFound
        if current["version"] != expected_version:
            raise VersionConflict
        statement = (
            update(products)
            .where(products.c.id == product_id, products.c.version == expected_version)
            .values(**changes, version=expected_version + 1, updated_at=datetime.now(timezone.utc))
            .returning(products)
        )
        updated = connection.execute(statement).mappings().first()
        if updated is None:
            raise VersionConflict
    return dict(updated), current["category"]


def list_product_ids(engine):
    with engine.connect() as connection:
        rows = connection.execute(select(products.c.id).order_by(products.c.id)).all()
    return [row[0] for row in rows]


def public_product(row):
    return {
        "id": row["id"],
        "category": row["category"],
        "name": row["name"],
        "description": row["description"],
        "image_url": row["image_url"],
        "active": row["active"],
        "version": row["version"],
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }
