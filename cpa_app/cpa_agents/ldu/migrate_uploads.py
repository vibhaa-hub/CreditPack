"""One-off migration (design D7, migration step 4): copy uploads stored on local disk into the
configured file store, and point each document record at its new URI. Document IDs and SHA-256
hashes do not change; a document whose bytes no longer match its recorded hash is reported and
left alone. Every changed case gets a `documents_migrated` audit event before its state changes.

  CPA_FILE_STORE=s3 CPA_S3_BUCKET=... python -m cpa_agents.ldu.migrate_uploads [--dry-run]
"""
import argparse
import asyncio
import hashlib
from pathlib import Path

from google.adk.events import Event, EventActions
from sqlalchemy import select, update

from .. import files
from ..store import get_store
from ..store.schema import documents

APP, USER = "cpa", "workbench"


def _local(path: str) -> bool:
    return not path.startswith("s3://")


async def migrate(target: files.FileStore, sessions, dry_run: bool = False) -> dict:
    store = get_store()
    with store.engine.connect() as c:
        rows = [dict(r) for r in c.execute(select(documents)).mappings() if _local(r["path"])]
    report = {"moved": [], "skipped": [], "dry_run": dry_run}
    moved: dict[str, dict] = {}                                   # session -> {doc_id: uri}
    for r in rows:
        try:
            data = files.read(r["path"])
        except OSError as e:
            report["skipped"].append({"doc_id": r["doc_id"], "reason": f"unreadable: {e}"})
            continue
        if hashlib.sha256(data).hexdigest() != r["sha256"]:
            report["skipped"].append({"doc_id": r["doc_id"], "reason": "bytes do not match the recorded sha256"})
            continue
        if dry_run:
            report["moved"].append({"doc_id": r["doc_id"], "from": r["path"], "to": None})
            continue
        uri = target.put(r["session_id"], Path(r["path"]).name, data)
        if hashlib.sha256(target.get(uri)).hexdigest() != r["sha256"]:
            report["skipped"].append({"doc_id": r["doc_id"], "reason": "copy did not verify"})
            continue
        with store.engine.begin() as c:
            c.execute(update(documents).where(documents.c.doc_id == r["doc_id"]).values(path=uri))
        moved.setdefault(r["session_id"], {})[r["doc_id"]] = uri
        report["moved"].append({"doc_id": r["doc_id"], "from": r["path"], "to": uri})

    for sid, uris in moved.items():
        session = await sessions.get_session(app_name=APP, user_id=USER, session_id=sid)
        if session is None:
            continue
        docs = [({**d, "path": uris[d["doc_id"]], "uri": uris[d["doc_id"]]} if d.get("doc_id") in uris else d)
                for d in session.state.get("documents") or []]
        case_id = session.state.get("case_id") or store.case_for_session(sid)
        store.append_event(sid, "system", "migration", "documents_migrated", case_id=case_id,
                           detail={"documents": uris})             # audit first, then apply
        await sessions.append_event(session, Event(author="migration",
                                                   actions=EventActions(state_delta={"documents": docs})))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    from ..store.runtime import make_session_service
    target = files.get_file_store()
    if isinstance(target, files.LocalFileStore):
        raise SystemExit("CPA_FILE_STORE is local: set CPA_FILE_STORE=s3 (and CPA_S3_BUCKET) to migrate")
    report = asyncio.run(migrate(target, make_session_service(), dry_run=args.dry_run))
    print(f"moved {len(report['moved'])}, skipped {len(report['skipped'])}" + (" (dry run)" if args.dry_run else ""))
    for s in report["skipped"]:
        print(f"  skipped {s['doc_id']}: {s['reason']}")


if __name__ == "__main__":
    main()
