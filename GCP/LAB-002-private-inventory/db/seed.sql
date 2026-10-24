BEGIN;
INSERT INTO products(sku,name,opening_stock) VALUES
('PEN-01','Blue pen',20),('BOOK-01','Notebook',30),('CABLE-01','USB cable',15),
('MOUSE-01','Office mouse',10),('BAG-01','Laptop bag',5)
ON CONFLICT (sku) DO NOTHING;
INSERT INTO stock(sku,quantity)
SELECT sku,opening_stock FROM products ON CONFLICT (sku) DO NOTHING;
COMMIT;
