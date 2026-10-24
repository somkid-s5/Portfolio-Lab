SELECT s.id,s.capacity,s.booked,count(b.id) FILTER (WHERE b.status='confirmed') AS confirmed
FROM slots s LEFT JOIN bookings b ON b.slot_id=s.id
GROUP BY s.id,s.capacity,s.booked
HAVING s.booked < 0 OR s.booked > s.capacity
 OR s.booked <> count(b.id) FILTER (WHERE b.status='confirmed');
