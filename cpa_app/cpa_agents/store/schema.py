"""Tables for the case store (design decision 3) and the append-only triggers (decision 4)."""
from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, MetaData, String,
                        Table, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
Json = JSON().with_variant(JSONB(), "postgresql")
TS = DateTime(timezone=True)

cases = Table(
    "cases", metadata,
    Column("case_seq", Integer, primary_key=True, autoincrement=True),
    Column("case_id", String(40), nullable=False, unique=True),
    Column("session_id", String(128), nullable=False, index=True),
    Column("dealer_name", String(300)),
    Column("registered_number", String(40)),
    Column("case_types", Json),
    Column("source", String(60)),
    Column("owner", String(200)),
    Column("received_at", TS, nullable=False),
)

audit_events = Table(
    "audit_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(128), nullable=False),
    Column("case_id", String(40), index=True),
    Column("seq", Integer, nullable=False),
    Column("at", TS, nullable=False),
    Column("actor_type", String(10), nullable=False),   # agent | human | system
    Column("actor", String(200), nullable=False),
    Column("action", String(40), nullable=False),      # tool_called | tool_result | agent_complete | human_decision ...
    Column("tool", String(100)),
    Column("args", Json),
    Column("result_status", String(40)),
    Column("detail", Json),
    Column("prev_hash", String(64), nullable=False),
    Column("hash", String(64), nullable=False),
    UniqueConstraint("session_id", "seq", name="uq_audit_session_seq"),
)

pack_versions = Table(
    "pack_versions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", String(40), nullable=False, index=True),
    Column("version", Integer, nullable=False),
    Column("content", Json, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("created_at", TS, nullable=False),
    Column("created_by", String(200), nullable=False),
    Column("reason", String(300)),
    UniqueConstraint("case_id", "version", name="uq_pack_case_version"),
)

submissions = Table(
    "submissions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", String(40), nullable=False, index=True),
    Column("pack_version_id", Integer, ForeignKey("pack_versions.id"), nullable=False),
    Column("authorised_by", String(200), nullable=False),
    Column("submitted_at", TS, nullable=False),
    Column("receipt_ref", String(200)),
)

section_versions = Table(
    "section_versions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", String(40), nullable=False, index=True),
    Column("section", String(120), nullable=False),
    Column("version", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("evidence", Json),
    Column("label", String(60)),
    Column("reviewed", Boolean, nullable=False, default=False),
    Column("actor", String(200), nullable=False),
    Column("created_at", TS, nullable=False),
    UniqueConstraint("case_id", "section", "version", name="uq_section_version"),
)

credit_queries = Table(
    "credit_queries", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", String(40), nullable=False, index=True),
    Column("raised_at", TS, nullable=False),
    Column("raised_by", String(200), nullable=False),
    Column("text", Text, nullable=False),
    Column("owner", String(200)),
    Column("status", String(20), nullable=False, default="open"),   # open | resolved
    Column("resolved_at", TS),
    Column("resolution", Text),
    Column("pack_version_id", Integer, ForeignKey("pack_versions.id")),
)

state_snapshots = Table(
    "state_snapshots", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(128), nullable=False, index=True),
    Column("case_id", String(40)),
    Column("agent", String(120), nullable=False),
    Column("at", TS, nullable=False),
    Column("state", Json, nullable=False),
)

users = Table(
    "users", metadata,
    Column("username", String(80), primary_key=True),
    Column("display_name", String(200), nullable=False),
    Column("roles", Json, nullable=False),          # list of role names (workbench.permissions.ROLES)
    Column("password_hash", String(400), nullable=False),
    Column("active", Boolean, nullable=False, default=True),
    Column("created_at", TS, nullable=False),
)

