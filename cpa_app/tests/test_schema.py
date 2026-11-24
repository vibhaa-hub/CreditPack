import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DatabaseError

from cpa_agents.store.core import Store
from cpa_agents.store.schema import APPEND_ONLY, create_schema


def test_seven_tables_created(store):
    names = set(inspect(store.engine).get_table_names())
    assert {"cases", "audit_events", "pack_versions", "submissions", "section_versions",
            "credit_queries", "state_snapshots"} <= names


def test_create_schema_is_idempotent(store, db_url):
    create_schema(store.engine)          # second run on the same database
    create_schema(store.engine)
    Store(store.engine.url.render_as_string(hide_password=False)).dispose()   # fresh Store, same db


def _seed(store):
    store.append_event("s", "system", "test", "seed")
    store.save_snapshot("s", "a", {"x": 1})
    pv = store.create_pack_version("CASE-1", {"a": 1}, "tester", "seed")
    store.add_section_version("CASE-1", "background", "text", [], "draft", False, "tester")
    return pv


@pytest.mark.parametrize("table", APPEND_ONLY)
@pytest.mark.parametrize("op", ["UPDATE", "DELETE"])
def test_append_only_tables_reject_update_and_delete(store, table, op):
    _seed(store)
    col = {"audit_events": "actor", "pack_versions": "created_by",
           "section_versions": "actor", "state_snapshots": "agent"}[table]
    stmt = f"UPDATE {table} SET {col} = 'tampered'" if op == "UPDATE" else f"DELETE FROM {table}"
    with pytest.raises(DatabaseError, match="append-only"):
        with store.engine.begin() as c:
            c.execute(text(stmt))
    with store.engine.connect() as c:
        assert c.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 1


def test_mutable_tables_still_update(store):
    q = store.record_credit_query("CASE-1", "credit-uw-1", "why?")
    store.assign_credit_query(q, "Jane Smith")
    assert store.credit_queries("CASE-1")[0]["owner"] == "Jane Smith"
