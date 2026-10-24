import json
import os
import re

from sqlalchemy import text

from app.catalog import initialize_schema, seed_catalog
from app.database import close_database_engine, create_database_engine


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.@-]{0,62}$")
OPERATOR_UPDATE_COLUMNS = (
    "category",
    "name",
    "description",
    "image_url",
    "active",
    "version",
    "updated_at",
)


def quote_identifier(value):
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError("PostgreSQL role/database name contains unsupported characters.")
    return '"' + value + '"'


def grant_runtime_access(engine, database_name, reader_user, operator_user):
    database = quote_identifier(database_name)
    reader = quote_identifier(reader_user)
    operator = quote_identifier(operator_user)
    if reader_user == operator_user:
        raise ValueError("Reader and operator database users must be different.")

    writable_columns = ", ".join(quote_identifier(column) for column in OPERATOR_UPDATE_COLUMNS)
    statements = (
        f"GRANT CONNECT ON DATABASE {database} TO {reader}",
        f"GRANT CONNECT ON DATABASE {database} TO {operator}",
        f"GRANT USAGE ON SCHEMA public TO {reader}",
        f"GRANT USAGE ON SCHEMA public TO {operator}",
        f"GRANT SELECT ON TABLE public.products TO {reader}",
        f"GRANT SELECT ON TABLE public.products TO {operator}",
        f"GRANT UPDATE ({writable_columns}) ON TABLE public.products TO {operator}",
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def main():
    engine = create_database_engine()
    try:
        initialize_schema(engine)
        result = seed_catalog(engine)
        grant_runtime_access(
            engine,
            os.environ.get("DB_NAME", "catalog"),
            os.environ["DB_READER_USER"],
            os.environ["DB_OPERATOR_USER"],
        )
        print(json.dumps({"event": "catalog_seeded_and_granted", **result}, sort_keys=True))
    finally:
        close_database_engine(engine)


if __name__ == "__main__":
    main()
