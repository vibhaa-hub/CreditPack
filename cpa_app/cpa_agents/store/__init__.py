"""Case store: unique case ids, append-only audit trail, pack/section versions,
Credit queries and state snapshots. One DATABASE_URL drives the store (sync engine)
and ADK sessions (async engine). Postgres is the target; SQLite behaves the same
for tests and local runs.

    from cpa_agents.store import get_store
    store = get_store()            # built from DATABASE_URL (or the SQLite default)
    configure("sqlite:///x.db")    # tests: point the singleton somewhere else
"""
import os
import threading
from pathlib import Path

from sqlalchemy.engine import make_url

DEFAULT_URL = "sqlite:///" + (Path(__file__).resolve().parents[1] / ".adk" / "cpa.db").as_posix()

_lock = threading.Lock()
_store = None


def resolve_url(url: str | None = None) -> str:
    """The configured database URL: explicit argument, else DATABASE_URL, else the SQLite default."""
    return url or os.getenv("DATABASE_URL") or DEFAULT_URL


def derive_urls(url: str | None = None) -> tuple[str, str]:
    """Return (sync_url, async_url) for one configured URL.

    postgresql://...  -> postgresql+psycopg://... (store), postgresql+asyncpg://... (ADK sessions)
    sqlite:///...     -> sqlite:///...            (store), sqlite+aiosqlite:///... (ADK sessions)
    """
    raw = resolve_url(url)
    backend = make_url(raw).get_backend_name()   # validates the URL
    rest = raw.split("://", 1)[1]                # keep path/credentials exactly as given (Windows drive colons)
    drivers = {"postgresql": ("postgresql+psycopg", "postgresql+asyncpg"),
               "sqlite": ("sqlite", "sqlite+aiosqlite")}
    if backend not in drivers:
        raise ValueError(f"unsupported database backend: {backend} (use postgresql or sqlite)")
    sync, asyn = drivers[backend]
    return f"{sync}://{rest}", f"{asyn}://{rest}"


def configure(url: str | None = None):
    """(Re)build the process-wide store for the given URL and return it."""
    global _store
    from .core import Store
    with _lock:
        if _store is not None:
            _store.dispose()
        _store = Store(derive_urls(url)[0])
        return _store


def get_store():
    """The process-wide store, built on first use from the configured URL."""
    if _store is None:
        return configure()
    return _store
