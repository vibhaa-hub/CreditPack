"""Store: the evidence layer behind the agents (design decisions 2-10).

Session state stays the agents' working copy. The store records what state cannot
guarantee: unique case ids, an append-only hash-chained audit trail, immutable pack and
section versions, Credit queries and per-step state snapshots.
"""
import difflib
import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, create_engine, func, or_, select, text

from .schema import (audit_events, cases, create_schema, credit_queries, pack_versions, section_versions,
                     state_snapshots, submissions)

GENESIS = "0" * 64
CASE_CHANNEL, STEP_CHANNEL = "cpa_cases", "cpa_steps"      # Postgres NOTIFY channels (LDU design D3/D6)


def notify(conn, channel: str, payload: str):
    """Postgres NOTIFY inside the caller's transaction (delivered on commit). No-op elsewhere."""
    if conn.dialect.name == "postgresql":
        conn.execute(text("SELECT pg_notify(:c, :p)"), {"c": channel, "p": str(payload)[:7000]})


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """Stable UTC ISO form; SQLite hands timestamps back naive, Postgres aware."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def jsonable(obj):
    """Round-trip through JSON so what we hash is exactly what the database stores."""
    return json.loads(json.dumps(obj, default=str))


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def event_hash(prev_hash: str, ev: dict) -> str:
    body = {k: ev.get(k) for k in ("session_id", "case_id", "seq", "at", "actor_type", "actor", "action",
                                   "tool", "args", "result_status", "detail")}
    return sha256(prev_hash + canonical(body))


class Store:
    def __init__(self, sync_url: str):
        kwargs = {}
        if sync_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        else:
            kwargs["pool_pre_ping"] = True
        self.engine = create_engine(sync_url, **kwargs)
        self.dialect = self.engine.dialect.name
        self._append_lock = threading.Lock()
        create_schema(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()

    # ---------- cases (REQ-001) ----------
    def create_case(self, session_id: str, dealer_name: str, registered_number: str, case_types: list,
                    source: str, owner: str) -> dict:
        received = now()
        with self.engine.begin() as c:
            seq = c.execute(cases.insert().values(
                case_id=f"PENDING-{uuid.uuid4().hex}", session_id=session_id, dealer_name=dealer_name,
                registered_number=registered_number, case_types=jsonable(case_types), source=source,
                owner=owner, received_at=received)).inserted_primary_key[0]
            case_id = f"CASE-{received:%Y%m%d}-{seq:06d}"
            c.execute(cases.update().where(cases.c.case_seq == seq).values(case_id=case_id))
        return {"case_id": case_id, "received_at": iso(received)}

    def get_case(self, case_id: str) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(select(cases).where(cases.c.case_id == case_id)).mappings().first()
        return dict(r) if r else None

    def cases_for_dealer(self, registered_number: str | None, dealer_name: str | None) -> list[dict]:
        """Every case for the same dealer (registered number, else exact name), newest first (REQ-006)."""
        cond = []
        if registered_number:
            cond.append(cases.c.registered_number == registered_number)
        if dealer_name:
            cond.append(func.lower(cases.c.dealer_name) == dealer_name.lower())
        if not cond:
            return []
        with self.engine.connect() as c:
            rows = c.execute(select(cases).where(or_(*cond)).order_by(cases.c.case_seq.desc())).mappings().all()
        return [{**dict(r), "received_at": iso(r["received_at"])} for r in rows]

    def case_for_session(self, session_id: str) -> str | None:
        with self.engine.connect() as c:
            return c.execute(select(cases.c.case_id).where(cases.c.session_id == session_id)
                             .order_by(cases.c.case_seq.desc())).scalar()

    # ---------- audit trail (REQ-085, BR-G02, ARCH-G09) ----------
    def append_event(self, session_id: str, actor_type: str, actor: str, action: str, *,
                     case_id: str | None = None, tool: str | None = None, args=None,
                     result_status: str | None = None, detail=None) -> dict:
        """Append one hash-chained audit event. Appends per session are serialised."""
        with self._append_lock, self.engine.begin() as c:
            if self.dialect == "postgresql":
                c.execute(text("SELECT pg_advisory_xact_lock(hashtext(:s))"), {"s": session_id})
            last = c.execute(select(audit_events.c.seq, audit_events.c.hash)
                             .where(audit_events.c.session_id == session_id)
                             .order_by(audit_events.c.seq.desc()).limit(1)).first()
            seq, prev = (last.seq + 1, last.hash) if last else (1, GENESIS)
            if case_id is None:
                case_id = c.execute(select(cases.c.case_id).where(cases.c.session_id == session_id)
                                    .order_by(cases.c.case_seq.desc())).scalar()
            at = now()
            ev = dict(session_id=session_id, case_id=case_id, seq=seq, at=iso(at), actor_type=actor_type,
                      actor=actor, action=action, tool=tool, args=jsonable(args),
                      result_status=result_status, detail=jsonable(detail))
            h = event_hash(prev, ev)
            c.execute(audit_events.insert().values(**{**ev, "at": at}, prev_hash=prev, hash=h))
            notify(c, CASE_CHANNEL, session_id)                       # live case pages (SSE)
        return {**ev, "prev_hash": prev, "hash": h}

    def events(self, key: str) -> list[dict]:
        """All audit events for a session id or a case id (including its session's
        events from before the case id existed), in order."""
        sessions = select(cases.c.session_id).where(cases.c.case_id == key)
        q = (select(audit_events)
             .where(or_(audit_events.c.session_id == key, audit_events.c.case_id == key,
                        audit_events.c.session_id.in_(sessions)))
             .order_by(audit_events.c.at, audit_events.c.id))
        with self.engine.connect() as c:
            rows = c.execute(q).mappings().all()
        return [{**dict(r), "at": iso(r["at"])} for r in rows]

    def verify_chain(self, session_id: str, rows: list[dict] | None = None) -> dict:
        """Recompute the session's hash chain. Returns ok, event count and the first broken seq."""
        if rows is None:
            with self.engine.connect() as c:
                rows = [dict(r) for r in c.execute(select(audit_events)
                                                   .where(audit_events.c.session_id == session_id)
                                                   .order_by(audit_events.c.seq)).mappings()]
        prev = GENESIS
        for i, r in enumerate(rows, start=1):
            ev = {**r, "at": iso(r["at"]) if isinstance(r["at"], datetime) else r["at"]}
            if r["seq"] != i or r["prev_hash"] != prev or event_hash(prev, ev) != r["hash"]:
                return {"ok": False, "events": len(rows), "broken_at": r["seq"]}
            prev = r["hash"]
        return {"ok": True, "events": len(rows), "broken_at": None}

    # ---------- state snapshots (ARCH-G06) ----------
    def save_snapshot(self, session_id: str, agent: str, state: dict, case_id: str | None = None) -> int:
        case_id = case_id or self.case_for_session(session_id)
        with self.engine.begin() as c:
            return c.execute(state_snapshots.insert().values(
                session_id=session_id, case_id=case_id, agent=agent,
                at=now(), state=jsonable(state))).inserted_primary_key[0]

    def snapshots(self, session_id: str) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(state_snapshots.c.id, state_snapshots.c.agent, state_snapshots.c.at)
                             .where(state_snapshots.c.session_id == session_id)
                             .order_by(state_snapshots.c.id)).mappings().all()
        return [{**dict(r), "at": iso(r["at"])} for r in rows]

    def get_snapshot(self, session_id: str, snapshot_id: int | None = None,
                     at_or_before: datetime | None = None) -> dict | None:
        """A specific snapshot, or the latest one at or before a time, or the latest overall."""
        q = select(state_snapshots).where(state_snapshots.c.session_id == session_id)
        if snapshot_id is not None:
            q = q.where(state_snapshots.c.id == snapshot_id)
        if at_or_before is not None:
            q = q.where(state_snapshots.c.at <= at_or_before)
        with self.engine.connect() as c:
            r = c.execute(q.order_by(state_snapshots.c.id.desc()).limit(1)).mappings().first()
        return {**dict(r), "at": iso(r["at"])} if r else None

    # ---------- pack versions and submissions (REQ-064, BR-P05) ----------
    def create_pack_version(self, case_id: str, content: dict, created_by: str, reason: str) -> dict:
        content = jsonable(content)
        digest = sha256(canonical(content))
        with self._append_lock, self.engine.begin() as c:
            v = (c.execute(select(func.max(pack_versions.c.version))
                           .where(pack_versions.c.case_id == case_id)).scalar() or 0) + 1
            pid = c.execute(pack_versions.insert().values(
                case_id=case_id, version=v, content=content, sha256=digest, created_at=now(),
                created_by=created_by, reason=reason)).inserted_primary_key[0]
        return {"id": pid, "version": v, "sha256": digest}

    def pack_versions(self, case_id: str) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(pack_versions).where(pack_versions.c.case_id == case_id)
                             .order_by(pack_versions.c.version)).mappings().all()
        return [dict(r) for r in rows]

    def record_submission(self, case_id: str, pack_version_id: int, authorised_by: str,
                          receipt_ref: str) -> int:
        with self.engine.begin() as c:
            return c.execute(submissions.insert().values(
                case_id=case_id, pack_version_id=pack_version_id, authorised_by=authorised_by,
                submitted_at=now(), receipt_ref=receipt_ref)).inserted_primary_key[0]

    # ---------- section versions (REQ-054) ----------
    def add_section_version(self, case_id: str, section: str, text_: str, evidence, label: str,
                            reviewed: bool, actor: str) -> int:
        with self._append_lock, self.engine.begin() as c:
            v = (c.execute(select(func.max(section_versions.c.version))
                           .where(and_(section_versions.c.case_id == case_id,
                                       section_versions.c.section == section))).scalar() or 0) + 1
            c.execute(section_versions.insert().values(
                case_id=case_id, section=section, version=v, text=text_, evidence=jsonable(evidence),
                label=label, reviewed=bool(reviewed), actor=actor, created_at=now()))
        return v

    def section_versions(self, case_id: str, section: str) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(section_versions)
                             .where(and_(section_versions.c.case_id == case_id,
                                         section_versions.c.section == section))
                             .order_by(section_versions.c.version)).mappings().all()
        return [dict(r) for r in rows]

    def section_diff(self, case_id: str, section: str, v1: int, v2: int) -> str:
        by_v = {r["version"]: r for r in self.section_versions(case_id, section)}
        a, b = by_v[v1], by_v[v2]

        def lines(r):
            return (r["text"].splitlines(keepends=True)
                    + [f"\n[evidence: {', '.join(r['evidence'] or [])}] [reviewed: {r['reviewed']}]\n"])
        return "".join(difflib.unified_diff(lines(a), lines(b), f"{section} v{v1}", f"{section} v{v2}"))

    # ---------- Credit queries (REQ-065, BR-P13) ----------
    def record_credit_query(self, case_id: str, raised_by: str, text_: str, owner: str | None = None) -> int:
        with self.engine.begin() as c:
            return c.execute(credit_queries.insert().values(
                case_id=case_id, raised_at=now(), raised_by=raised_by, text=text_, owner=owner,
                status="open")).inserted_primary_key[0]

    def assign_credit_query(self, query_id: int, owner: str) -> None:
        with self.engine.begin() as c:
            c.execute(credit_queries.update().where(credit_queries.c.id == query_id).values(owner=owner))

    def resolve_credit_query(self, query_id: int, resolution: str, actor: str, pack_changed: bool,
                             new_content: dict | None = None) -> dict:
        """Resolve a query. A pack-changing resolution needs the new pack content and creates
        a new pack version linked to the query."""
        with self.engine.connect() as c:
            q = c.execute(select(credit_queries).where(credit_queries.c.id == query_id)).mappings().first()
        if q is None:
            raise KeyError(f"no credit query {query_id}")
        if q["status"] == "resolved":
            raise ValueError(f"credit query {query_id} is already resolved")
        pv = None
        if pack_changed:
            if new_content is None:
                raise ValueError("a pack-changing resolution needs the new pack content")
            pv = self.create_pack_version(q["case_id"], new_content, actor,
                                          f"response to credit query {query_id}")
        with self.engine.begin() as c:
            c.execute(credit_queries.update().where(credit_queries.c.id == query_id).values(
                status="resolved", resolved_at=now(), resolution=resolution,
                pack_version_id=pv["id"] if pv else None))
        return {"query_id": query_id, "status": "resolved", "pack_version": pv}

    def credit_queries(self, case_id: str, status: str | None = None) -> list[dict]:
        q = select(credit_queries).where(credit_queries.c.case_id == case_id)
        if status:
            q = q.where(credit_queries.c.status == status)
        with self.engine.connect() as c:
            rows = c.execute(q.order_by(credit_queries.c.id)).mappings().all()
        return [{k: (iso(v) if isinstance(v, datetime) else v) for k, v in dict(r).items()} for r in rows]
