SELECT 'stock_balance' AS invariant, p.sku AS reference
FROM products p LEFT JOIN stock_events e ON e.sku=p.sku
GROUP BY p.sku,p.initial_stock,p.available
HAVING p.available <> p.initial_stock + COALESCE(sum(e.delta),0)
UNION ALL
SELECT 'order_total',o.id::text
FROM orders o JOIN order_items i ON i.order_id=o.id
GROUP BY o.id,o.total_satang
HAVING o.total_satang <> sum(i.quantity*i.price_snapshot_satang)
UNION ALL
SELECT 'empty_order',o.id::text FROM orders o
WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id=o.id)
UNION ALL
SELECT 'item_ledger',i.order_id::text || ':' || i.sku
FROM order_items i JOIN orders o ON o.id=i.order_id
LEFT JOIN stock_events e ON e.order_id=i.order_id AND e.sku=i.sku
GROUP BY i.order_id,i.sku,i.quantity,o.status
HAVING count(*) FILTER (WHERE e.event='reserved') <> 1
 OR COALESCE(sum(e.delta) FILTER (WHERE e.event='reserved'),0) <> -i.quantity
 OR (o.status='confirmed' AND count(*) FILTER (WHERE e.event='cancelled') <> 0)
 OR (o.status='cancelled' AND (
   count(*) FILTER (WHERE e.event='cancelled') <> 1
   OR COALESCE(sum(e.delta) FILTER (WHERE e.event='cancelled'),0) <> i.quantity));
