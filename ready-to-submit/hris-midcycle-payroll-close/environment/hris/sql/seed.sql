INSERT INTO leave_plans(plan_id, accrual_hours_per_period) VALUES
  ('PTO-NE', 3.08),
  ('PTO-EX', 4.00),
  ('PTO-SEA', 1.50),
  ('PTO-LOA', 0.00);

INSERT INTO pay_periods(period_id, start_date, end_date, cutoff_at, work_days) VALUES
  ('2026-W32', '2026-08-03', '2026-08-09', '2026-08-07T18:00:00Z', 5);

INSERT INTO employees(employee_id, status, location_id, hire_date) VALUES
  ('E000001', 'active', 'LOC-01', '2019-03-12'),
  ('E000002', 'active', 'LOC-02', '2016-07-01'),
  ('E000003', 'active', 'LOC-03', '2021-01-18'),
  ('E000004', 'active', 'LOC-04', '2020-11-02'),
  ('E000005', 'active', 'LOC-05', '2018-05-22'),
  ('E000006', 'active', 'LOC-06', '2022-09-09'),
  ('E000007', 'leave_of_absence', 'LOC-07', '2015-02-14'),
  ('E000008', 'seasonal', 'LOC-08', '2024-04-01');

INSERT INTO assignments(
  employee_id, effective_date, end_date, cost_center, department_id,
  flsa_status, leave_plan, hourly_rate_cents, salary_per_period_cents
) VALUES
  ('E000001', '2024-01-01', NULL, 'CC-WH-02', 'DEPT-WH', 'non_exempt', 'PTO-NE', 2000, NULL),
  ('E000002', '2023-01-01', NULL, 'CC-FIN-10', 'DEPT-FIN', 'exempt', 'PTO-EX', NULL, 150000),
  ('E000003', '2024-06-01', NULL, 'CC-OPS-03', 'DEPT-OPS', 'non_exempt', 'PTO-NE', 1800, NULL),
  ('E000004', '2024-02-01', NULL, 'CC-OPS-04', 'DEPT-OPS', 'non_exempt', 'PTO-NE', 1600, NULL),
  ('E000005', '2023-08-01', NULL, 'CC-HR-01', 'DEPT-HR', 'non_exempt', 'PTO-NE', 2200, NULL),
  ('E000006', '2025-01-01', NULL, 'CC-WH-06', 'DEPT-WH', 'non_exempt', 'PTO-NE', 1500, NULL),
  ('E000007', '2022-01-01', NULL, 'CC-FIN-11', 'DEPT-FIN', 'exempt', 'PTO-LOA', NULL, 180000),
  ('E000008', '2024-04-01', NULL, 'CC-SEA-01', 'DEPT-SEA', 'non_exempt', 'PTO-SEA', 1400, NULL);

