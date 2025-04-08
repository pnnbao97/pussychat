import sqlite3

def init_db():
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        content TEXT,
        source TEXT,
        url TEXT UNIQUE,
        timestamp TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS crypto (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coin TEXT,
        price REAL,
        volume REAL,
        timestamp TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS macro (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        indicator TEXT,
        value TEXT,
        source TEXT,
        timestamp TEXT
    )''')
    conn.commit()
    conn.close()

def get_db_connection():
    return sqlite3.connect("bot_data.db")

# Khởi tạo database khi module được import
init_db()
