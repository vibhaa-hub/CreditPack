from cpa_agents.store import DEFAULT_URL, derive_urls


def test_postgres_url_derives_psycopg_and_asyncpg():
    sync, asyn = derive_urls("postgresql://u:p@db:5432/cpa")
    assert sync == "postgresql+psycopg://u:p@db:5432/cpa"
    assert asyn == "postgresql+asyncpg://u:p@db:5432/cpa"


def test_postgres_url_with_driver_is_normalised():
    sync, asyn = derive_urls("postgresql+psycopg2://u:p@db/cpa")
    assert sync.startswith("postgresql+psycopg://") and asyn.startswith("postgresql+asyncpg://")


def test_sqlite_url_derives_aiosqlite():
    assert derive_urls("sqlite:///data/cpa.db") == ("sqlite:///data/cpa.db", "sqlite+aiosqlite:///data/cpa.db")


def test_unset_variable_uses_sqlite_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sync, asyn = derive_urls()
    assert sync == DEFAULT_URL and DEFAULT_URL.endswith("/.adk/cpa.db")
    assert asyn.startswith("sqlite+aiosqlite:///")


def test_database_url_variable_is_used(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x@h/d")
    assert derive_urls()[0] == "postgresql+psycopg://x@h/d"


def test_unsupported_backend_rejected():
    import pytest
    with pytest.raises(ValueError):
        derive_urls("mysql://u@h/d")
