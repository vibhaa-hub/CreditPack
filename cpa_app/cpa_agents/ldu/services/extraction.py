"""document-extraction LDU (DU-02, design D8): structured extraction of uploaded files, wherever
they are stored. CPU-heavy parsing and OCR scale here, apart from the LLM steps that read the result.

  POST /structure {location, filename} -> the structured extraction (cpa_agents.extract.structured):
                                          pages, tables with cell references, iXBRL facts, warnings
  POST /extract   {location, filename} -> {"text": ...} plain text (older callers)

A document is parsed once: the result is cached next to the stored file (`<location>.extract.json`)
and in this process. Unreadable files raise ValueError (over HTTP: 422 with the error), which the
document tools report as unreadable (REQ-083)."""
import hashlib
import json
from collections import OrderedDict
from threading import Lock

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ... import files
from ...extract import structured as S
from ..config import distributed

TEXT_TYPES = S.TEXT_TYPES
SIDECAR = ".extract.json"
_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_LOCK = Lock()
_CACHE_SIZE = 32


def extract_bytes(data: bytes, filename: str) -> str:
    """Plain text of a file (kept for callers that only need text)."""
    return S.plain_text(S.structure(data, filename))


def structure_location(location: str, filename: str | None = None) -> dict:
    """Structured extraction of a stored document, cached (by content hash) in this process and
    beside the file, so a re-uploaded file under the same name is parsed again."""
    data = files.read(location)
    digest = hashlib.sha256(data).hexdigest()
    with _LOCK:
        if digest in _CACHE:
            _CACHE.move_to_end(digest)
            return _CACHE[digest]
    raw = files.read_sidecar(location, SIDECAR)
    result = None
    if raw:
        try:
            cached = json.loads(raw)
            if cached.get("version") == S.EXTRACT_VERSION and cached.get("sha256") == digest:
                result = cached
        except ValueError:
            result = None
    if result is None:
        result = {**S.structure(data, filename or location), "sha256": digest}
        try:
            files.write_sidecar(location, SIDECAR, json.dumps(result, default=str).encode())
        except Exception:                                     # noqa: BLE001  (read-only store: still usable)
            pass
    with _LOCK:
        _CACHE[digest] = result
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return result


def extract_location(location: str, filename: str | None = None) -> str:
    return S.plain_text(structure_location(location, filename))


def structure(location: str, filename: str | None = None) -> dict:
    """Client: the document-extraction LDU's structured result for a stored document."""
    if not distributed():
        return structure_location(location, filename)
    with _LOCK:                       # uploads get a fresh location each time, so the location is a safe key
        if ("loc", location) in _CACHE:
            return _CACHE[("loc", location)]
    from . import client
    r = client("document-extraction").post("/structure", json={"location": location, "filename": filename})
    if r.status_code == 422:
        raise ValueError(r.json().get("error") or "unreadable")
    r.raise_for_status()
    result = r.json()
    with _LOCK:
        _CACHE[("loc", location)] = result
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return result


def extract(location: str, filename: str | None = None) -> str:
    """Client: plain text of a stored document."""
    return S.plain_text(structure(location, filename))


def create_service() -> FastAPI:
    app = FastAPI(title="document-extraction")

    @app.get("/health")
    def health():
        return {"ldu": "document-extraction", "ok": True, "ocr": S._ocr_available()}

    @app.post("/structure")
    def structure_endpoint(body: dict):
        try:
            return structure_location(body["location"], body.get("filename"))
        except Exception as e:                                # corrupt, encrypted, unsupported, missing
            return JSONResponse({"error": str(e)[:500]}, status_code=422)

    @app.post("/extract")
    def extract_endpoint(body: dict):
        try:
            return {"text": extract_location(body["location"], body.get("filename"))}
        except Exception as e:                                # corrupt, encrypted, unsupported, missing
            return JSONResponse({"error": str(e)[:500]}, status_code=422)

    return app
