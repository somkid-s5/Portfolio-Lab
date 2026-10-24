BEGIN;
CREATE TABLE IF NOT EXISTS products (
  sku text PRIMARY KEY CHECK (sku ~ '^[A-Z0-9-]{1,32}$'),
  name text NOT NULL,
  opening_stock integer NOT NULL CHECK (opening_stock >= 0)
);
CREATE TABLE IF NOT EXISTS stock (
  sku text PRIMARY KEY REFERENCES products(sku),
  quantity integer NOT NULL CHECK (quantity >= 0)
);
CREATE TABLE IF NOT EXISTS movements (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  request_key text UNIQUE NOT NULL,
  sku text NOT NULL REFERENCES products(sku),
  delta integer NOT NULL CHECK (delta <> 0 AND delta BETWEEN -1000 AND 1000),
  quantity_after integer NOT NULL CHECK (quantity_after >= 0),
  actor text NOT NULL,
  note text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
COMMIT;
