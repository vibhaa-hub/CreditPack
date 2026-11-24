"""Progressive reading of case documents, shared by the agent LDUs' tool modules (read-only: no state
writes here; the evidence agent's tools record unreadable documents themselves).

Each function returns the tool result dict. Text is labelled untrusted (ARCH-G07)."""
from ..files import location
from ..ldu.services import extraction
from . import structured as S

MAX_CHARS = 20_000


def documents(state) -> list[dict]:
    return [{k: d.get(k) for k in ("doc_id", "filename", "uploaded_by", "uploaded_at")}
            for d in state.get("documents") or []]


def load(state, doc_id: str) -> tuple[dict | None, dict | None, dict | None]:
    """(structure, document, None) or (None, document or None, error result)."""
    d = {x["doc_id"]: x for x in state.get("documents") or []}.get(doc_id)
    if not d:
        return None, None, {"status": "error", "message": f"no document {doc_id}"}
    try:
        struct = extraction.structure(location(d), d.get("filename"))     # document-extraction LDU
    except Exception as e:                                    # noqa: BLE001  corrupt, encrypted, unsupported
        return None, d, {"status": "unreadable", "error": str(e)[:200],
                         "message": f"{d.get('filename')} could not be read ({str(e)[:120]}): "
                                    "request a usable copy (REQ-083)"}
    if not any(p["text"].strip() for p in struct["pages"]) and not struct["tables"]:
        return None, d, {"status": "unreadable", "error": "no text layer",
                         "message": f"{d.get('filename')} has no text (scanned image without OCR?): "
                                    "request a readable copy or a transcription"}
    return struct, d, None


def outline(doc_id: str, struct: dict) -> dict:
    return {"status": "ok", "doc_id": doc_id, **S.outline(struct)}


def find(doc_id: str, struct: dict, query: str) -> dict:
    hits = S.find(struct, query)
    out = {"status": "ok", "doc_id": doc_id, "query": query, "matches": hits}
    if not hits:
        out["note"] = "no matches: try other wording, or read the pages listed by document_outline"
    return out


def pages(doc_id: str, struct: dict, first_page: int, last_page: int | None) -> dict:
    sel = [p for p in struct["pages"]
           if p["n"] >= int(first_page) and (last_page is None or p["n"] <= int(last_page))]
    out, used, next_page = [], 0, None
    for p in sel:
        if used and used + len(p["text"]) > MAX_CHARS:
            next_page = p["n"]
            break
        text = p["text"][:MAX_CHARS - used]
        out.append({"page": p["n"], "method": p["method"], "text": text,
                    **({"page_truncated": True} if len(text) < len(p["text"]) else {})})
        used += len(text)
    return {"status": "ok", "doc_id": doc_id, "untrusted_document_pages": out, "next_page": next_page,
            "pages_in_document": len(struct["pages"])}


def table(doc_id: str, struct: dict, table_id: str, first_row: int | None, max_rows: int) -> dict:
    t = next((t for t in struct["tables"] if t["id"] == str(table_id).upper()), None)
    if t is None:
        return {"status": "error", "message": f"no table {table_id}; tables: {[x['id'] for x in struct['tables']]}"}
    rows = [r for r in t["rows"] if first_row is None or r["row"] >= int(first_row)]
    n = max(1, min(int(max_rows or 60), 200))
    return {"status": "ok", "doc_id": doc_id, "table_id": t["id"], "where": t["where"], "title": t["title"],
            "rows": [{"row": r["row"], "cells": {f"{t['id']}!{t['columns'][i]}{r['row']}": v
                                                 for i, v in enumerate(r["cells"]) if v is not None}}
                     for r in rows[:n]],
            "next_row": rows[n]["row"] if len(rows) > n else None}


def text(doc_id: str, d: dict, struct: dict, offset: int) -> dict:
    full = S.plain_text(struct)
    start = max(0, int(offset or 0))
    more = start + MAX_CHARS < len(full)
    return {"status": "ok", "doc_id": doc_id, "filename": d.get("filename"), "truncated": more,
            "next_offset": start + MAX_CHARS if more else None, "total_chars": len(full),
            "untrusted_document_text": full[start:start + MAX_CHARS]}
