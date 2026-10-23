-- NOLOGIN by design: private bootstrap provisions credentials separately.
-- These roles must be NEW on this dedicated instance; never mutate shared roles.
CREATE ROLE order_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 8;
CREATE ROLE outbox_dispatcher NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 2;
CREATE ROLE order_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 12;
GRANT USAGE ON SCHEMA lab007 TO order_api,outbox_dispatcher,order_worker;
GRANT SELECT ON lab007.schema_meta TO order_api,outbox_dispatcher,order_worker;
GRANT SELECT ON lab007.products,lab007.orders,lab007.order_items,lab007.outbox
    TO order_api;
GRANT INSERT ON lab007.orders,lab007.order_items,lab007.outbox TO order_api;
GRANT SELECT ON lab007.outbox,lab007.orders TO outbox_dispatcher;
GRANT UPDATE(state,epoch,attempts,lease_token,lease_until,last_outcome,published_at)
    ON lab007.outbox TO outbox_dispatcher;
GRANT SELECT ON lab007.products,lab007.orders,lab007.order_items,lab007.outbox,
    lab007.processed_events,lab007.reservations TO order_worker;
GRANT UPDATE(available) ON lab007.products TO order_worker;
GRANT UPDATE(state,safe_reason,finished_at) ON lab007.orders TO order_worker;
GRANT INSERT ON lab007.processed_events,lab007.reservations TO order_worker;
-- No DDL, price/seed changes, DELETE, ledger UPDATE or admin credentials granted.
-- Replay/operator SQL interface is added only with its audited implementation.
