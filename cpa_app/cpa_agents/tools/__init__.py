"""Agent tools, one module per Arch 3.2 specialist. External systems (Companies House, bureaux,
screening, Credit) are STUBS backed by cpa_agents/stubs/*.json. Human decisions are never made
here: gate tools only create pending requests; people act through the case store runtime."""
from .assembly import (list_credit_queries, record_lending_request, request_pricing_authorisation,
                       request_submission_authorisation, run_completeness_gate, transmit_pack)
from .bureau import assess_staleness, credit_reference_lookup, lookup_held_data
from .diligence import (adverse_media_search, check_register, record_check_result, request_hit_disposition,
                        sanctions_screen)
from .documents import (document_outline, extract_text, find_in_document, import_ixbrl_accounts, list_case_documents,
                        list_info_gaps, read_document, read_pages, read_table, record_financial_statement,
                        record_info_item, record_info_request, record_note, record_statement_from_cells,
                        verify_total)
from .entity import companies_house_lookup, compare_with_registry, record_party, record_verification
from . import financial as _fin
from .financial import (calculate_measures, financial_quality_flags, reconcile_financials, record_facility,
                        record_security)
from .intake import DT1, find_related_cases, get_requirement_checklist, register_case
from .narrative import review_drafts, save_template_section
from .post_approval import check_case_closure, initiate_handoffs, next_review_date

# Tools per specialist (Arch 3.2). Tool whitelisting per blueprint (ARCH-G03): an agent gets only these.
BY_SPECIALIST = {
    "intake_classifier": [register_case, get_requirement_checklist, find_related_cases],
    "entity_structure": [record_party, companies_house_lookup, compare_with_registry, record_verification],
    "document_ingestion": [list_case_documents, document_outline, find_in_document, read_pages, read_table,
                           read_document, import_ixbrl_accounts, record_statement_from_cells,
                           record_financial_statement, verify_total, record_info_item, record_note,
                           record_info_request, list_info_gaps],
    "bureau_external": [lookup_held_data, credit_reference_lookup, assess_staleness],
    "dd_sanctions": [sanctions_screen, record_check_result, request_hit_disposition],
    "dd_identity": [record_check_result, check_register],
    "dd_adverse_media": [adverse_media_search, record_check_result, request_hit_disposition],
    "dd_summary": [check_register, request_hit_disposition],
    "gap_consolidator": [list_info_gaps, check_register, record_info_request],
    "financial_analysis": [_fin.list_case_documents, _fin.document_outline, _fin.find_in_document, _fin.read_table,
                           record_facility, record_security, financial_quality_flags, calculate_measures,
                           reconcile_financials],
    "narrative_drafter": [save_template_section],
    "narrative_critic": [review_drafts],
    "pack_assembly": [record_lending_request, request_pricing_authorisation, run_completeness_gate,
                      request_submission_authorisation],
    "pack_transmit": [run_completeness_gate, transmit_pack, list_credit_queries],
    "post_approval": [initiate_handoffs, check_case_closure, next_review_date],
}
