REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE booking TO booking_a,booking_b;
GRANT USAGE ON SCHEMA public TO booking_a,booking_b;
GRANT SELECT ON slots,bookings,booking_events TO booking_a,booking_b;
GRANT UPDATE(booked) ON slots TO booking_a,booking_b;
GRANT INSERT(id,username,slot_id,request_key,status) ON bookings TO booking_a,booking_b;
GRANT UPDATE(status,cancelled_at) ON bookings TO booking_a,booking_b;
GRANT INSERT(booking_id,event,actor) ON booking_events TO booking_a,booking_b;
GRANT USAGE ON SEQUENCE booking_events_id_seq TO booking_a,booking_b;
