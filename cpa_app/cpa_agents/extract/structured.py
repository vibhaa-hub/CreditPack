"""Structured extraction: a document as pages, tables with cell references, and (for iXBRL) tagged
facts. Agents find what they need and read only those parts; figures are recorded by cell
reference so code, not the model, copies the numbers.

Result shape (EXTRACT_VERSION bumps invalidate cached results):
    {"version", "filename", "kind", "method", "pages": [{"n", "text", "method"}],
     "tables": [{"id": "T1", "where": "sheet Accounts" | "page 3" | "document", "title",
                 "columns": ["A", "B", ...], "rows": [{"row": 4, "cells": [...]}]}],
     "ixbrl": {...} | None, "warnings": [...]}

Cell references are "<table id>!<column letter><row number>", e.g. "T1!B12". For spreadsheets the
column and row are the sheet's own, so a person can find the cell in Excel. OCR runs on pages with
no text layer when Tesseract is installed (CPA_OCR=off disables it)."""
import csv
import io
import os
import re
import shutil
from pathlib import Path

EXTRACT_VERSION = 2
TEXT_TYPES = (".txt", ".md", ".eml", ".json")
IXBRL_TYPES = (".xhtml", ".html", ".htm")
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".tif", ".tiff")
MAX_TABLE_ROWS = 5_000                      # per table; larger sheets are cut and a warning added


