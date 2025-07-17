import sqlite3
import logging
from datetime import datetime, timedelta
import uuid # تأكد من وجود هذا الاستيراد هنا

logger = logging.getLogger(__name__)

DATABASE_NAME = "bot_data.db"

def init_db():
    """Initializes the database by creating necessary tables if they don't exist,
    and adds new columns if they are missing."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Create users table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_activity TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Add last_activity column if it doesn't exist
    try:
        cursor.execute("SELECT last_activity FROM users LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE users ADD COLUMN last_activity TEXT") # لا نحدد قيمة افتراضية هنا
        cursor.execute("UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE last_activity IS NULL") # نحدث الموجودين
        logger.info("Added and initialized 'last_activity' column to 'users' table.")
    
    # Add created_at column if it doesn't exist
    try:
        cursor.execute("SELECT created_at FROM users LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE users ADD COLUMN created_at TEXT") # لا نحدد قيمة افتراضية هنا
        cursor.execute("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL") # نحدث الموجودين
        logger.info("Added and initialized 'created_at' column to 'users' table.")


    # Pending payments table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_payments (
            payment_id TEXT PRIMARY KEY,
            user_id INTEGER,
            username TEXT,
            amount REAL,
            transaction_id TEXT,
            payment_method TEXT,
            status TEXT,
            timestamp TEXT
        )
    """)

    # Purchases history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchases_history (
            purchase_id TEXT PRIMARY KEY,
            user_id INTEGER,
            username TEXT,
            product_name TEXT,
            game_id TEXT,
            price REAL,
            status TEXT,
            timestamp TEXT,
            shipped_at TEXT
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")

async def get_user_wallet_db(user_id: int) -> float:
    """Fetches the user's wallet balance from the database."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return result[0]
    return 0.0

async def update_user_wallet_db(user_id: int, amount: float, username: str = None):
    """Updates the user's wallet balance in the database.
    Also updates last_activity and sets created_at for new users."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    current_time = datetime.now().isoformat()

    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    existing_user = cursor.fetchone()

    if existing_user:
        new_balance = existing_user[0] + amount
        cursor.execute("UPDATE users SET balance = ?, last_activity = ? WHERE user_id = ?", (new_balance, current_time, user_id))
    else:
        new_balance = amount
        if username:
             cursor.execute("INSERT INTO users (user_id, username, balance, created_at, last_activity) VALUES (?, ?, ?, ?, ?)", (user_id, username, new_balance, current_time, current_time))
        else:
             cursor.execute("INSERT INTO users (user_id, balance, created_at, last_activity) VALUES (?, ?, ?, ?)", (user_id, new_balance, current_time, current_time))
    
    conn.commit()
    conn.close()
    logger.info(f"User {user_id} wallet updated. New balance: {new_balance} (Database)")
    return new_balance

async def update_user_activity_db(user_id: int):
    """Updates the last_activity timestamp for a user."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    current_time = datetime.now().isoformat()
    cursor.execute("UPDATE users SET last_activity = ? WHERE user_id = ?", (current_time, user_id))
    conn.commit()
    conn.close()
    logger.debug(f"User {user_id} last activity updated.")


async def add_pending_payment_db(user_id: int, username: str, amount: float, transaction_id: str, payment_method: str = "Unknown"):
    """Adds a pending payment to the database."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    payment_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat() # Use isoformat for consistency
    
    cursor.execute("""
        INSERT INTO pending_payments (payment_id, user_id, username, amount, transaction_id, payment_method, status, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (payment_id, user_id, username, amount, transaction_id, payment_method, "pending", timestamp))
    
    conn.commit()
    conn.close()
    logger.info(f"Pending payment added to DB for user {user_id}: {payment_id} via {payment_method}")
    return payment_id

async def get_pending_payment_db(payment_id: str):
    """Fetches a pending payment by its ID."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pending_payments WHERE payment_id = ?", (payment_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        keys = ["payment_id", "user_id", "username", "amount", "transaction_id", "payment_method", "status", "timestamp"]
        return dict(zip(keys, result))
    return None

async def update_pending_payment_status_db(payment_id: str, status: str):
    """Updates the status of a pending payment."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE pending_payments SET status = ? WHERE payment_id = ?", (status, payment_id))
    conn.commit()
    conn.close()
    logger.info(f"Pending payment {payment_id} status updated to {status}.")

async def add_purchase_history_db(user_id: int, username: str, product_name: str, game_id: str, price: float):
    """Adds a completed purchase to the history."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    purchase_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()

    cursor.execute("""
        INSERT INTO purchases_history (purchase_id, user_id, username, product_name, game_id, price, status, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (purchase_id, user_id, username, product_name, game_id, price, "pending_shipment", timestamp))

    conn.commit()
    conn.close()
    logger.info(f"Purchase added to DB for user {user_id}: {purchase_id}")
    return purchase_id

async def get_user_purchases_history_db(user_id: int):
    """Fetches all purchase history for a given user."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM purchases_history WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
    results = cursor.fetchall()
    conn.close()
    
    history = []
    keys = ["purchase_id", "user_id", "username", "product_name", "game_id", "price", "status", "timestamp", "shipped_at"]
    for row in results:
        history.append(dict(zip(keys, row)))
    return history

async def get_purchase_by_details_db(user_id: int, product_name: str, status: str = 'pending_shipment'):
    """Fetches a specific purchase by user_id, product_name and status."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT purchase_id FROM purchases_history
        WHERE user_id = ? AND product_name = ? AND status = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (user_id, product_name, status))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

async def update_purchase_status_db(purchase_id: str, status: str, shipped_at: str = None):
    """Updates the status of a purchase in the history."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    if shipped_at:
        cursor.execute("UPDATE purchases_history SET status = ?, shipped_at = ? WHERE purchase_id = ?", (status, shipped_at, purchase_id))
    else:
        cursor.execute("UPDATE purchases_history SET status = ? WHERE purchase_id = ?", (status, purchase_id))
    conn.commit()
    conn.close()
    logger.info(f"Purchase {purchase_id} status updated to {status}.")


# --- دوال الإحصائيات الجديدة ---
async def get_total_users_db() -> int:
    """Returns the total number of unique users."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(user_id) FROM users")
    total_users = cursor.fetchone()[0]
    conn.close()
    return total_users

async def get_new_users_today_db() -> int:
    """Returns the number of new users registered today."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    cursor.execute("SELECT COUNT(user_id) FROM users WHERE created_at >= ?", (today_start,))
    new_users = cursor.fetchone()[0]
    conn.close()
    return new_users

async def get_active_users_last_24_hours_db() -> int:
    """Returns the number of users active in the last 24 hours."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    time_24_hours_ago = (datetime.now() - timedelta(hours=24)).isoformat()
    cursor.execute("SELECT COUNT(user_id) FROM users WHERE last_activity >= ?", (time_24_hours_ago,))
    active_users = cursor.fetchone()[0]
    conn.close()
    return active_users

# --- دالة جديدة لجلب جميع معرفات المستخدمين (للبث) ---
async def get_all_user_ids_db() -> list[int]:
    """Returns a list of all user IDs in the database."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    user_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return user_ids