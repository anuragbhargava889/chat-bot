import mysql.connector
from mysql.connector import pooling, Error
from datetime import date, datetime
from config import DB_CONFIG

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(pool_name="chatbot_pool", pool_size=5, **DB_CONFIG)
    return _pool


def get_connection():
    return get_pool().get_connection()


def get_product_sales(product_name, month=None, year=None):
    now = datetime.now()
    month = month or now.month
    year = year or now.year

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT p.name,
                   SUM(s.quantity)  AS total_quantity,
                   SUM(s.amount)    AS total_amount,
                   COUNT(s.sale_id) AS total_transactions
            FROM sales s
            JOIN products p ON s.product_id = p.product_id
            WHERE p.name LIKE %s
              AND MONTH(s.sale_date) = %s
              AND YEAR(s.sale_date)  = %s
            GROUP BY p.product_id, p.name
            """,
            (f"%{product_name}%", month, year),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def get_all_products():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT product_id, name, category, price FROM products ORDER BY name")
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def get_employee_by_username(username):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM employees WHERE username = %s", (username,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def mark_attendance(employee_id, action):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    today = date.today()
    try:
        cursor.execute(
            "SELECT * FROM attendance WHERE employee_id = %s AND date = %s",
            (employee_id, today),
        )
        existing = cursor.fetchone()

        if action == "checkin":
            if existing:
                return {"status": "error", "message": "You have already checked in today."}
            cursor.execute(
                "INSERT INTO attendance (employee_id, date, check_in, status) VALUES (%s, %s, NOW(), 'present')",
                (employee_id, today),
            )
            conn.commit()
            return {"status": "success", "message": f"Check-in marked at {datetime.now().strftime('%H:%M:%S')}."}

        elif action == "checkout":
            if not existing:
                return {"status": "error", "message": "You haven't checked in today yet."}
            if existing.get("check_out"):
                return {"status": "error", "message": "You have already checked out today."}
            cursor.execute(
                "UPDATE attendance SET check_out = NOW() WHERE employee_id = %s AND date = %s",
                (employee_id, today),
            )
            conn.commit()
            return {"status": "success", "message": f"Check-out marked at {datetime.now().strftime('%H:%M:%S')}."}

        return {"status": "error", "message": "Unknown attendance action."}
    finally:
        cursor.close()
        conn.close()


def get_attendance_report(employee_id=None):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if employee_id:
            cursor.execute(
                """
                SELECT e.name, e.department,
                       a.date, a.check_in, a.check_out, a.status
                FROM attendance a
                JOIN employees e ON a.employee_id = e.employee_id
                WHERE a.employee_id = %s
                ORDER BY a.date DESC
                LIMIT 30
                """,
                (employee_id,),
            )
        else:
            cursor.execute(
                """
                SELECT e.name, e.department,
                       a.date, a.check_in, a.check_out, a.status
                FROM attendance a
                JOIN employees e ON a.employee_id = e.employee_id
                ORDER BY a.date DESC, e.name
                LIMIT 200
                """
            )
        rows = cursor.fetchall()
        # Convert date/datetime to strings for JSON serialisation
        for row in rows:
            for key, val in row.items():
                if isinstance(val, (date, datetime)):
                    row[key] = str(val)
        return rows
    finally:
        cursor.close()
        conn.close()
