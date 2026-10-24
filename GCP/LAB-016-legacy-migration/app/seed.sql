INSERT INTO public.orders (id, order_ref, customer_name, amount_cents, status, created_at)
VALUES
  (1001, 'LAB16-ORD-1001', 'Mali', 12500, 'PAID', '2026-01-10T09:00:00Z'),
  (1002, 'LAB16-ORD-1002', 'Niran', 45900, 'NEW', '2026-01-10T09:05:00Z'),
  (1003, 'LAB16-ORD-1003', 'Dao', 7800, 'CANCELLED', '2026-01-10T09:10:00Z'),
  (1004, 'LAB16-ORD-1004', 'Krit', 21300, 'PAID', '2026-01-10T09:15:00Z'),
  (1005, 'LAB16-ORD-1005', 'Ploy', 9900, 'NEW', '2026-01-10T09:20:00Z')
ON CONFLICT (order_ref) DO NOTHING;
SELECT setval(pg_get_serial_sequence('public.orders', 'id'),
              GREATEST(COALESCE((SELECT max(id) FROM public.orders), 1), 1), true);
