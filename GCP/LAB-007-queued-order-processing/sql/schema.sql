-- First installation only. Bootstrap must refuse to reset an existing schema.
CREATE SCHEMA lab007;
REVOKE ALL ON SCHEMA lab007 FROM PUBLIC;
CREATE TABLE lab007.schema_meta (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    version integer NOT NULL CHECK (version = 1),
    seed_version text NOT NULL CHECK (seed_version = 'catalog-v1')
);
INSERT INTO lab007.schema_meta VALUES (true, 1, 'catalog-v1');

CREATE TABLE lab007.products (
    sku text PRIMARY KEY CHECK (sku ~ '^[A-Z][A-Z0-9-]{0,31}$'),
    initial_stock integer NOT NULL CHECK (initial_stock >= 0),
    available integer NOT NULL CHECK (available BETWEEN 0 AND initial_stock),
    unit_price_satang bigint NOT NULL CHECK (unit_price_satang BETWEEN 0 AND 100000000)
);
INSERT INTO lab007.products VALUES
 ('BOOK-01',200,200,12500), ('LAST-01',1,1,100), ('USB-01',200,200,9900);

CREATE TABLE lab007.orders (
    order_id text PRIMARY KEY CHECK (order_id ~ '^[a-f0-9]{32}$'),
    owner text NOT NULL CHECK (owner ~ '^[a-z][a-z0-9_]{0,63}$'),
    key_hash text NOT NULL CHECK (key_hash ~ '^[a-f0-9]{64}$'),
    request_fingerprint text NOT NULL CHECK (request_fingerprint ~ '^[a-f0-9]{64}$'),
    order_fingerprint text NOT NULL CHECK (order_fingerprint ~ '^[a-f0-9]{64}$'),
    total_satang bigint NOT NULL CHECK (total_satang >= 0),
    state text NOT NULL DEFAULT 'accepted' CHECK (state IN ('accepted','confirmed','rejected')),
    safe_reason text CHECK (safe_reason ~ '^[a-z][a-z0-9_]{0,63}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    UNIQUE(owner,key_hash),
    CHECK ((state='accepted' AND finished_at IS NULL AND safe_reason IS NULL)
        OR (state='confirmed' AND finished_at IS NOT NULL AND safe_reason IS NULL)
        OR (state='rejected' AND finished_at IS NOT NULL AND safe_reason IS NOT NULL))
);
CREATE TABLE lab007.order_items (
    order_id text NOT NULL REFERENCES lab007.orders,
    sku text NOT NULL REFERENCES lab007.products,
    quantity integer NOT NULL CHECK (quantity BETWEEN 1 AND 3),
    unit_price_satang bigint NOT NULL CHECK (unit_price_satang BETWEEN 0 AND 100000000),
    PRIMARY KEY(order_id,sku),
    UNIQUE(order_id,sku,quantity,unit_price_satang)
);
CREATE TABLE lab007.outbox (
    event_id text PRIMARY KEY CHECK (event_id ~ '^[a-f0-9]{32}$'),
    order_id text NOT NULL UNIQUE REFERENCES lab007.orders,
    UNIQUE(event_id,order_id),
    payload text NOT NULL CHECK (octet_length(payload) BETWEEN 1 AND 4096),
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[a-f0-9]{64}$'),
    state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending','publishing','published','exhausted')),
    epoch integer NOT NULL DEFAULT 0 CHECK (epoch BETWEEN 0 AND 2),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 10),
    lease_token text CHECK (lease_token ~ '^[a-f0-9]{32}$'),
    lease_until timestamptz,
    last_outcome text CHECK (last_outcome ~ '^[a-z][a-z0-9_]{0,63}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    published_at timestamptz,
    CHECK ((state='publishing' AND lease_token IS NOT NULL AND lease_until IS NOT NULL)
        OR (state<>'publishing' AND lease_token IS NULL AND lease_until IS NULL))
);
CREATE INDEX outbox_dispatchable ON lab007.outbox(state,created_at,event_id);
CREATE TABLE lab007.processed_events (
    event_id text PRIMARY KEY REFERENCES lab007.outbox(event_id),
    order_id text NOT NULL UNIQUE REFERENCES lab007.orders,
    order_fingerprint text NOT NULL CHECK (order_fingerprint ~ '^[a-f0-9]{64}$'),
    outcome text NOT NULL CHECK (outcome IN ('confirmed','rejected')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY(event_id,order_id) REFERENCES lab007.outbox(event_id,order_id)
);
CREATE TABLE lab007.reservations (
    order_id text NOT NULL,
    sku text NOT NULL,
    units integer NOT NULL CHECK (units BETWEEN 1 AND 3),
    unit_price_satang bigint NOT NULL CHECK (unit_price_satang BETWEEN 0 AND 100000000),
    PRIMARY KEY(order_id,sku),
    FOREIGN KEY(order_id,sku,units,unit_price_satang)
        REFERENCES lab007.order_items(order_id,sku,quantity,unit_price_satang)
);
CREATE TABLE lab007.operator_actions (
    operator_name text NOT NULL CHECK (operator_name ~ '^[a-z][a-z0-9_]{0,63}$'),
    key_hash text NOT NULL CHECK (key_hash ~ '^[a-f0-9]{64}$'),
    event_id text NOT NULL REFERENCES lab007.outbox,
    source_digest text NOT NULL CHECK (source_digest ~ '^[a-f0-9]{64}$'),
    epoch integer NOT NULL CHECK (epoch BETWEEN 0 AND 2),
    outcome text NOT NULL CHECK (outcome IN ('prepared','already_resolved')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(operator_name,key_hash)
);
