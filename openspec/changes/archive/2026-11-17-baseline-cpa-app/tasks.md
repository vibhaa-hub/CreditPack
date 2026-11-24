# Tasks

This change is a baseline of an app that already exists, so each task *verifies* that a spec matches the current code and tests. Where a scenario has no test, the task adds one. If code and spec disagree, fix the spec, not the code, unless the code is clearly a bug; in that case raise a separate change.

Baseline at time of writing: `../venv/Scripts/python -m pytest -q` in `cpa_app/` → **255 passed** on SQLite.

## 1. Environment

- [ ] 1.1 Run the suite on SQLite and on Postgres (`TEST_DATABASE_URL` pointing at the `cpa_test` database in the `cpa-postgres` container), and verify that both report 255 or more passed and 0 failed
- [ ] 1.2 Run `openspec validate baseline-cpa-app --strict` and verify there are no errors or warnings

## 2. Case intake (`specs/case-intake`)

- [ ] 2.1 Check the registration-validation, one-case-per-session and ID-format scenarios against `tests/test_cases.py` and `tests/test_tools.py`; add tests for any scenario not covered and verify they pass
- [ ] 2.2 Check the DT-1 "stricter marker wins" and related-case recency scenarios against `tests/test_tools.py`; add missing tests and verify they pass

## 3. Evidence assembly (`specs/evidence-assembly`)

- [ ] 3.1 Check the extraction, unreadable-document and 20,000-character truncation scenarios against `tests/test_tools.py`; add a test with an image-only PDF and verify it is listed in unreadable_documents
- [ ] 3.2 Check the provenance, financial-statement, info-gap (consent always required) and duplicate-request scenarios against `tests/test_info_gaps.py` and `tests/test_tools.py`, and verify they pass
- [ ] 3.3 Check the registry-comparison and consent-before-bureau scenarios against `tests/test_registry_rules.py` and `tests/test_tools.py`, and verify they pass

## 4. Due diligence (`specs/due-diligence-screening`)

- [ ] 4.1 Check the register-derivation (IDV for individuals only), DT-3 outcome, expiry and CRA scenarios against `tests/test_check_rules.py`, and verify they pass
- [ ] 4.2 Check that no agent tool clears a hit and that a "true match" keeps the case halted, against `tests/test_human_decisions.py` and `tests/test_mesh.py`, and verify they pass

## 5. Financial analysis (`specs/financial-analysis`)

- [ ] 5.1 Check every CALC-001 to CALC-014 scenario in the spec (gearing 1.45x, zero denominators, limit breach, unset cashflow tolerance, month-end-safe review date) against `tests/test_calculations.py`, and verify they pass
- [ ] 5.2 Check the measure-set and data-quality-flag scenarios (one period only, missing EBIT, unaudited) against `tests/test_tools.py`; add missing tests and verify they pass

## 6. Narrative drafting (`specs/narrative-drafting`)

- [ ] 6.1 Check the decision-language patterns (agent save and human amend) against `tests/test_validity_language.py` and `tests/test_human_decisions.py`, and verify they pass
- [ ] 6.2 Check the critic findings, accept/amend/reject and section-version scenarios against `tests/test_section_versions.py` and `tests/test_tools.py`, and verify they pass

## 7. Completeness gate (`specs/pack-completeness-gate`)

- [ ] 7.1 Check the R1 to R8 ordering, deciding rule, corrective actions and CALC-011 completeness against `tests/test_gate_rules.py`, and verify they pass
- [ ] 7.2 Check that authorised exceptions turn R2 and R6 gaps into advisories, and that unset policy produces R7 advisories, against `tests/test_gate_rules.py`; add missing tests and verify they pass

## 8. Submission and Credit (`specs/pack-submission`)

