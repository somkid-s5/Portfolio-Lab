-- Empty result means every stock balance reconciles with committed movements.
SELECT p.sku, s.quantity, p.opening_stock + COALESCE(sum(m.delta),0) AS expected
FROM products p JOIN stock s USING(sku) LEFT JOIN movements m USING(sku)
GROUP BY p.sku,p.opening_stock,s.quantity
HAVING s.quantity <> p.opening_stock + COALESCE(sum(m.delta),0) OR s.quantity < 0;
