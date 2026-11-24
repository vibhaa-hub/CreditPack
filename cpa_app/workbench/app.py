"""Credit Pack Workbench: JSON API for the React front end (workbench/frontend), plus the built
single-page app. Every rule is enforced here, never in the browser: sign-in (signed, expiring
cookie), role permissions, approval prerequisites (ARCH-H09) and the audit trail."""
import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from starlette.datastructures import UploadFile   # what request.form() returns (FastAPI subclasses it)

from cpa_agents.rules import reconcile
from cpa_agents.rules.gate import evaluate
from cpa_agents.rules.policy import load_policy
from cpa_agents.files import LocalFileStore, get_file_store, safe_name
from cpa_agents.ldu.pgqueue import Subscription
from cpa_agents.store import get_store
from cpa_agents.store.core import CASE_CHANNEL
from cpa_agents.store.runtime import make_session_service, record_human_decision
from cpa_agents.store.schema import documents

from . import users as U
from .gates import Gates, prereq_hash, prerequisites
from .permissions import ACTIONS, ROLES, can
from .runner import APP, USER, Runs

HERE = Path(__file__).resolve().parent
SPA = HERE / "frontend" / "dist"
SAMPLES = Path(os.getenv("CPA_SAMPLES_DIR") or HERE.parent / "samples")
UPLOADS = Path(os.getenv("CPA_UPLOAD_DIR") or HERE.parent / "cpa_agents" / ".adk" / "uploads")
ALLOWED = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".eml", ".xhtml", ".html", ".htm",   # .xhtml/.html: iXBRL
           ".png", ".jpg", ".jpeg", ".tif", ".tiff"}                                         # scans: OCR
MAX_BYTES = 20 * 1024 * 1024
COOKIE, MAX_AGE = "cpa_wb", 8 * 3600
WORKFLOW_ACTION = {"preparation": "run_preparation", "submission": "run_submission", "post_approval": "run_post_approval"}


def err(status: int, message: str, action: str = "") -> JSONResponse:
    return JSONResponse({"ok": False, "error": message, "action": action}, status_code=status)


def waiting_on(st: dict) -> list[dict]:
    """What is waiting on which human role (the exception queue)."""
    w = []
    for h in st.get("hits_open") or []:
        w.append(("financial_crime_analyst", f"Disposition {h.get('result')} for {h.get('party')} / {h.get('check')}", "checks"))
    if st.get("gate_status") and not st.get("cra_recorded_by"):
        w.append(("onboarding_analyst", "Record the CRA outcome", "checks"))
    for d in st.get("registry_discrepancies") or []:
        if not d.get("resolved_by"):
            w.append(("account_manager", f"Resolve registry discrepancy: {d.get('field')}", "evidence"))
    if st.get("financial_statement_versions") or st.get("financial_statements"):
        for it in reconcile.run(st, load_policy()):
            if it["severity"] == "BLOCK" and not it["explained"]:
                w.append(("account_manager", f"Explain financial difference: {it['description'][:90]}", "analysis"))
    for k, s in (st.get("sections") or {}).items():
        if not s.get("reviewed"):
            w.append(("account_manager", f"Review section {k.replace('_', ' ')}", "narrative"))
    if st.get("lending_request") and not st.get("pricing_authorised_by"):
        w.append(("pricing_authority", "Authorise pricing and terms", "request"))
    if st.get("gate_status") == "PASS" and not st.get("submission_authorised_by"):
        w.append(("account_manager", "Authorise submission to Credit", "submission"))
    if st.get("submission_authorised_by") and not st.get("submitted"):
        w.append(("account_manager", "Run the submission step", "submission"))
    if st.get("submitted") and not st.get("credit_outcome"):
        w.append(("credit_underwriter", "Assess the pack and record the outcome", "credit"))
    for h in st.get("handoffs") or []:
        if h["status"] not in ("complete", "closed"):
            w.append(("operations", f"Handoff: {h['task']}", "handoffs"))
    return [{"role": r, "item": i, "tab": t} for r, i, t in w]


