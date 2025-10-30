import sqlite3
from sqlite3 import Cursor
import argparse
from argparse import Action

DB_FILE = 'tasks.db'

def get_db_connection() -> Cursor:
    """Get a connection to the database."""
    conn = sqlite3.connect(DB_FILE)
    return conn.cursor()

def init_db(db_conn: Cursor):
    """Create the database."""
    sql = """CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        due_date TEXT,
        status TEXT NOT NULL DEFAULT 'pending'
    )
    """
    db_conn.execute(sql)

def add_task(db_conn: Cursor, title: str, description: str = None, due_date: str = None):
    """Add a new task to the database."""
    sql = """INSERT INTO tasks (title, description, due_date)
             VALUES (?, ?, ?)"""
    db_conn.execute(sql, (title, description, due_date))
    db_conn.connection.commit()

def get_tasks(db_conn: Cursor):
    sql = "SELECT * FROM tasks"
    db_conn.execute(sql)
    return db_conn.fetchall()
    

def handle_actions(db_conn: Cursor):
    parser = argparse.ArgumentParser(description='Task Management CLI')
    parser.add_argument(
        '-a',
        type=str,
        default=None,
        help="add task"
    )
    parser.add_argument(
        '-l',
        action='store_true',
        help='list tasks'
    )

    args = parser.parse_args()

    if args.a is not None:
        add_task(db_conn, args.a)
        print(f"Task '{args.a}' added.")
    
    if args.l:
        tasks = get_tasks(db_conn)
        for task in tasks:
            print(f"Task {task[0]} title: {task[1]}")


if __name__ == '__main__':
    db_conn = get_db_connection()
    init_db(db_conn)
    handle_actions(db_conn)
    db_conn.close()


