CREATE SCHEMA IF NOT EXISTS lab19;
-- migrate:split
CREATE TABLE IF NOT EXISTS lab19.tasks (
    task_id UUID PRIMARY KEY,
    idempotency_key VARCHAR(80) NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('QUEUED', 'SUCCEEDED', 'FAILED')),
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
-- migrate:split
GRANT USAGE ON SCHEMA lab19 TO lab19_api_role, lab19_worker_role;
-- migrate:split
GRANT SELECT, INSERT ON lab19.tasks TO lab19_api_role;
-- migrate:split
GRANT SELECT, UPDATE ON lab19.tasks TO lab19_worker_role;
-- migrate:split
ALTER DEFAULT PRIVILEGES IN SCHEMA lab19 GRANT SELECT, INSERT ON TABLES TO lab19_api_role;
-- migrate:split
ALTER DEFAULT PRIVILEGES IN SCHEMA lab19 GRANT SELECT, UPDATE ON TABLES TO lab19_worker_role;