def create_app(workflows: dict | None = None, sessions=None, secret: str | None = None, ldus=None) -> FastAPI:
    """`ldus` (an InProcessLdus) runs agent steps through their LDUs in this process; `workflows`
    runs a given set of workflows directly. With neither, the real agent mesh runs on in-process LDUs."""
    app = FastAPI(title="Credit Pack Workbench API")
    secret = secret or os.getenv("CPA_WORKBENCH_SECRET") or uuid.uuid4().hex   # unset: sign-ins end on restart
    signer = TimestampSigner(secret, salt="cpa-workbench")
    from cpa_agents.ldu.config import distributed
    dist = workflows is None and ldus is None and distributed()     # runs go to case-orchestrator replicas
    if workflows is None and ldus is None and not dist:
        from cpa_agents.ldu.runtime import InProcessLdus
        ldus = InProcessLdus()                              # the real agent mesh, single-process mode
    if ldus is not None:
        workflows = ldus.workflows
    sessions = sessions or make_session_service()
    runs, gates = Runs(sessions, workflows or {}, ldus=ldus, distributed=dist), Gates(sessions)
    app.state.runs, app.state.gates, app.state.sessions = runs, gates, sessions

    # ---------- auth ----------
    def user_of(request: Request) -> dict | None:
        raw = request.cookies.get(COOKIE)
        if not raw:
            return None
        try:
            username = signer.unsign(raw, max_age=MAX_AGE).decode()
        except (BadSignature, SignatureExpired):
            return None
        u = U.get_user(username)
        return {k: u[k] for k in ("username", "display_name", "roles")} if u and u["active"] else None

    def denied(sid, user, action, d):
        gates._denied(sid, user, action, d.reason)
        return err(403, d.reason, d.action)

    @app.post("/api/login")
    async def login(request: Request):
        body = await request.json()
        u = U.authenticate(body.get("username", ""), body.get("password", ""))
        if not u:
            get_store().append_event("workbench", "human", body.get("username") or "anonymous", "access_denied",
                                     detail={"action": "sign_in", "reason": "bad credentials or disabled"})
            return err(401, "Wrong username or password.")
        resp = JSONResponse({"ok": True, "user": u})
        resp.set_cookie(COOKIE, signer.sign(u["username"]).decode(), max_age=MAX_AGE, httponly=True, samesite="lax")
        get_store().append_event("workbench", "human", U.actor(u), "signed_in")
        return resp

    @app.post("/api/logout")
    async def logout(request: Request):
        u = user_of(request)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE)
        if u:
            get_store().append_event("workbench", "human", U.actor(u), "signed_out")
        return resp

    @app.get("/api/me")
    async def me(request: Request):
        u = user_of(request)
        if not u:
            return err(401, "not signed in", "sign in")
        return {"user": u, "roles": ROLES,
                "can": {a: bool(can(u, a)) for a in ("create_case",)}}

    # ---------- cases ----------
    async def all_cases() -> list[dict]:
        resp = await sessions.list_sessions(app_name=APP, user_id=USER)
        out = [summary(s.id, await gates.state(s.id)) for s in resp.sessions]
        return sorted(out, key=lambda c: c["created"] or "", reverse=True)

    def summary(sid: str, st: dict) -> dict:
        status = runs.status(sid)
        stage = ("post-approval" if st.get("credit_outcome") else "with Credit" if st.get("submitted")
                 else "awaiting people" if st.get("gate_status") else "preparing" if status["state"] == "running"
                 else "new")
        return {"sid": sid, "case_id": st.get("case_id"), "dealer": st.get("dealer_name") or "",
                "owner": st.get("owner") or st.get("wb_owner") or "", "stage": stage,
                "gate": st.get("gate_status"), "run": status["state"], "waiting": waiting_on(st),
                "created": st.get("wb_created"), "types": st.get("case_types") or []}

    @app.get("/api/cases")
    async def cases(request: Request):
        if not user_of(request):
            return err(401, "not signed in", "sign in")
        return {"cases": await all_cases()}

    @app.get("/api/queue")
    async def queue(request: Request):
        u = user_of(request)
        if not u:
            return err(401, "not signed in", "sign in")
        mine = []
        for c in await all_cases():
            for w in c["waiting"]:
                if w["role"] in u["roles"] or (w["role"] == "account_manager" and "wholesale_manager" in u["roles"]):
                    mine.append({"sid": c["sid"], "case_id": c["case_id"], "dealer": c["dealer"], "stage": c["stage"], **w})
        return {"items": mine}

    def save_upload(sid, filename, ctype, data: bytes, who: str) -> dict:
        doc_id = f"doc-{uuid.uuid4().hex[:10]}"
        safe = safe_name(filename)
        fs = get_file_store()
        if isinstance(fs, LocalFileStore):
            fs = LocalFileStore(UPLOADS)                    # local mode: today's folder (CPA_UPLOAD_DIR)
        uri = fs.put(sid, f"{doc_id}-{safe}", data)        # s3://... in distributed mode
        now = datetime.now(timezone.utc)
        rec = dict(doc_id=doc_id, filename=safe, path=uri, uri=uri, sha256=hashlib.sha256(data).hexdigest(),
                   size=len(data), content_type=ctype, uploaded_by=who, uploaded_at=now.isoformat(timespec="seconds"))
        with get_store().engine.begin() as c:
            c.execute(documents.insert().values(**{**{k: v for k, v in rec.items() if k != "uri"}, "uploaded_at": now},
                                                session_id=sid, case_id=None))
        return rec

    async def read_files(form) -> tuple[list, str | None]:
        out = []
        for x in [x for x in form.getlist("files") if isinstance(x, UploadFile) and x.filename]:
            if Path(x.filename).suffix.lower() not in ALLOWED:
                return [], f"{x.filename}: file type not allowed ({', '.join(sorted(ALLOWED))})"
            data = await x.read()
            if len(data) > MAX_BYTES:
                return [], f"{x.filename}: larger than 20 MB"
            out.append((x.filename, x.content_type, data))
        return out, None

    @app.post("/api/cases")
    async def create_case(request: Request):
        u = user_of(request)
        if not u:
            return err(401, "not signed in", "sign in")
        d = can(u, "create_case")
        if not d:
            return denied(None, u, "create_case", d)
        form = await request.form()
        text = (form.get("request_text") or "").strip()
        if not text:
            return err(400, "Describe the request.")
        files, problem = await read_files(form)
        if problem:
            return err(400, problem)
        sid = f"wb-{uuid.uuid4().hex[:12]}"
        await sessions.create_session(app_name=APP, user_id=USER, session_id=sid)
        who = U.actor(u, d.role)
        docs = [save_upload(sid, n, t, b, who) for n, t, b in files]
        await record_human_decision(sessions, APP, USER, sid, who,
                                    {"request_text": text, "documents": docs, "wb_owner": u["display_name"],
                                     "wb_created": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                                    f"case opened with {len(docs)} document(s)")
        if form.get("run_now") in ("true", "on", "1"):
            runs.start(sid, "preparation", text, who)
        return {"ok": True, "sid": sid}

    # ---------- sample cases (cpa_app/samples/<name>/request.txt + documents) ----------
    def sample_dirs() -> list[Path]:
        return sorted(p for p in SAMPLES.iterdir() if (p / "request.txt").is_file()) if SAMPLES.is_dir() else []

    def sample_info(p: Path) -> dict:
        text = (p / "request.txt").read_text(encoding="utf-8")
        lines = [l for l in text.splitlines() if l.strip() and not l.startswith("FICTIONAL")]
        notes = (p / "README.txt").read_text(encoding="utf-8").splitlines()[2:] if (p / "README.txt").is_file() else []
        return {"name": p.name, "title": p.name.split("-", 1)[-1].replace("-", " ").title(),
                "summary": " ".join(lines[:3])[:300],
                "documents": sorted(f.name for f in p.iterdir() if f.is_file() and f.name not in ("request.txt", "README.txt")),
                "expect": [n.lstrip("- ").strip() for n in notes if n.strip().startswith("-")]}

    @app.get("/api/samples")
    async def samples(request: Request):
        if not user_of(request):
            return err(401, "not signed in", "sign in")
        return {"samples": [sample_info(p) for p in sample_dirs()]}

    @app.post("/api/samples/{name}/open")
    async def open_sample(name: str, request: Request):
        """Open a case from a sample folder exactly as if its request and documents were uploaded."""
        u = user_of(request)
        if not u:
            return err(401, "not signed in", "sign in")
        d = can(u, "create_case")
        if not d:
            return denied(None, u, "create_case", d)
        folder = next((p for p in sample_dirs() if p.name == name), None)
        if folder is None:
            return err(404, "No such sample.")
        sid = f"wb-{uuid.uuid4().hex[:12]}"
        await sessions.create_session(app_name=APP, user_id=USER, session_id=sid)
        who = U.actor(u, d.role)
        docs = [save_upload(sid, f.name, None, f.read_bytes(), who) for f in sorted(folder.iterdir())
                if f.is_file() and f.name not in ("request.txt", "README.txt") and f.suffix.lower() in ALLOWED]
        text = (folder / "request.txt").read_text(encoding="utf-8")
        await record_human_decision(sessions, APP, USER, sid, who,
                                    {"request_text": text, "documents": docs, "wb_owner": u["display_name"],
                                     "wb_created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                     "wb_sample": name},
                                    f"case opened from sample {name} with {len(docs)} document(s)")
        runs.start(sid, "preparation", text, who)
        return {"ok": True, "sid": sid}

    @app.post("/api/cases/{sid}/upload")
    async def upload(sid: str, request: Request):
        u = user_of(request)
        if not u:
            return err(401, "not signed in", "sign in")
        st = await gates.state(sid)
        d = can(u, "upload_document", st)
        if not d:
            return denied(sid, u, "upload_document", d)
        files, problem = await read_files(await request.form())
        if problem:
            return err(400, problem)
        who = U.actor(u, d.role)
        new = [save_upload(sid, n, t, b, who) for n, t, b in files]
        await record_human_decision(sessions, APP, USER, sid, who, {"documents": (st.get("documents") or []) + new},
                                    f"uploaded {len(new)} document(s)")
        return {"ok": True, "message": f"Uploaded {len(new)} document(s)"}

    @app.post("/api/cases/{sid}/run/{workflow}")
    async def run(sid: str, workflow: str, request: Request):
        u = user_of(request)
        if not u:
            return err(401, "not signed in", "sign in")
        if workflow not in WORKFLOW_ACTION:
            return err(404, "unknown workflow")
        st = await gates.state(sid)
        d = can(u, WORKFLOW_ACTION[workflow], st)
        if not d:
            return denied(sid, u, WORKFLOW_ACTION[workflow], d)
        text = {"preparation": st.get("request_text") or "",
                "submission": "Humans have recorded their decisions. Transmit if the gate allows.",
                "post_approval": "Approval recorded. Start handoffs and check closure."}[workflow]
        if not runs.start(sid, workflow, text, U.actor(u, d.role)):
            return err(409, "A run is already in progress for this case.")
        return {"ok": True, "message": f"Started {workflow.replace('_', '-')}"}

    @app.get("/api/cases/{sid}/status")
    async def status(sid: str, request: Request):
        if not user_of(request):
            return err(401, "not signed in", "sign in")
        return runs.status(sid)

    @app.get("/api/cases/{sid}/stream")
    async def stream(sid: str, request: Request):
        """Server-sent events: a 'change' event whenever the run changes (state, waiting-on LDU) or
        the case's audit trail grows, so the page updates live while agents run and while other
        people act on the case. Each check reads the run row and an event count, not the trail.
        On Postgres the stream wakes on LISTEN cpa_cases (sent with every audit event and run
        change, from any replica) and polls only as a fallback; elsewhere it polls."""
        if not user_of(request):
            return err(401, "not signed in", "sign in")

        async def gen():
            last = None
            async with Subscription(CASE_CHANNEL, sid) as sub:
                while not await request.is_disconnected():
                    s = await asyncio.to_thread(runs.status, sid)
                    key = (s["state"], s.get("waiting_on"), s["events"])
                    if key != last:
                        last = key
                        yield f"event: change\ndata: {json.dumps(s)}\n\n"
                    busy = s["state"] in ("running", "waiting")
                    await sub.wait((5 if busy else 15) if sub.live else (1.5 if busy else 4))
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/cases/{sid}")
    async def case(sid: str, request: Request):
        u = user_of(request)
        if not u:
            return err(401, "not signed in", "sign in")
        if not await sessions.get_session(app_name=APP, user_id=USER, session_id=sid):
            return err(404, "No such case.")
        st = await gates.state(sid)
        store = get_store()
        case_id = st.get("case_id")
        gate = evaluate(st, load_policy()) if st.get("checklist") else None
        pre = {}
        for i, _ in enumerate(st.get("hits_open") or []):
            pre[f"hit:{i}"] = prereq_hash(prerequisites("disposition_hit", st, idx=i))
        for i, _ in enumerate(st.get("registry_discrepancies") or []):
            pre[f"disc:{i}"] = prereq_hash(prerequisites("resolve_discrepancy", st, idx=i))
        for name in st.get("sections") or {}:
            pre[f"sec:{name}"] = prereq_hash(prerequisites("review_section", st, section=name))
        recon = reconcile.run(st, load_policy())
        for it in recon:
            pre[f"rec:{it['key']}"] = prereq_hash(prerequisites("explain_difference", st, key=it["key"]))
        pre["pricing"] = prereq_hash(prerequisites("authorise_pricing", st))
        pre["submission"] = prereq_hash(prerequisites("authorise_submission", st))
        perms = {}
        for a in ACTIONS:
            dd = can(u, a, st)
            perms[a] = {"allowed": bool(dd), "reason": dd.reason}
        diffs = {}
        if case_id:
            for n in st.get("sections") or {}:
                v = store.section_versions(case_id, n)
                if len(v) > 1:
                    diffs[n] = store.section_diff(case_id, n, v[-2]["version"], v[-1]["version"])
        hidden = {"request_text"}            # sent separately below
        return {"sid": sid, "state": {k: v for k, v in st.items() if not k.startswith("wb_") and k not in hidden},
                "request_text": st.get("request_text"), "owner": st.get("owner") or st.get("wb_owner"),
                "gate": gate and {k: gate[k] for k in ("result", "deciding_rule", "gaps", "advisories", "completeness",
                                                        "mandatory_items", "check_register", "policy_version",
                                                        "submission_may_be_authorised")},
                "status": runs.status(sid), "waiting": waiting_on(st), "prereq": pre, "permissions": perms,
                "diffs": diffs, "reconciliation": recon,
                "packs": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in p.items() if k != "content"}
                          for p in (store.pack_versions(case_id) if case_id else [])],
                "queries": store.credit_queries(case_id) if case_id else []}

    @app.get("/api/cases/{sid}/audit")
    async def audit(sid: str, request: Request):
        u = user_of(request)
        if not u:
            return err(401, "not signed in", "sign in")
        st = await gates.state(sid)
        store = get_store()
        return {"events": store.events(st.get("case_id") or sid), "chain": store.verify_chain(sid)}

    @app.post("/api/cases/{sid}/act/{action}")
    async def act(sid: str, action: str, request: Request):
        u = user_of(request)
        if not u:
            return err(401, "not signed in", "sign in")
        if runs.running(sid):
            return err(409, "An agent run is in progress - wait for it to finish.")
        if action not in ACTIONS:
            return err(404, f"unknown action {action}")
        d = can(u, action, await gates.state(sid))
        if not d:
            return denied(sid, u, action, d)
        body = await request.json()
        form = {k: ("on" if v is True else "" if v is False else str(v)) for k, v in body.items() if v is not None}
        ok, msg = await gates.act(sid, u, action, form)
        return {"ok": True, "message": msg} if ok else err(400, msg)

    # ---------- single-page app ----------
    if (SPA / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(SPA / "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return err(404, "not found")
        index = SPA / "index.html"
        if not index.exists():
            return JSONResponse({"error": "front end not built: cd workbench/frontend && npm install && npm run build"},
                                status_code=503)
        f = SPA / path
        if path and f.is_file() and SPA in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(index)

    return app
