INSERT INTO slots(id,label,capacity) VALUES
(1,'Monday 09:00 training',2),(2,'Monday 11:00 training',2),
(3,'Tuesday 09:00 support',3),(4,'Tuesday 11:00 support',3),
(5,'Wednesday 14:00 workshop',4)
ON CONFLICT(id) DO NOTHING;
