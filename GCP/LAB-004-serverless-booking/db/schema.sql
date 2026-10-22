CREATE TABLE IF NOT EXISTS slots (
  id integer PRIMARY KEY,
  label text NOT NULL,
  capacity integer NOT NULL CHECK (capacity > 0),
  booked integer NOT NULL DEFAULT 0 CHECK (booked >= 0 AND booked <= capacity)
);
CREATE TABLE IF NOT EXISTS bookings (
  id uuid PRIMARY KEY,
  username text NOT NULL,
  slot_id integer NOT NULL REFERENCES slots(id),
  request_key text NOT NULL,
  status text NOT NULL CHECK (status IN ('confirmed','cancelled')),
  created_at timestamptz NOT NULL DEFAULT now(),
  cancelled_at timestamptz,
  UNIQUE(username,request_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_booking_per_user_slot
  ON bookings(username,slot_id) WHERE status='confirmed';
CREATE TABLE IF NOT EXISTS booking_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  booking_id uuid NOT NULL REFERENCES bookings(id),
  event text NOT NULL CHECK (event IN ('reserved','cancelled')),
  actor text NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT now()
);