documents = Table(
    "documents", metadata,
    Column("doc_id", String(40), primary_key=True),
    Column("case_id", String(40), index=True),
    Column("session_id", String(128), nullable=False, index=True),
    Column("filename", String(300), nullable=False),
    Column("path", String(600), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("size", Integer, nullable=False),
    Column("content_type", String(120)),
    Column("uploaded_by", String(200), nullable=False),
    Column("uploaded_at", TS, nullable=False),
)

# Workflow runs (split-into-least-deployable-units, design D6). Mutable working table: one row per
# run, heartbeated by the orchestrator. The partial unique index allows one active run per case
# across every web and orchestrator replica.
ACTIVE_RUN_STATES = ("queued", "running")
runs = Table(
    "runs", metadata,
    Column("run_id", String(40), primary_key=True),
    Column("session_id", String(128), nullable=False, index=True),
    Column("workflow", String(40), nullable=False),
    Column("state", String(20), nullable=False),          # queued | running | finished | failed | interrupted
    Column("started_by", String(200)),
    Column("started_at", TS, nullable=False),
    Column("finished_at", TS),
    Column("heartbeat_at", Float, nullable=False),        # epoch seconds
    Column("orchestrator", String(200)),
    Column("pending", Json),                              # {agent: ldu} steps dispatched, not finished
    Column("completed", Json),                            # agents finished, in order
    Column("error", Text),
    Column("failed_step", String(80)),
    Column("input", Text),                                # the message the run starts with
    Index("one_active_run_per_case", "session_id", unique=True,
          postgresql_where=text("state IN ('queued', 'running')"),
          sqlite_where=text("state IN ('queued', 'running')")),
)

# Step jobs (design D3): the distributed queue between case-orchestrator and the agent LDUs.
# Mutable working table; workers claim rows with SELECT ... FOR UPDATE SKIP LOCKED.
step_jobs = Table(
    "step_jobs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(40), nullable=False),
    Column("case_id", String(128), nullable=False),
    Column("ldu", String(80), nullable=False),
    Column("agent", String(80), nullable=False),
    Column("payload", JSON, nullable=False),                # JSON, not JSONB: keeps key order exactly
    Column("state", String(20), nullable=False),          # queued | claimed | done | failed
    Column("attempts", Integer, nullable=False, default=0),
    Column("claimed_by", String(200)),
    Column("claimed_at", Float),
    Column("heartbeat_at", Float),
    Column("result", JSON),
    Column("error", Text),
    Column("enqueued_at", Float, nullable=False),
    Index("step_jobs_ldu_state", "ldu", "state", "id"),
)

# LDU process registry (distributed mode): every LDU process heartbeats its row, so status can
# say which LDU a run is waiting for when none of its replicas is alive.
ldu_workers = Table(
    "ldu_workers", metadata,
    Column("worker_id", String(200), primary_key=True),
    Column("ldu", String(80), nullable=False, index=True),
    Column("version", String(40)),
    Column("started_at", Float, nullable=False),
    Column("heartbeat_at", Float, nullable=False),
)

APPEND_ONLY = ("audit_events", "pack_versions", "section_versions", "state_snapshots")

_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION cpa_block_change() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'append-only table %: % is not allowed', TG_TABLE_NAME, TG_OP;
END; $$ LANGUAGE plpgsql
"""


def _trigger_ddl(dialect: str) -> list[str]:
    stmts = []
    if dialect == "postgresql":
        stmts.append(_PG_FUNCTION)
        for t in APPEND_ONLY:
            stmts.append(f"CREATE OR REPLACE TRIGGER {t}_no_change BEFORE UPDATE OR DELETE ON {t} "
                         f"FOR EACH ROW EXECUTE FUNCTION cpa_block_change()")
            stmts.append(f"CREATE OR REPLACE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON {t} "
                         f"FOR EACH STATEMENT EXECUTE FUNCTION cpa_block_change()")
    elif dialect == "sqlite":
        for t in APPEND_ONLY:
            for op in ("UPDATE", "DELETE"):
                stmts.append(f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                             f"BEGIN SELECT RAISE(ABORT, 'append-only table {t}: {op} is not allowed'); END")
    else:
        raise ValueError(f"no append-only triggers for dialect {dialect}")
    return stmts


def _pg_triggers_present(conn) -> bool:
    names = [f"{t}_no_change" for t in APPEND_ONLY] + [f"{t}_no_truncate" for t in APPEND_ONLY]
    n = conn.execute(text("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname = ANY(:n)"),
                     {"n": names}).scalar()
    return n == len(names)


def create_schema(engine) -> None:
    """Create tables and triggers if missing. Safe to call on every start-up.

    On Postgres, triggers that already exist are left alone, so the restricted application
    role (which does not own the tables and cannot create triggers) can start the store
    once an admin has created the schema."""
    metadata.create_all(engine)
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql" and _pg_triggers_present(conn):
            return
        for stmt in _trigger_ddl(engine.dialect.name):
            conn.execute(text(stmt))
