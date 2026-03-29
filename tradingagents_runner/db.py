import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # 保持可运行，不强依赖 python-dotenv
    load_dotenv = None

from psycopg2.pool import SimpleConnectionPool


_POOL: Optional[SimpleConnectionPool] = None
_POOL_LOCK = threading.Lock()


def _load_env_once() -> None:
    """
    读取环境变量。
    优先级：
    1. ENV_FILE_PATH
    2. 项目根目录下 .env
    3. 当前工作目录下 .env
    """
    if load_dotenv is None:
        return

    env_file_path = os.getenv("ENV_FILE_PATH")
    candidates = []

    if env_file_path:
        candidates.append(Path(env_file_path))

    this_file = Path(__file__).resolve()
    repo_root = this_file.parent.parent
    candidates.append(repo_root / ".env")
    candidates.append(Path.cwd() / ".env")

    for path in candidates:
        if path and path.exists():
            load_dotenv(path, override=False)
            break


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def build_db_config() -> Dict[str, Any]:
    _load_env_once()

    return {
        "host": _require_env("DB_HOST"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": _require_env("DB_NAME"),
        "user": _require_env("DB_USER"),
        "password": _require_env("DB_PASSWORD"),
        "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "8")),
        "sslmode": os.getenv("DB_SSLMODE", "prefer"),
        "application_name": os.getenv("DB_APPLICATION_NAME", "tradingagents_runner"),
    }


def build_db_url(mask_password: bool = True) -> str:
    cfg = build_db_config()
    password = "***" if mask_password else cfg["password"]
    return (
        f"postgresql://{cfg['user']}:{password}@{cfg['host']}:"
        f"{cfg['port']}/{cfg['dbname']}"
    )


def init_pool(minconn: Optional[int] = None, maxconn: Optional[int] = None) -> SimpleConnectionPool:
    global _POOL

    with _POOL_LOCK:
        if _POOL is not None:
            return _POOL

        cfg = build_db_config()
        minconn = minconn or int(os.getenv("DB_POOL_MINCONN", "1"))
        maxconn = maxconn or int(os.getenv("DB_POOL_MAXCONN", "5"))

        _POOL = SimpleConnectionPool(
            minconn=minconn,
            maxconn=maxconn,
            **cfg,
        )
        return _POOL


def get_pool() -> SimpleConnectionPool:
    global _POOL
    if _POOL is None:
        return init_pool()
    return _POOL


@contextmanager
def get_conn(autocommit: bool = False) -> Generator:
    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = autocommit
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def close_pool() -> None:
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.closeall()
            _POOL = None


def ping() -> bool:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            row = cur.fetchone()
            return bool(row and row[0] == 1)