INSERT INTO punches(employee_id, punched_at, direction) VALUES
  ('E000001', '2026-08-03T08:00:00Z', 'in'),
  ('E000001', '2026-08-03T18:00:00Z', 'out'),
  ('E000001', '2026-08-04T08:00:00Z', 'in'),
  ('E000001', '2026-08-04T18:00:00Z', 'out'),
  ('E000001', '2026-08-05T08:00:00Z', 'in'),
  ('E000001', '2026-08-05T17:00:00Z', 'out'),
  ('E000001', '2026-08-06T08:00:00Z', 'in'),
  ('E000001', '2026-08-06T17:00:00Z', 'out'),
  ('E000001', '2026-08-07T08:00:00Z', 'in'),
  ('E000001', '2026-08-07T16:00:00Z', 'out'),
  ('E000002', '2026-08-03T08:00:00Z', 'in'),
  ('E000002', '2026-08-03T18:00:00Z', 'out'),
  ('E000002', '2026-08-04T08:00:00Z', 'in'),
  ('E000002', '2026-08-04T18:00:00Z', 'out'),
  ('E000002', '2026-08-05T08:00:00Z', 'in'),
  ('E000002', '2026-08-05T18:00:00Z', 'out'),
  ('E000002', '2026-08-06T08:00:00Z', 'in'),
  ('E000002', '2026-08-06T18:00:00Z', 'out'),
  ('E000002', '2026-08-07T08:00:00Z', 'in'),
  ('E000002', '2026-08-07T18:00:00Z', 'out'),
  ('E000003', '2026-08-03T07:00:00Z', 'in'),
  ('E000003', '2026-08-03T18:00:00Z', 'out'),
  ('E000003', '2026-08-04T07:00:00Z', 'in'),
  ('E000003', '2026-08-04T18:00:00Z', 'out'),
  ('E000003', '2026-08-05T07:00:00Z', 'in'),
  ('E000003', '2026-08-05T18:00:00Z', 'out'),
  ('E000003', '2026-08-06T07:00:00Z', 'in'),
  ('E000003', '2026-08-06T17:00:00Z', 'out'),
  ('E000003', '2026-08-07T07:00:00Z', 'in'),
  ('E000003', '2026-08-07T17:00:00Z', 'out'),
  ('E000004', '2026-08-03T08:00:00Z', 'in'),
  ('E000004', '2026-08-03T16:00:00Z', 'out'),
  ('E000004', '2026-08-04T08:00:00Z', 'in'),
  ('E000004', '2026-08-04T16:00:00Z', 'out'),
  ('E000004', '2026-08-05T08:00:00Z', 'in'),
  ('E000004', '2026-08-05T16:00:00Z', 'out'),
  ('E000004', '2026-08-06T08:00:00Z', 'in'),
  ('E000004', '2026-08-06T16:00:00Z', 'out'),
  ('E000004', '2026-08-07T08:00:00Z', 'in'),
  ('E000004', '2026-08-07T16:00:00Z', 'out'),
  ('E000004', '2026-08-07T19:00:00Z', 'in'),
  ('E000004', '2026-08-07T21:00:00Z', 'out'),
  ('E000005', '2026-08-03T08:00:00Z', 'in'),
  ('E000005', '2026-08-03T16:00:00Z', 'out'),
  ('E000005', '2026-08-04T08:00:00Z', 'in'),
  ('E000005', '2026-08-04T16:00:00Z', 'out'),
  ('E000005', '2026-08-05T08:00:00Z', 'in'),
  ('E000005', '2026-08-05T16:00:00Z', 'out'),
  ('E000005', '2026-08-06T08:00:00Z', 'in'),
  ('E000005', '2026-08-06T16:00:00Z', 'out'),
  ('E000006', '2026-08-03T08:00:00Z', 'in'),
  ('E000006', '2026-08-03T16:00:00Z', 'out'),
  ('E000006', '2026-08-04T08:00:00Z', 'in'),
  ('E000006', '2026-08-04T16:00:00Z', 'out'),
  ('E000006', '2026-08-05T08:00:00Z', 'in'),
  ('E000006', '2026-08-06T08:00:00Z', 'in'),
  ('E000006', '2026-08-06T16:00:00Z', 'out'),
  ('E000006', '2026-08-07T08:00:00Z', 'in'),
  ('E000006', '2026-08-07T16:00:00Z', 'out'),
  ('E000008', '2026-08-03T09:00:00Z', 'in'),
  ('E000008', '2026-08-03T15:00:00Z', 'out'),
  ('E000008', '2026-08-04T09:00:00Z', 'in'),
  ('E000008', '2026-08-04T15:00:00Z', 'out'),
  ('E000008', '2026-08-05T09:00:00Z', 'in'),
  ('E000008', '2026-08-05T15:00:00Z', 'out'),
  ('E000008', '2026-08-06T09:00:00Z', 'in'),
  ('E000008', '2026-08-06T15:00:00Z', 'out'),
  ('E000008', '2026-08-07T09:00:00Z', 'in'),
  ('E000008', '2026-08-07T15:00:00Z', 'out');

