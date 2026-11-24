"""Structured extraction (pages, tables with cell references, iXBRL facts, OCR fallback) and the
progressive reading and recording tools built on it."""
from pathlib import Path

import pytest

from cpa_agents import tools as t
from cpa_agents.extract import ixbrl
from cpa_agents.extract import structured as S
from cpa_agents.ldu.services import extraction
from conftest import fake_ctx

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
ACME = SAMPLES / "01-acme-motors-increase"


@pytest.fixture
def case(store):
    ctx = fake_ctx(session_id="ex-1", agent="document_ingestion")
    t.register_case("Acme Motors Ltd", "01234567", ["increased borrowing request"], "OEM partner", "Jane Smith", ctx)
    t.get_requirement_checklist(ctx)
    return ctx


def attach(ctx, *paths):
    ctx.state["documents"] = [{"doc_id": f"d{i}", "filename": Path(p).name, "path": str(p)}
                              for i, p in enumerate(paths, start=1)]


def test_refs_and_columns():
    assert [S.col_letter(i) for i in (0, 25, 26, 27)] == ["A", "Z", "AA", "AB"]
    assert S.col_index("AB") == 27 and S.parse_ref("t2!c14") == ("T2", 2, 14) and S.parse_ref("B4") is None


def test_xlsx_keeps_sheet_rows_and_cells(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BS"
    ws["A1"], ws["A5"], ws["B5"] = "Balance sheet £000", "Stock", 2500
    wb.create_sheet("PL").append(["Turnover", "15,000"])
    wb.save(tmp_path / "a.xlsx")
    st = S.structure((tmp_path / "a.xlsx").read_bytes(), "a.xlsx")
    assert [x["where"] for x in st["tables"]] == ["sheet BS", "sheet PL"]
    assert S.cell(st, "T1!B5") == 2500 and S.cell(st, "T2!B1") == "15,000"     # Excel's own row numbers
    with pytest.raises(KeyError):
        S.cell(st, "T1!B6")
    o = S.outline(st)
    assert o["likely_locations"]["balance_sheet"] and o["tables"][0]["rows"] == 2


def test_csv_docx_text_and_unsupported(tmp_path):
    import docx
    d = docx.Document()
    d.add_paragraph("Application form")
    tb = d.add_table(rows=2, cols=2)
    tb.cell(0, 0).text, tb.cell(1, 0).text, tb.cell(1, 1).text = "Item", "Turnover", "15,000,000"
    d.save(tmp_path / "f.docx")
    st = S.structure((tmp_path / "f.docx").read_bytes(), "f.docx")
    assert S.cell(st, "T1!B2") == "15,000,000" and "Application form" in st["pages"][0]["text"]
    csvst = S.structure((ACME / "facility_statement.csv").read_bytes(), "facility_statement.csv")
    assert S.cell(csvst, "T1!B3") == "3600000"                       # comment line kept in numbering
    with pytest.raises(ValueError):
        S.structure(b"x", "a.zip")


def test_image_without_ocr_is_unreadable(monkeypatch):
    monkeypatch.setenv("CPA_OCR", "off")
    with pytest.raises(ValueError, match="OCR is not available"):
        S.structure(b"\x89PNG", "scan.png")


def test_ixbrl_sample_parses_without_a_model():
    parsed = ixbrl.parse((ACME / "companies_house_accounts_FY2025.xhtml").read_bytes())
    assert parsed["audit_basis"] == "audited" and parsed["entity_name"] == "ACME MOTORS LIMITED"
    by = {s["period_end"]: s for s in ixbrl.statements(parsed)}
    fy25 = by["2025-12-31"]["figures"]
    assert fy25["current_liabilities"] == 4_000_000 and fy25["cost_of_sales"] == 12_000_000
    assert fy25["opening_stock"] == 2_300_000 and fy25["opening_cash"] == 250_000      # from the prior-year instant
    assert by["2025-12-31"]["refs"]["current_liabilities"] == "ixbrl:Creditors[WithinOneYear]@I25-W1"


def test_ixbrl_scale_sign_and_exemption():
    doc = b"""<html><body>
      <xbrli:context id="C"><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
      <xbrli:unit id="U"><xbrli:measure>iso4217:GBP</xbrli:measure></xbrli:unit>
      <ix:nonNumeric name="uk-direp:StatementThatCompanyEntitledToExemptionFromAudit" contextRef="C">exempt</ix:nonNumeric>
      <ix:nonFraction name="uk-core:ProfitLoss" contextRef="C" unitRef="U" scale="3" sign="-">1,250</ix:nonFraction>
      <ix:nonFraction name="uk-core:TurnoverRevenue" contextRef="C" unitRef="U" format="ixt:fixed-zero">-</ix:nonFraction>
    </body></html>"""
    p = ixbrl.parse(doc)
    s = ixbrl.statements(p)[0]
    assert p["audit_basis"] == "unaudited_accounts" and s["figures"] == {"net_profit": -1_250_000, "turnover": 0}


# ---------- tools ----------
def test_outline_find_read_table_and_record_from_cells(case):
    attach(case, ACME / "accounts_FY2025_audited.xlsx")
    o = t.document_outline("d1", case)
    assert o["status"] == "ok" and o["tables"][0]["id"] == "T1"
    hit = t.find_in_document("d1", "net worth", case)["matches"][0]
    assert hit["cells"] == {"T1!A11": "Net worth", "T1!B11": 3000000}      # Excel's row 11 (row 3 is blank)
    rows = t.read_table("d1", "T1", case, first_row=4, max_rows=3)
    assert [r["row"] for r in rows["rows"]] == [4, 5, 6] and rows["next_row"] == 7     # blank row 3 skipped
    r = t.record_statement_from_cells("d1", "2025-12-31", "audited", "GBP",
                                      ["turnover=T1!B5", "net_worth=T1!B11", "ebit=T1!A8", "bogus=T1!B5", "net_profit=T9!B1"],
                                      case)
    assert r["read"] == {"net_worth": 3_000_000, "turnover": 15_000_000} and len(r["problems"]) == 3
    v = case.state["financial_statement_versions"][0]
    assert v["refs"]["turnover"] == "d1:T1!B5" and v["doc_id"] == "d1"


def test_record_from_cells_scales_thousands(case, tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["Turnover £000", "15,000"])
    wb.active.append(["Loss", "(120)"])
    wb.save(tmp_path / "k.xlsx")
    attach(case, tmp_path / "k.xlsx")
    r = t.record_statement_from_cells("d1", "2025-12-31", "management", "GBP", ["turnover=T1!B1", "net_profit=T1!B2"],
                                      case, units="thousands")
    assert r["read"] == {"turnover": 15_000_000, "net_profit": -120_000}


def test_verify_total_blocks_on_mismatch(case, tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    for row in (["Stock", 2500], ["Debtors", 1200], ["Cash", 400], ["Total current assets", 4200]):
        wb.active.append(row)
    wb.save(tmp_path / "bs.xlsx")
    attach(case, tmp_path / "bs.xlsx")
    r = t.verify_total("d1", "T1", "B", [1, 2, 3], 4, "total current assets", case, period_end="2025-12-31")
    assert r["agrees"] is False and r["difference"] == 100
    assert t.verify_total("d1", "T1", "B", [1, 2], 3, "x", case)["agrees"] is False
    items = t.reconcile_financials(case)["items"]
    assert [i["kind"] for i in items] == ["subtotal", "subtotal"]


def test_import_ixbrl_and_agree_with_spreadsheets(case):
    attach(case, ACME / "companies_house_accounts_FY2025.xhtml", ACME / "accounts_FY2025_audited.xlsx")
    r = t.import_ixbrl_accounts("d1", case)
    assert r["basis"] == "audited" and [x["period_end"] for x in r["recorded"]] == ["2024-12-31", "2025-12-31"]
    t.record_statement_from_cells("d2", "2025-12-31", "audited", "GBP",
                                  ["turnover=T1!B5", "net_profit=T1!B7", "net_worth=T1!B11"], case)
    out = t.reconcile_financials(case)
    assert out["open_blocking"] == 0, out["items"]                   # two audited sources agree
    assert t.import_ixbrl_accounts("d2", case)["status"] == "error"


def test_read_pages_and_document_never_truncate_silently(case, tmp_path):
    (tmp_path / "long.txt").write_text("x" * 45_000, encoding="utf-8")
    attach(case, tmp_path / "long.txt")
    a = t.read_document("d1", case)
    assert a["truncated"] and a["next_offset"] == 20_000 and a["total_chars"] == 45_000
    b = t.read_document("d1", case, offset=a["next_offset"])
    c = t.read_document("d1", case, offset=b["next_offset"])
    assert len(a["untrusted_document_text"] + b["untrusted_document_text"] + c["untrusted_document_text"]) == 45_000
    assert c["next_offset"] is None
    p = t.read_pages("d1", 1, case)
    assert p["untrusted_document_pages"][0].get("page_truncated")


def test_structure_is_cached_beside_the_file(tmp_path):
    from cpa_agents import files
    files.set_file_store(files.LocalFileStore(tmp_path / "uploads"))
    try:
        f = Path(files.get_file_store().put("s1", "c.txt", b"hello"))
        extraction._CACHE.clear()
        first = extraction.structure_location(str(f), "c.txt")
        assert Path(str(f) + ".extract.json").is_file() and first["sha256"]
        extraction._CACHE.clear()
        f.write_text("changed", encoding="utf-8")                    # same name, new content: parsed again
        assert extraction.structure_location(str(f), "c.txt")["pages"][0]["text"] == "changed"
        # a file outside the upload store (e.g. samples/) is cached in memory only
        outside = tmp_path / "sample.txt"
        outside.write_text("sample", encoding="utf-8")
        extraction.structure_location(str(outside), "sample.txt")
        assert not (tmp_path / "sample.txt.extract.json").exists()
    finally:
        files.set_file_store(None)
