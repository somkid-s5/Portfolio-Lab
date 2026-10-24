INSERT INTO products(sku,name,unit_price_satang,initial_stock,available) VALUES
 ('BOOK-01','Cloud notebook',12500,10,10),
 ('MUG-01','Engineer mug',9900,5,5),
 ('PEN-01','Blue pen',3000,12,12),
 ('USB-01','Lab USB case',25000,4,4),
 ('BAG-01','Canvas bag',19900,6,6)
ON CONFLICT (sku) DO NOTHING;