INSERT INTO leave_requests(employee_id, start_date, end_date, hours, status) VALUES
  ('E000005', '2026-08-07', '2026-08-07', 8.00, 'approved'),
  ('E000003', '2026-08-08', '2026-08-08', 8.00, 'pending'),
  ('E000002', '2026-08-06', '2026-08-06', 4.00, 'denied');

INSERT INTO attendance_exceptions(employee_id, work_date, code) VALUES
  ('E000005', '2026-08-03', 'late'),
  ('E000008', '2026-08-04', 'early_out');

WITH d(n) AS (
  SELECT 0 UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
  UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9
),
ids AS (
  SELECT (a.n * 10000 + b.n * 1000 + c.n * 100 + e.n * 10 + f.n) AS id
  FROM d a
  JOIN d b
  JOIN d c
  JOIN d e
  JOIN d f
)
INSERT INTO employees(employee_id, status, location_id, hire_date)
SELECT
  printf('E%06d', id),
  CASE id % 7
    WHEN 0 THEN 'active'
    WHEN 1 THEN 'active'
    WHEN 2 THEN 'active'
    WHEN 3 THEN 'leave_of_absence'
    WHEN 4 THEN 'seasonal'
    WHEN 5 THEN 'terminated'
    ELSE 'contractor'
  END,
  printf('LOC-%02d', (id % 12) + 1),
  printf('201%d-%02d-%02d', 4 + (id % 3), 1 + (id % 12), 1 + (id % 27))
FROM ids
WHERE id BETWEEN 9 AND 12000;

WITH d(n) AS (
  SELECT 0 UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
  UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9
),
ids AS (
  SELECT (a.n * 10000 + b.n * 1000 + c.n * 100 + e.n * 10 + f.n) AS id
  FROM d a
  JOIN d b
  JOIN d c
  JOIN d e
  JOIN d f
)
INSERT INTO assignments(
  employee_id, effective_date, end_date, cost_center, department_id,
  flsa_status, leave_plan, hourly_rate_cents, salary_per_period_cents
)
SELECT
  printf('E%06d', id),
  '2024-01-01',
  NULL,
  printf('CC-%02d', (id % 24) + 1),
  printf('DEPT-%02d', (id % 15) + 1),
  CASE WHEN id % 3 = 0 THEN 'exempt' ELSE 'non_exempt' END,
  CASE id % 4 WHEN 0 THEN 'PTO-NE' WHEN 1 THEN 'PTO-EX' WHEN 2 THEN 'PTO-SEA' ELSE 'PTO-LOA' END,
  CASE WHEN id % 3 = 0 THEN NULL ELSE 1200 + (id % 20) * 50 END,
  CASE WHEN id % 3 = 0 THEN 140000 + (id % 25) * 1000 ELSE NULL END
FROM ids
WHERE id BETWEEN 9 AND 12000;

WITH d(n) AS (
  SELECT 0 UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
  UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9
),
ids AS (
  SELECT (a.n * 10000 + b.n * 1000 + c.n * 100 + e.n * 10 + f.n) AS id
  FROM d a
  JOIN d b
  JOIN d c
  JOIN d e
  JOIN d f
),
days(day, out_hour) AS (
  SELECT '2026-08-03', 16 UNION ALL
  SELECT '2026-08-04', 17 UNION ALL
  SELECT '2026-08-05', 16 UNION ALL
  SELECT '2026-08-06', 17 UNION ALL
  SELECT '2026-08-07', 16
)
INSERT INTO punches(employee_id, punched_at, direction)
SELECT printf('E%06d', id), day || 'T08:00:00Z', 'in'
FROM ids
JOIN days
WHERE id BETWEEN 9 AND 12000 AND (id % 7) NOT IN (5)
UNION ALL
SELECT printf('E%06d', id), day || 'T' || printf('%02d', out_hour) || ':00:00Z', 'out'
FROM ids
JOIN days
WHERE id BETWEEN 9 AND 12000 AND (id % 7) NOT IN (5);
