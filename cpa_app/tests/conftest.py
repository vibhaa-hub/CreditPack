"""Shared fixtures. Tests run on a temporary SQLite file by default; set TEST_DATABASE_URL
to a Postgres database to run the same suite there (tables are dropped between tests)."""
import os
from types import SimpleNamespace

import pytest

from cpa_agents import store as store_pkg


@pytest.fixture
def db_url(tmp_path):
    return os.getenv("TEST_DATABASE_URL") or f"sqlite:///{(tmp_path / 'test.db').as_posix()}"


ADK_TABLES = ("events", "sessions", "app_states", "user_states", "adk_internal_metadata")


def _drop_all_pg(url):
    """Postgres test databases are shared between tests: drop store and ADK tables."""
    from sqlalchemy import create_engine, text
    from cpa_agents.store import derive_urls
    from cpa_agents.store.schema import metadata
    eng = create_engine(derive_urls(url)[0])
    with eng.begin() as c:
        for name in [t.name for t in reversed(metadata.sorted_tables)] + list(ADK_TABLES):
            c.execute(text(f"DROP TABLE IF EXISTS {name} CASCADE"))
    eng.dispose()


@pytest.fixture
def store(db_url):
    pg = db_url.startswith("postgresql")
    if pg:
        _drop_all_pg(db_url)
    s = store_pkg.configure(db_url)
    yield s
    s.dispose()
    store_pkg._store = None
    if pg:
        _drop_all_pg(db_url)


def fake_ctx(session_id="sess-1", agent="test_agent", state=None):
    """Stand-in for an ADK ToolContext / callback context: session.id, agent_name and a REAL
    ADK State object (it is not a dict: update() takes a dict, dict(state) fails)."""
    from google.adk.sessions.state import State
    if not isinstance(state, State):
        state = State({} if state is None else state, {})
    return SimpleNamespace(state=state, session=SimpleNamespace(id=session_id), agent_name=agent)


@pytest.fixture
def ctx():
    return fake_ctx()
