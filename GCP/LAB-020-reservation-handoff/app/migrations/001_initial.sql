CREATE TABLE IF NOT EXISTS slots (
    slot_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    booked INTEGER NOT NULL DEFAULT 0 CHECK (booked >= 0 AND booked <= capacity)
);
CREATE TABLE IF NOT EXISTS bookings (
    booking_id TEXT PRIMARY KEY,
    created_by TEXT NOT NULL,
    slot_id TEXT NOT NULL REFERENCES slots(slot_id),
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'cancelled')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (created_by, idempotency_key)
);
CREATE TABLE IF NOT EXISTS report_jobs (
    report_id TEXT PRIMARY KEY,
    requested_by TEXT NOT NULL,
    report_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'ready', 'failed')),
    object_name TEXT,
    idempotency_key TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (requested_by, idempotency_key)
);
