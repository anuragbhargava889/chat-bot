-- ============================================================
--  ChatBot DB schema + sample data
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

-- ── sample data ───────────────────────────────────────────────────────────

-- Passwords are SHA-256 of the plain-text value shown in comments
INSERT INTO employees (username, password, name, email, department, role) VALUES
-- password: admin123
('admin',      SHA2('admin123',     256), 'Administrator', 'admin@company.com',   'Management', 'admin'),
-- password: password123
('john.doe',   SHA2('password123',  256), 'John Doe',      'john@company.com',    'Sales',      'employee'),
('jane.smith', SHA2('password123',  256), 'Jane Smith',    'jane@company.com',    'IT',         'employee'),
('bob.jones',  SHA2('password123',  256), 'Bob Jones',     'bob@company.com',     'Warehouse',  'employee');

INSERT INTO products (name, category, price, description) VALUES
('Laptop Pro',       'Electronics', 999.99,  '15-inch high-performance laptop'),
('Wireless Mouse',   'Electronics',  49.99,  'Ergonomic Bluetooth mouse'),
('Monitor 4K',       'Electronics', 699.99,  '27-inch 4K IPS display'),
('Office Chair',     'Furniture',   299.99,  'Ergonomic adjustable office chair'),
('Standing Desk',    'Furniture',   499.99,  'Height-adjustable standing desk'),
('USB-C Hub',        'Electronics',  79.99,  '7-in-1 USB-C multiport adapter'),
('Mechanical Keyboard','Electronics',129.99, 'Tenkeyless mechanical keyboard');

-- Sales for the current month
INSERT INTO sales (product_id, quantity, amount, sale_date, customer_name) VALUES
(1, 5,  4999.95, CURDATE(),                          'TechCorp Ltd'),
(1, 3,  2999.97, DATE_SUB(CURDATE(), INTERVAL 1 DAY),'StartupXYZ'),
(2, 20, 999.80,  CURDATE(),                          'Office Supplies Co'),
(3, 4,  2799.96, DATE_SUB(CURDATE(), INTERVAL 3 DAY),'MediaStudio'),
(4, 8,  2399.92, DATE_SUB(CURDATE(), INTERVAL 5 DAY),'Corporate HQ'),
(5, 6,  2999.94, DATE_SUB(CURDATE(), INTERVAL 2 DAY),'HomeCorp'),
(6, 15, 1199.85, CURDATE(),                          'Various'),
(7, 10, 1299.90, DATE_SUB(CURDATE(), INTERVAL 4 DAY),'DevTeam Inc');

-- Previous month sales (for trend comparison)
INSERT INTO sales (product_id, quantity, amount, sale_date, customer_name) VALUES
(1, 8,  7999.92, DATE_SUB(CURDATE(), INTERVAL 35 DAY), 'OldClient'),
(2, 30, 1499.70, DATE_SUB(CURDATE(), INTERVAL 40 DAY), 'Various'),
(3, 6,  4199.94, DATE_SUB(CURDATE(), INTERVAL 32 DAY), 'MediaGroup');