- [ ] 8.1 Check pricing withdrawal on a re-recorded request, the preparer-cannot-authorise rule and the owner-only submission rule against `tests/test_workbench_app.py` and `tests/test_human_decisions.py`, and verify they pass
- [ ] 8.2 Check that transmission re-evaluates the gate, pack versions are immutable, and Credit query and outcome rules hold, against `tests/test_pack_versions.py`, `tests/test_credit_queries.py` and `tests/test_schema.py`, and verify they pass

## 9. Post-approval (`specs/post-approval`)

- [ ] 9.1 Check approval-only handoffs, idempotency, close-with-reason, condition evidence, closure terms-drift and cadence validation against `tests/test_tools.py` and `tests/test_workbench_app.py`; add missing tests and verify they pass

## 10. Orchestration (`specs/agent-orchestration`)

- [ ] 10.1 Check the workflow graph order, the stop for humans and submission routing against `tests/test_mesh.py`, and verify they pass
- [ ] 10.2 Check the per-agent tool allow-lists and declared-key contexts against `tests/test_skills.py` and `tests/test_mesh.py`, and verify they pass
- [ ] 10.3 Check that parallel partition merges lose no writes, and the run-state values (409 on a concurrent start, "interrupted" after restart), against `tests/test_mesh.py` and `tests/test_workbench_app.py`, and verify they pass

## 11. Human decisions (`specs/human-decisions`)

- [ ] 11.1 Check sign-in (scrypt, 8-hour cookie, disabled users) and role refusals audited as access_denied against `tests/test_workbench_identity.py` and `tests/test_workbench_app.py`, and verify they pass
- [ ] 11.2 Check the stale-prerequisite fingerprint refusal (process_failure), audit-before-apply and the 409 during a run against `tests/test_workbench_app.py` and `tests/test_human_decisions.py`, and verify they pass

## 12. Audit trail (`specs/audit-trail`)

- [ ] 12.1 Check the hash-chain, tamper-detection, append-only trigger and snapshot scenarios against `tests/test_audit_chain.py`, `tests/test_schema.py`, `tests/test_snapshots.py` and `tests/test_callbacks.py`, and verify they pass
- [ ] 12.2 Check replay (exit code 1 on a broken chain, `--json`), rollback-keeps-history and unsupported-backend scenarios against `tests/test_replay.py`, `tests/test_snapshots.py` and `tests/test_config.py`, and verify they pass

## 13. Policy parameters (`specs/policy-parameters`)

- [ ] 13.1 Check NOT CONFIGURED handling, the `CPA_POLICY_FILE` override and the policy version on results against `tests/test_policy.py`, and verify they pass

## 14. Workbench UI (`specs/workbench-ui`)

- [ ] 14.1 Run `npm run typecheck` in `cpa_app/workbench/frontend` and verify there are no errors
- [ ] 14.2 Walk through each workbench-ui scenario manually in the browser (`.\start.ps1`): deep link while signed out, queue link, a 25 MB file rejected, run button hidden for a pricing authority, live update from a second user, refusal message, theme toggle. Record the results in this task. There is no automated UI test suite yet

## 15. Integration check

- [ ] 15.1 Run one sample case end to end in the workbench, with a separate user for each role: preparation → dispositions, CRA, discrepancies, section reviews → pricing → submission authorised → submission → Credit outcome → post-approval → closure. Verify that replay shows an intact chain for the case

## Workflow follow-up

- Archive this change once tasks 1 to 15 are complete, so the 13 specs become `openspec/specs/` (`openspec archive baseline-cpa-app`).
- Candidate follow-up changes, each its own proposal, suggested by design.md's Risks section:
  - segment- and grade-based ratio benchmarks: a decision-table layer in `policy.yaml`
  - real Companies House, bureau and screening adapters to replace the stubs
  - a Credit interface to replace the NOT-TRANSMITTED receipt (OQ-14)
  - SSO/MFA sign-in
  - a durable job queue for agent runs
  - populating `policy.yaml` with values signed off by the policy owner
  - an automated frontend test suite
