-- Run as database owner after creating login inventory_app.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO inventory_app;
GRANT SELECT ON products, stock, movements TO inventory_app;
GRANT UPDATE(quantity) ON stock TO inventory_app;
GRANT INSERT(request_key,sku,delta,quantity_after,actor,note) ON movements TO inventory_app;
GRANT USAGE ON SEQUENCE movements_id_seq TO inventory_app;
