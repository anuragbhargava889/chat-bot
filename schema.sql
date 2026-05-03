-- ============================================================
--  ChatBot DB schema + comprehensive seed data
--  Run: mysql -u root -p < schema.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS chatbot_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE chatbot_db;

-- ── employees ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS employees (
    employee_id INT          AUTO_INCREMENT PRIMARY KEY,
    username    VARCHAR(50)  UNIQUE NOT NULL,
    password    VARCHAR(64)  NOT NULL,          -- SHA-256 hex
    name        VARCHAR(100) NOT NULL,
    email       VARCHAR(100) UNIQUE,
    department  VARCHAR(50),
    role        ENUM('employee','admin') NOT NULL DEFAULT 'employee',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── products ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    product_id  INT           AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100)  NOT NULL,
    category    VARCHAR(50),
    price       DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    description TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── sales ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sales (
    sale_id       INT           AUTO_INCREMENT PRIMARY KEY,
    product_id    INT           NOT NULL,
    quantity      INT           NOT NULL DEFAULT 1,
    amount        DECIMAL(10,2) NOT NULL,
    sale_date     DATE          NOT NULL,
    customer_name VARCHAR(100),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

-- ── attendance ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS attendance (
    attendance_id INT      AUTO_INCREMENT PRIMARY KEY,
    employee_id   INT      NOT NULL,
    date          DATE     NOT NULL,
    check_in      DATETIME,
    check_out     DATETIME,
    status        ENUM('present','absent','late') NOT NULL DEFAULT 'present',
    UNIQUE KEY uq_emp_date (employee_id, date),
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
);

-- ── Employees ─────────────────────────────────────────────────────────────
-- Passwords are SHA-256 of the plain-text value shown in comments

INSERT INTO employees (username, password, name, email, department, role) VALUES
-- password: admin123
('admin',          SHA2('admin123',    256), 'Administrator',  'admin@company.com',   'Management',  'admin'),
-- password: password123
('john.doe',       SHA2('password123', 256), 'John Doe',       'john@company.com',    'Sales',       'employee'),
('jane.smith',     SHA2('password123', 256), 'Jane Smith',     'jane@company.com',    'HR',          'employee'),
('bob.johnson',    SHA2('password123', 256), 'Bob Johnson',    'bob@company.com',     'Sales',       'employee'),
('alice.brown',    SHA2('password123', 256), 'Alice Brown',    'alice@company.com',   'Marketing',   'employee'),
('charlie.davis',  SHA2('password123', 256), 'Charlie Davis',  'charlie@company.com', 'Engineering', 'employee'),
('diana.wilson',   SHA2('password123', 256), 'Diana Wilson',   'diana@company.com',   'Finance',     'employee');

-- ── Products ──────────────────────────────────────────────────────────────

INSERT INTO products (name, category, price, description) VALUES
('Laptop Pro',                 'Electronics',  999.99, '15-inch high-performance laptop with i9 processor'),
('Laptop Air',                 'Electronics',  699.99, '13-inch lightweight laptop, 18-hour battery'),
('Monitor 4K',                 'Electronics',  699.99, '27-inch 4K IPS display, 144Hz'),
('Wireless Mouse',             'Electronics',   49.99, 'Ergonomic Bluetooth mouse, 12-month battery'),
('Mechanical Keyboard',        'Electronics',  129.99, 'Tenkeyless mechanical keyboard, RGB backlit'),
('USB-C Hub',                  'Electronics',   79.99, '7-in-1 USB-C multiport adapter'),
('Webcam HD',                  'Electronics',   89.99, '1080p webcam with built-in noise-cancelling mic'),
('Noise-Cancelling Headphones','Electronics',  249.99, 'Over-ear ANC headphones, 30-hour battery'),
('External SSD 1TB',           'Electronics',  149.99, 'USB-C portable SSD, 1050 MB/s read speed'),
('Office Chair',               'Furniture',    299.99, 'Ergonomic adjustable office chair with lumbar support'),
('Standing Desk',              'Furniture',    499.99, 'Height-adjustable electric standing desk, 160cm'),
('Smart Phone X',              'Electronics',  899.99, 'Latest flagship smartphone, 256GB storage');

-- ── Sales — current month ─────────────────────────────────────────────────

INSERT INTO sales (product_id, quantity, amount, sale_date, customer_name) VALUES
(1,  5,  4999.95, CURDATE(),                           'TechCorp Ltd'),
(1,  3,  2999.97, DATE_SUB(CURDATE(), INTERVAL 1 DAY), 'StartupXYZ'),
(1,  2,  1999.98, DATE_SUB(CURDATE(), INTERVAL 4 DAY), 'Innovate Inc'),
(2,  4,  2799.96, DATE_SUB(CURDATE(), INTERVAL 2 DAY), 'Creative Agency'),
(2,  6,  4199.94, DATE_SUB(CURDATE(), INTERVAL 5 DAY), 'Design Studio'),
(3,  4,  2799.96, DATE_SUB(CURDATE(), INTERVAL 3 DAY), 'MediaStudio'),
(3,  3,  2099.97, DATE_SUB(CURDATE(), INTERVAL 7 DAY), 'Content Co'),
(4,  20,  999.80, CURDATE(),                           'Office Supplies Co'),
(4,  15,  749.85, DATE_SUB(CURDATE(), INTERVAL 6 DAY), 'Bulk Orders Ltd'),
(5,  10, 1299.90, DATE_SUB(CURDATE(), INTERVAL 4 DAY), 'DevTeam Inc'),
(5,  8,  1039.92, DATE_SUB(CURDATE(), INTERVAL 8 DAY), 'Code Factory'),
(6,  15, 1199.85, CURDATE(),                           'Various'),
(6,  12,  959.88, DATE_SUB(CURDATE(), INTERVAL 3 DAY), 'Remote Workers'),
(7,  8,   719.92, DATE_SUB(CURDATE(), INTERVAL 2 DAY), 'HomeOffice Co'),
(7,  10,  899.90, DATE_SUB(CURDATE(), INTERVAL 6 DAY), 'Video Team'),
(8,  5,  1249.95, DATE_SUB(CURDATE(), INTERVAL 1 DAY), 'Executive Suite'),
(8,  3,   749.97, DATE_SUB(CURDATE(), INTERVAL 5 DAY), 'Podcast Studio'),
(9,  10, 1499.90, DATE_SUB(CURDATE(), INTERVAL 3 DAY), 'Data Corp'),
(9,  7,  1049.93, DATE_SUB(CURDATE(), INTERVAL 7 DAY), 'Backup Solutions'),
(10, 8,  2399.92, DATE_SUB(CURDATE(), INTERVAL 5 DAY), 'Corporate HQ'),
(10, 5,  1499.95, DATE_SUB(CURDATE(), INTERVAL 9 DAY), 'New Office Setup'),
(11, 6,  2999.94, DATE_SUB(CURDATE(), INTERVAL 2 DAY), 'HomeCorp'),
(11, 4,  1999.96, DATE_SUB(CURDATE(), INTERVAL 8 DAY), 'Wellness Co'),
(12, 6,  5399.94, DATE_SUB(CURDATE(), INTERVAL 1 DAY), 'Enterprise Mobile'),
(12, 3,  2699.97, DATE_SUB(CURDATE(), INTERVAL 4 DAY), 'Sales Team');

-- ── Sales — previous month ────────────────────────────────────────────────

INSERT INTO sales (product_id, quantity, amount, sale_date, customer_name) VALUES
(1,  8,  7999.92, DATE_SUB(CURDATE(), INTERVAL 35 DAY), 'OldClient Corp'),
(1,  4,  3999.96, DATE_SUB(CURDATE(), INTERVAL 42 DAY), 'Budget Buyers'),
(2,  7,  4899.93, DATE_SUB(CURDATE(), INTERVAL 38 DAY), 'StartupHub'),
(2,  5,  3499.95, DATE_SUB(CURDATE(), INTERVAL 45 DAY), 'Freelancers Co'),
(3,  6,  4199.94, DATE_SUB(CURDATE(), INTERVAL 32 DAY), 'MediaGroup'),
(3,  4,  2799.96, DATE_SUB(CURDATE(), INTERVAL 40 DAY), 'Film Studio'),
(4,  30, 1499.70, DATE_SUB(CURDATE(), INTERVAL 36 DAY), 'Various'),
(4,  25, 1249.75, DATE_SUB(CURDATE(), INTERVAL 44 DAY), 'Bulk Order'),
(5,  12, 1559.88, DATE_SUB(CURDATE(), INTERVAL 33 DAY), 'Coders Guild'),
(8,  8,  1999.92, DATE_SUB(CURDATE(), INTERVAL 37 DAY), 'Executive Team'),
(10, 10, 2999.90, DATE_SUB(CURDATE(), INTERVAL 41 DAY), 'Office Refit'),
(11, 8,  3999.92, DATE_SUB(CURDATE(), INTERVAL 34 DAY), 'Ergonomics Ltd'),
(12, 10, 8999.90, DATE_SUB(CURDATE(), INTERVAL 39 DAY), 'Telecom Partner');

-- ── Sales — two months ago ────────────────────────────────────────────────

INSERT INTO sales (product_id, quantity, amount, sale_date, customer_name) VALUES
(1,  10, 9999.90, DATE_SUB(CURDATE(), INTERVAL 65 DAY), 'Enterprise Inc'),
(1,  6,  5999.94, DATE_SUB(CURDATE(), INTERVAL 72 DAY), 'Tech University'),
(2,  8,  5599.92, DATE_SUB(CURDATE(), INTERVAL 68 DAY), 'Marketing Agency'),
(3,  8,  5599.92, DATE_SUB(CURDATE(), INTERVAL 63 DAY), 'Design Hub'),
(4,  40, 1999.60, DATE_SUB(CURDATE(), INTERVAL 70 DAY), 'Big Box Store'),
(6,  20, 1599.80, DATE_SUB(CURDATE(), INTERVAL 66 DAY), 'Tech Fair'),
(9,  15, 2249.85, DATE_SUB(CURDATE(), INTERVAL 71 DAY), 'Cloud Backup Co'),
(12, 8,  7199.92, DATE_SUB(CURDATE(), INTERVAL 64 DAY), 'Retail Chain');

-- ── Attendance — past 14 days for all employees ───────────────────────────
-- employee_id: 2=john.doe 3=jane.smith 4=bob.johnson
--              5=alice.brown 6=charlie.davis 7=diana.wilson

INSERT INTO attendance (employee_id, date, check_in, check_out, status) VALUES
-- john.doe
(2, DATE_SUB(CURDATE(), INTERVAL 13 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 13 DAY), '08:55:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 13 DAY), '17:30:00'), 'present'),
(2, DATE_SUB(CURDATE(), INTERVAL 12 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 12 DAY), '09:02:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 12 DAY), '17:45:00'), 'present'),
(2, DATE_SUB(CURDATE(), INTERVAL 11 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 11 DAY), '08:50:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 11 DAY), '17:00:00'), 'present'),
(2, DATE_SUB(CURDATE(), INTERVAL 10 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 10 DAY), '09:30:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 10 DAY), '18:00:00'), 'late'),
(2, DATE_SUB(CURDATE(), INTERVAL 9 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 9 DAY),  '08:58:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 9 DAY),  '17:30:00'), 'present'),
(2, DATE_SUB(CURDATE(), INTERVAL 6 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY),  '09:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY),  '17:30:00'), 'present'),
(2, DATE_SUB(CURDATE(), INTERVAL 5 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 5 DAY),  '08:45:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 5 DAY),  '17:15:00'), 'present'),
(2, DATE_SUB(CURDATE(), INTERVAL 4 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 4 DAY),  '09:05:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 4 DAY),  '17:30:00'), 'present'),
(2, DATE_SUB(CURDATE(), INTERVAL 3 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 3 DAY),  '08:55:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 3 DAY),  '17:00:00'), 'present'),
(2, DATE_SUB(CURDATE(), INTERVAL 2 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 2 DAY),  '09:10:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 2 DAY),  '17:45:00'), 'present'),
-- jane.smith
(3, DATE_SUB(CURDATE(), INTERVAL 13 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 13 DAY), '08:30:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 13 DAY), '16:30:00'), 'present'),
(3, DATE_SUB(CURDATE(), INTERVAL 12 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 12 DAY), '08:45:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 12 DAY), '17:00:00'), 'present'),
(3, DATE_SUB(CURDATE(), INTERVAL 11 DAY), NULL, NULL, 'absent'),
(3, DATE_SUB(CURDATE(), INTERVAL 10 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 10 DAY), '08:50:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 10 DAY), '17:30:00'), 'present'),
(3, DATE_SUB(CURDATE(), INTERVAL 9 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 9 DAY),  '09:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 9 DAY),  '17:00:00'), 'present'),
(3, DATE_SUB(CURDATE(), INTERVAL 6 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY),  '08:40:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY),  '16:45:00'), 'present'),
(3, DATE_SUB(CURDATE(), INTERVAL 5 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 5 DAY),  '08:55:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 5 DAY),  '17:30:00'), 'present'),
(3, DATE_SUB(CURDATE(), INTERVAL 4 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 4 DAY),  '09:20:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 4 DAY),  '17:00:00'), 'late'),
(3, DATE_SUB(CURDATE(), INTERVAL 3 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 3 DAY),  '08:35:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 3 DAY),  '17:00:00'), 'present'),
(3, DATE_SUB(CURDATE(), INTERVAL 2 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 2 DAY),  '08:50:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 2 DAY),  '17:15:00'), 'present'),
-- bob.johnson
(4, DATE_SUB(CURDATE(), INTERVAL 13 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 13 DAY), '09:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 13 DAY), '18:00:00'), 'present'),
(4, DATE_SUB(CURDATE(), INTERVAL 12 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 12 DAY), '09:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 12 DAY), '18:15:00'), 'present'),
(4, DATE_SUB(CURDATE(), INTERVAL 11 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 11 DAY), '09:05:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 11 DAY), '17:30:00'), 'present'),
(4, DATE_SUB(CURDATE(), INTERVAL 10 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 10 DAY), '08:55:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 10 DAY), '17:45:00'), 'present'),
(4, DATE_SUB(CURDATE(), INTERVAL 6 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY),  '09:10:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY),  '17:30:00'), 'present'),
(4, DATE_SUB(CURDATE(), INTERVAL 5 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 5 DAY),  '09:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 5 DAY),  '18:00:00'), 'present'),
(4, DATE_SUB(CURDATE(), INTERVAL 4 DAY),  NULL, NULL, 'absent'),
(4, DATE_SUB(CURDATE(), INTERVAL 3 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 3 DAY),  '09:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 3 DAY),  '17:30:00'), 'present'),
(4, DATE_SUB(CURDATE(), INTERVAL 2 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 2 DAY),  '08:50:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 2 DAY),  '17:45:00'), 'present'),
-- alice.brown
(5, DATE_SUB(CURDATE(), INTERVAL 13 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 13 DAY), '08:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 13 DAY), '16:00:00'), 'present'),
(5, DATE_SUB(CURDATE(), INTERVAL 12 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 12 DAY), '08:10:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 12 DAY), '16:30:00'), 'present'),
(5, DATE_SUB(CURDATE(), INTERVAL 11 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 11 DAY), '08:05:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 11 DAY), '16:00:00'), 'present'),
(5, DATE_SUB(CURDATE(), INTERVAL 10 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 10 DAY), '09:45:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 10 DAY), '17:00:00'), 'late'),
(5, DATE_SUB(CURDATE(), INTERVAL 9 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 9 DAY),  '08:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 9 DAY),  '16:15:00'), 'present'),
(5, DATE_SUB(CURDATE(), INTERVAL 6 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY),  '08:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY),  '16:00:00'), 'present'),
(5, DATE_SUB(CURDATE(), INTERVAL 5 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 5 DAY),  '08:15:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 5 DAY),  '16:30:00'), 'present'),
(5, DATE_SUB(CURDATE(), INTERVAL 4 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 4 DAY),  '08:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 4 DAY),  '16:00:00'), 'present'),
(5, DATE_SUB(CURDATE(), INTERVAL 2 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 2 DAY),  '08:05:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 2 DAY),  '16:15:00'), 'present'),
-- charlie.davis
(6, DATE_SUB(CURDATE(), INTERVAL 13 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 13 DAY), '10:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 13 DAY), '19:00:00'), 'present'),
(6, DATE_SUB(CURDATE(), INTERVAL 12 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 12 DAY), '10:05:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 12 DAY), '19:15:00'), 'present'),
(6, DATE_SUB(CURDATE(), INTERVAL 11 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 11 DAY), '09:55:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 11 DAY), '18:45:00'), 'present'),
(6, DATE_SUB(CURDATE(), INTERVAL 10 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 10 DAY), '10:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 10 DAY), '19:30:00'), 'present'),
(6, DATE_SUB(CURDATE(), INTERVAL 9 DAY),  NULL, NULL, 'absent'),
(6, DATE_SUB(CURDATE(), INTERVAL 6 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY),  '10:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY),  '19:00:00'), 'present'),
(6, DATE_SUB(CURDATE(), INTERVAL 5 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 5 DAY),  '10:10:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 5 DAY),  '18:30:00'), 'present'),
(6, DATE_SUB(CURDATE(), INTERVAL 4 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 4 DAY),  '10:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 4 DAY),  '19:00:00'), 'present'),
(6, DATE_SUB(CURDATE(), INTERVAL 3 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 3 DAY),  '09:50:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 3 DAY),  '18:45:00'), 'present'),
(6, DATE_SUB(CURDATE(), INTERVAL 2 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 2 DAY),  '10:00:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 2 DAY),  '19:00:00'), 'present'),
-- diana.wilson
(7, DATE_SUB(CURDATE(), INTERVAL 13 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 13 DAY), '08:30:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 13 DAY), '17:00:00'), 'present'),
(7, DATE_SUB(CURDATE(), INTERVAL 12 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 12 DAY), '08:30:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 12 DAY), '17:15:00'), 'present'),
(7, DATE_SUB(CURDATE(), INTERVAL 11 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 11 DAY), '08:45:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 11 DAY), '17:00:00'), 'present'),
(7, DATE_SUB(CURDATE(), INTERVAL 10 DAY), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 10 DAY), '08:30:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 10 DAY), '17:30:00'), 'present'),
(7, DATE_SUB(CURDATE(), INTERVAL 9 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 9 DAY),  '08:35:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 9 DAY),  '17:00:00'), 'present'),
(7, DATE_SUB(CURDATE(), INTERVAL 6 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY),  '08:30:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY),  '17:00:00'), 'present'),
(7, DATE_SUB(CURDATE(), INTERVAL 5 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 5 DAY),  '08:40:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 5 DAY),  '17:00:00'), 'present'),
(7, DATE_SUB(CURDATE(), INTERVAL 4 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 4 DAY),  '10:30:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 4 DAY),  '17:00:00'), 'late'),
(7, DATE_SUB(CURDATE(), INTERVAL 3 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 3 DAY),  '08:30:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 3 DAY),  '17:00:00'), 'present'),
(7, DATE_SUB(CURDATE(), INTERVAL 2 DAY),  TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 2 DAY),  '08:45:00'), TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 2 DAY),  '17:15:00'), 'present');
