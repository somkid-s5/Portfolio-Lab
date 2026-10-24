CREATE TABLE products (
  sku text PRIMARY KEY CHECK (sku ~ '^[A-Z0-9][A-Z0-9-]{2,19}$'),
  name text NOT NULL,
  unit_price_satang bigint NOT NULL CHECK (unit_price_satang BETWEEN 1 AND 100000000),
  initial_stock integer NOT NULL CHECK (initial_stock >= 0),
  available integer NOT NULL CHECK (available >= 0 AND available <= initial_stock)
);
CREATE TABLE orders (
  id uuid PRIMARY KEY,
  username text NOT NULL,
  request_key text NOT NULL,
  request_fingerprint text NOT NULL CHECK (request_fingerprint ~ '^[a-f0-9]{64}$'),
  status text NOT NULL CHECK (status IN ('confirmed','cancelled')),
  total_satang bigint NOT NULL CHECK (total_satang > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  cancelled_at timestamptz,
  UNIQUE(username,request_key),
  CHECK ((status='confirmed' AND cancelled_at IS NULL) OR (status='cancelled' AND cancelled_at IS NOT NULL))
);
CREATE TABLE order_items (
  order_id uuid NOT NULL REFERENCES orders(id),
  sku text NOT NULL REFERENCES products(sku),
  quantity integer NOT NULL CHECK (quantity BETWEEN 1 AND 20),
  price_snapshot_satang bigint NOT NULL CHECK (price_snapshot_satang > 0),
  PRIMARY KEY(order_id,sku)
);
CREATE TABLE stock_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_id uuid NOT NULL,
  sku text NOT NULL,
  event text NOT NULL CHECK (event IN ('reserved','cancelled')),
  delta integer NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(order_id,sku) REFERENCES order_items(order_id,sku),
  UNIQUE(order_id,sku,event),
  CHECK ((event='reserved' AND delta < 0) OR (event='cancelled' AND delta > 0))
);
