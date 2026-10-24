import json

from app.catalog import initialize_schema, seed_catalog
from app.database import close_database_engine, create_database_engine


def main():
    engine = create_database_engine()
    try:
        initialize_schema(engine)
        result = seed_catalog(engine)
        print(json.dumps({"event": "catalog_seeded", **result}, sort_keys=True))
    finally:
        close_database_engine(engine)


if __name__ == "__main__":
    main()