def col_letter(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


_REF = re.compile(r"^(T\d+)!([A-Z]{1,3})(\d+)$")


def parse_ref(ref: str) -> tuple[str, int, int] | None:
    """'T1!B12' -> ('T1', 1, 12)."""
    m = _REF.match((ref or "").strip().upper())
    return (m.group(1), col_index(m.group(2)), int(m.group(3))) if m else None


def cell(struct: dict, ref: str):
    """The value at a cell reference, or raise KeyError with a reason."""
    p = parse_ref(ref)
    if not p:
        raise KeyError(f"{ref}: not a cell reference like T1!B12")
    tid, c, r = p
    t = next((t for t in struct.get("tables") or [] if t["id"] == tid), None)
    if t is None:
        raise KeyError(f"{ref}: no table {tid}")
    row = next((x for x in t["rows"] if x["row"] == r), None)
    if row is None:
        raise KeyError(f"{ref}: no row {r} in {tid}")
    if c >= len(row["cells"]):
        raise KeyError(f"{ref}: no column {col_letter(c)} in row {r}")
    return row["cells"][c]


def _ocr_available() -> bool:
    if os.getenv("CPA_OCR", "on").lower() in ("off", "0", "false"):
        return False
    try:
        import pytesseract                                     # noqa: F401
    except ImportError:
        return False
    return bool(os.getenv("TESSERACT_CMD") or shutil.which("tesseract"))


def _ocr(image) -> str:
    import pytesseract
    if os.getenv("TESSERACT_CMD"):
        pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
    return pytesseract.image_to_string(image)


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    return s or None


def _table(tid, where, rows: list[tuple[int, list]], warnings) -> dict | None:
    rows = [(n, [_clean(v) for v in cells]) for n, cells in rows]
    rows = [(n, cells) for n, cells in rows if any(v is not None for v in cells)]
    if not rows:
        return None
    if len(rows) > MAX_TABLE_ROWS:
        warnings.append(f"{tid} ({where}) has {len(rows)} rows; only the first {MAX_TABLE_ROWS} are kept")
        rows = rows[:MAX_TABLE_ROWS]
    width = max(len(c) for _, c in rows)
    title = next((str(v) for _, c in rows for v in c if isinstance(v, str)), where)
    return {"id": tid, "where": where, "title": title[:120], "columns": [col_letter(i) for i in range(width)],
            "rows": [{"row": n, "cells": c + [None] * (width - len(c))} for n, c in rows]}


def _table_text(t: dict) -> str:
    return "\n".join("\t".join("" if v is None else str(v) for v in r["cells"]) for r in t["rows"])


def structure(data: bytes, filename: str) -> dict:
    """Structured extraction of one file. Raises ValueError for unsupported or unreadable files."""
    ext = Path(filename).suffix.lower()
    out = {"version": EXTRACT_VERSION, "filename": filename, "kind": ext.lstrip("."), "method": "native",
           "pages": [], "tables": [], "ixbrl": None, "warnings": []}
    w = out["warnings"]
    if ext == ".pdf":
        _pdf(data, out)
    elif ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        for i, ws in enumerate(wb.worksheets, start=1):
            rows = list(enumerate((list(r) for r in ws.iter_rows(min_row=1, values_only=True)), start=1))
            t = _table(f"T{i}", f"sheet {ws.title}", rows, w)
            if t:
                out["tables"].append(t)
                out["pages"].append({"n": i, "text": f"[sheet {ws.title}]\n" + _table_text(t), "method": "native"})
        out["kind"] = "xlsx"
    elif ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        out["pages"].append({"n": 1, "text": "\n".join(p.text for p in d.paragraphs), "method": "native"})
        for i, tb in enumerate(d.tables, start=1):
            t = _table(f"T{i}", "document", [(n, [c.text for c in r.cells]) for n, r in enumerate(tb.rows, start=1)], w)
            if t:
                out["tables"].append(t)
                out["pages"][0]["text"] += f"\n[table T{i}]\n" + _table_text(t)
    elif ext == ".csv":
        text = data.decode("utf-8", errors="replace")
        rows = [(n, r) for n, r in enumerate(csv.reader(io.StringIO(text)), start=1) if r and not r[0].startswith("#")]
        t = _table("T1", "csv", rows, w)
        if t:
            out["tables"].append(t)
        out["pages"].append({"n": 1, "text": text, "method": "native"})
    elif ext in IXBRL_TYPES:
        from . import ixbrl
        parsed = ixbrl.parse(data)
        text = re.sub(r"<[^>]+>", " ", data.decode("utf-8", errors="replace"))
        out["pages"].append({"n": 1, "text": re.sub(r"\s+", " ", text).strip(), "method": "native"})
        if parsed["facts"]:
            out["ixbrl"] = {**parsed, "statements": ixbrl.statements(parsed)}
            out["kind"] = "ixbrl"
        elif ext == ".xhtml":
            w.append("no iXBRL facts found")
    elif ext in IMAGE_TYPES:
        if not _ocr_available():
            raise ValueError("scanned image: OCR is not available on this server (install Tesseract)")
        from PIL import Image
        out["pages"].append({"n": 1, "text": _ocr(Image.open(io.BytesIO(data))), "method": "ocr"})
        out["method"] = "ocr"
        w.append("text read by OCR: verify figures against the image")
    elif ext in TEXT_TYPES:
        out["pages"].append({"n": 1, "text": data.decode("utf-8", errors="replace"), "method": "native"})
    else:
        raise ValueError(f"unsupported document type {ext}")
    return out


def _pdf(data: bytes, out: dict):
    w = out["warnings"]
    try:
        import pdfplumber
    except ImportError:
        pdfplumber = None
    if pdfplumber is None:                                      # text layer only, as before
        from pypdf import PdfReader
        for i, pg in enumerate(PdfReader(io.BytesIO(data)).pages, start=1):
            out["pages"].append({"n": i, "text": (pg.extract_text() or "").strip(), "method": "text"})
        w.append("pdfplumber not installed: tables not extracted")
    else:
        try:
            pdf = pdfplumber.open(io.BytesIO(data))
        except Exception as e:                                  # noqa: BLE001  corrupt or encrypted
            raise ValueError(f"PDF could not be opened: {e}") from e
        ocr = _ocr_available()
        n_tables = 0
        with pdf:
            for i, pg in enumerate(pdf.pages, start=1):
                text, method = (pg.extract_text() or "").strip(), "text"
                if not text and ocr:
                    text, method = _ocr(pg.to_image(resolution=200).original).strip(), "ocr"
                out["pages"].append({"n": i, "text": text, "method": method})
                if method == "text":
                    for tb in pg.extract_tables() or []:
                        n_tables += 1
                        t = _table(f"T{n_tables}", f"page {i}", list(enumerate(tb, start=1)), w)
                        if t:
                            out["tables"].append(t)
    ocr_pages = [p["n"] for p in out["pages"] if p["method"] == "ocr"]
    empty = [p["n"] for p in out["pages"] if not p["text"]]
    if ocr_pages:
        out["method"] = "ocr" if len(ocr_pages) == len(out["pages"]) else "mixed"
        w.append(f"pages {ocr_pages} read by OCR: verify figures against the page image")
    if empty:
        w.append(f"pages {empty} have no text layer" + ("" if _ocr_available() else " and OCR is not available"))


def plain_text(struct: dict) -> str:
    return "\n".join((f"[page {p['n']}] " if struct["kind"] == "pdf" else "") + p["text"] for p in struct["pages"])


# ---------------- finding things ----------------
STATEMENT_HEADINGS = {
    "balance_sheet": ("balance sheet", "statement of financial position", "net assets"),
    "profit_and_loss": ("profit and loss", "income statement", "statement of comprehensive income", "turnover"),
    "cash_flow": ("cash flow", "statement of cash flows"),
    "notes_borrowings": ("bank loans", "borrowings", "creditors: amounts falling due", "stocking"),
}


def outline(struct: dict) -> dict:
    """What is in the document and where the statements probably are."""
    where: dict[str, list[str]] = {}
    for key, words in STATEMENT_HEADINGS.items():
        hits = [f"page {p['n']}" for p in struct["pages"] if any(wd in p["text"].lower() for wd in words)]
        hits += [t["id"] for t in struct["tables"]
                 if any(wd in _table_text(t).lower() for wd in words)]
        if hits:
            where[key] = hits[:8]
    ix = struct.get("ixbrl")
    return {"filename": struct["filename"], "kind": struct["kind"], "method": struct["method"],
            "pages": len(struct["pages"]), "characters": sum(len(p["text"]) for p in struct["pages"]),
            "tables": [{"id": t["id"], "where": t["where"], "title": t["title"], "rows": len(t["rows"]),
                        "columns": len(t["columns"])} for t in struct["tables"]],
            "likely_locations": where,
            "ixbrl": ix and {"facts": len(ix["facts"]), "periods": ix["periods"], "audit_basis": ix["audit_basis"],
                             "entity_name": ix["entity_name"],
                             "statements": [{"period_end": s["period_end"], "fields": sorted(s["figures"])}
                                            for s in ix["statements"]]},
            "warnings": struct["warnings"]}


def find(struct: dict, query: str, limit: int = 20) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return []
    hits = []
    for t in struct["tables"]:
        for r in t["rows"]:
            if any(q in str(v).lower() for v in r["cells"] if v is not None):
                hits.append({"where": f"{t['id']} row {r['row']}", "table_id": t["id"], "row": r["row"],
                             "cells": {f"{t['id']}!{t['columns'][i]}{r['row']}": v
                                       for i, v in enumerate(r["cells"]) if v is not None}})
    for p in struct["pages"]:
        low = p["text"].lower()
        start = 0
        while (i := low.find(q, start)) >= 0 and len(hits) < limit * 2:
            hits.append({"where": f"page {p['n']}", "page": p["n"],
                         "snippet": p["text"][max(0, i - 120): i + len(q) + 160].replace("\n", " ")})
            start = i + len(q)
    return hits[:limit]
