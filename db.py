"""Работа с базой данных (SQLite)."""

import os
import re
import sqlite3

from dotenv import load_dotenv

load_dotenv()

# Путь к файлу базы можно переопределить переменной окружения DB_PATH
DB_PATH = os.getenv("DB_PATH", "clients.db")

# Правила Telegram: 5–32 символа, латиница/цифры/подчёркивание, начинается с буквы
USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{4,31}$")


def normalize_username(text: str) -> str | None:
    """'@Ivan', 'https://t.me/Ivan' -> 'Ivan'. None, если это не @username."""
    name = text.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/", "@"):
        if name.lower().startswith(prefix.lower()):
            name = name[len(prefix):]
            break
    name = name.strip().rstrip("/")
    return name if USERNAME_RE.match(name) else None


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Создаёт файл базы и таблицу клиентов, если их ещё нет."""
    folder = os.path.dirname(os.path.abspath(DB_PATH))
    os.makedirs(folder, exist_ok=True)

    with get_connection() as conn:
        _migrate_old_table(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clients (
                -- @username клиента без @; COLLATE NOCASE + PRIMARY KEY дают
                -- защиту от дублей на уровне БД, включая разный регистр
                username    TEXT PRIMARY KEY COLLATE NOCASE,
                employee_id INTEGER NOT NULL,      -- Telegram ID сотрудника
                added_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_clients_employee ON clients(employee_id)"
        )
        _add_employee_name_column(conn)


def _add_employee_name_column(conn: sqlite3.Connection) -> None:
    """Подпись сотрудника для общей статистики (добавлено позже)."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(clients)")}
    if "employee_name" not in columns:
        conn.execute("ALTER TABLE clients ADD COLUMN employee_name TEXT")


def _migrate_old_table(conn: sqlite3.Connection) -> None:
    """Старая версия хранила числовые client_id. Убираем её, данные не теряем."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='clients'"
    ).fetchone()
    if row is None or "client_id" not in row["sql"]:
        return

    count = conn.execute("SELECT COUNT(*) AS n FROM clients").fetchone()["n"]
    if count:
        conn.execute("ALTER TABLE clients RENAME TO clients_old_ids")
        print(
            f"Старая таблица с числовыми ID сохранена как clients_old_ids "
            f"({count} записей)."
        )
    else:
        conn.execute("DROP TABLE clients")


def add_client(username: str, employee_id: int, employee_name: str = "") -> bool:
    """Добавляет клиента. True — добавлен, False — такой @username уже есть."""
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO clients (username, employee_id, employee_name) "
                "VALUES (?, ?, ?)",
                (username, employee_id, employee_name),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def get_client_owner(username: str) -> int | None:
    """Telegram ID сотрудника, который добавил этого клиента."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT employee_id FROM clients WHERE username = ?", (username,)
        ).fetchone()
    return row["employee_id"] if row else None


def count_clients(employee_id: int) -> int:
    """Счётчик клиентов конкретного сотрудника."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM clients WHERE employee_id = ?", (employee_id,)
        ).fetchone()
    return row["n"]


def get_my_clients(employee_id: int) -> list[sqlite3.Row]:
    """Клиенты сотрудника (сначала новые)."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT username, added_at FROM clients "
            "WHERE employee_id = ? ORDER BY added_at DESC, rowid DESC",
            (employee_id,),
        ).fetchall()


def get_all_clients(limit: int = 100) -> list[sqlite3.Row]:
    """Все клиенты — доступно всем сотрудникам."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT username, employee_id, added_at FROM clients "
            "ORDER BY added_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()


def count_all_clients() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM clients").fetchone()["n"]


def get_employee_stats() -> list[sqlite3.Row]:
    """Сколько клиентов добавил каждый сотрудник (по убыванию)."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT employee_id, MAX(employee_name) AS employee_name, "
            "COUNT(*) AS clients FROM clients "
            "GROUP BY employee_id ORDER BY clients DESC, employee_id"
        ).fetchall()
