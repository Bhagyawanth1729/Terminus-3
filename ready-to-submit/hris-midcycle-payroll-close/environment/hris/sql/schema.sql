CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    location_id TEXT NOT NULL,
    hire_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY,
    employee_id TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    end_date TEXT,
    cost_center TEXT NOT NULL,
    department_id TEXT NOT NULL,
    flsa_status TEXT NOT NULL,
    leave_plan TEXT NOT NULL,
    hourly_rate_cents INTEGER,
    salary_per_period_cents INTEGER
);

CREATE TABLE IF NOT EXISTS punches (
    id INTEGER PRIMARY KEY,
    employee_id TEXT NOT NULL,
    punched_at TEXT NOT NULL,
    direction TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leave_requests (
    id INTEGER PRIMARY KEY,
    employee_id TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    hours REAL NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attendance_exceptions (
    id INTEGER PRIMARY KEY,
    employee_id TEXT NOT NULL,
    work_date TEXT NOT NULL,
    code TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leave_plans (
    plan_id TEXT PRIMARY KEY,
    accrual_hours_per_period REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS pay_periods (
    period_id TEXT PRIMARY KEY,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    work_days INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS payroll_closes (
    period_id TEXT PRIMARY KEY,
    closed_at TEXT NOT NULL,
    register_digest TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_asg_emp_eff ON assignments(employee_id, effective_date);
CREATE INDEX IF NOT EXISTS idx_punch_emp ON punches(employee_id, punched_at);
