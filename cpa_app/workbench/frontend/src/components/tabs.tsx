import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Chip, FormControlLabel, Grid2 as Grid,
  LinearProgress, List, ListItem, ListItemText, Stack, Switch, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, TextField, Typography } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import { api, fmtMoney, label, type CaseDetail } from "../api";
import { useAct } from "../hooks";
import { useNotify } from "../notify";
import ActionDialog from "./ActionDialog";
import { Empty, KV, Section } from "./bits";

type P = { d: CaseDetail };
const statusColor = (s: string) => (s === "complete" ? "success" : s === "hold" || s === "halted" ? "error" : "warning");

function Denied({ reason }: { reason?: string }) {
  return reason ? <Typography variant="caption" color="text.secondary">{reason}</Typography> : null;
}

// ---------------------------------------------------------------- Gate
export function GateTab({ d }: P) {
  const act = useAct(d.sid);
  const g = d.gate;
  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, lg: 8 }}>
        <Section title={g ? <>DT-2 gate: <Box component="span" color={g.result === "PASS" ? "success.main" : g.result === "ADVISORY" ? "warning.main" : "error.main"}>{g.result}</Box></> : "DT-2 gate"}
          sub={g ? `Deciding rule ${g.deciding_rule} · ${g.mandatory_items.complete}/${g.mandatory_items.applicable} mandatory items · policy ${g.policy_version}` : undefined}>
          {!g ? <Empty>The gate runs once intake has built the checklist. Run preparation to start.</Empty> : (
            <Stack spacing={2}>
              <Box>
                <Stack direction="row" justifyContent="space-between"><Typography variant="body2">Completeness (CALC-011)</Typography>
                  <Typography variant="body2" fontWeight={600}>{g.completeness.display}</Typography></Stack>
                <LinearProgress variant="determinate" value={Math.min(100, g.completeness.value ?? 0)}
                  color={g.result === "BLOCK" ? "error" : "success"} sx={{ height: 8, borderRadius: 4, mt: 0.5 }} />
              </Box>
              {g.gaps.length === 0 ? <Alert severity="success">No blocking gaps.</Alert> : (
                <TableContainer><Table size="small">
                  <TableHead><TableRow><TableCell>Rule</TableCell><TableCell>Blocking gap</TableCell><TableCell>Corrective action</TableCell></TableRow></TableHead>
                  <TableBody>{g.gaps.map((x, i) => (
                    <TableRow key={i}><TableCell><Chip size="small" color="error" label={x.rule} /></TableCell>
                      <TableCell>{x.reason}</TableCell><TableCell>{x.action}</TableCell></TableRow>))}</TableBody>
                </Table></TableContainer>)}
              {g.advisories.length > 0 && (
                <Accordion disableGutters variant="outlined">
                  <AccordionSummary expandIcon={<ExpandMoreIcon />}><WarningAmberIcon color="warning" sx={{ mr: 1 }} />
                    {g.advisories.length} advisories (submission may proceed)</AccordionSummary>
                  <AccordionDetails><List dense>{g.advisories.map((a, i) => (
                    <ListItem key={i}><ListItemText primary={`${a.rule}: ${a.reason}`} secondary={a.action} /></ListItem>))}</List></AccordionDetails>
                </Accordion>)}
            </Stack>)}
        </Section>
      </Grid>
      <Grid size={{ xs: 12, lg: 4 }}>
        <Section title="Waiting on people">
          {d.waiting.length === 0 ? <Empty>Nothing.</Empty> : (
            <List dense disablePadding>{d.waiting.map((w, i) => (
              <ListItem key={i} disableGutters><ListItemText primary={w.item} secondary={label(w.role)} /></ListItem>))}</List>)}
        </Section>
        {d.permissions.authorise_exception?.allowed && (
          <Section title="Authorised exception" sub="BR-E04: named approver and reason">
            <ActionDialog button="Record an exception" title="Authorised exception" submitLabel="Record exception" variant="outlined"
              fields={[{ name: "rule", label: "Rule (e.g. R2 or R6)", required: true },
                       { name: "item", label: "Item exactly as shown (e.g. Acme Motors Ltd/kyc)", required: true },
                       { name: "reason", label: "Reason", required: true, multiline: true }]}
              onSubmit={(v) => act.mutateAsync({ action: "authorise_exception", body: v })} />
          </Section>)}
      </Grid>
    </Grid>
  );
}

// ---------------------------------------------------------------- Evidence
export function EvidenceTab({ d }: P) {
  const st = d.state, act = useAct(d.sid), p = d.permissions;
  const qc = useQueryClient();
  const { ok, fail } = useNotify();
  const input = useRef<HTMLInputElement>(null);
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    const f = new FormData();
    Array.from(files).forEach((x) => f.append("files", x));
    try { ok((await api.upload(d.sid, f)).message); qc.invalidateQueries({ queryKey: ["case", d.sid] }); } catch (e) { fail(e); }
  };
  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, md: 6 }}>
        <Section title="Request"><Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>{d.request_text}</Typography></Section>
      </Grid>
      <Grid size={{ xs: 12, md: 6 }}>
        <Section title="Documents" action={p.upload_document?.allowed && (<>
          <Button size="small" onClick={() => input.current?.click()}>Upload</Button>
          <input ref={input} type="file" multiple hidden accept=".pdf,.docx,.xlsx,.csv,.txt,.eml" onChange={(e) => upload(e.target.files)} /></>)}>
          {(st.documents ?? []).length === 0 ? <Empty>No documents.</Empty> : (
            <List dense disablePadding>{st.documents.map((x: any) => (
              <ListItem key={x.doc_id} disableGutters><ListItemText primary={x.filename}
                secondary={`${x.uploaded_by} · ${x.uploaded_at} · SHA-256 ${x.sha256.slice(0, 12)}…`} /></ListItem>))}</List>)}
          {(st.unreadable_documents ?? []).map((u: any, i: number) => <Alert key={i} severity="warning" sx={{ mt: 1 }}>Unreadable: {u.filename} — {u.error}</Alert>)}
        </Section>
      </Grid>
      <Grid size={12}>
        <Section title="Information items" sub="Every item with its source and date (REQ-015)">
          <TableContainer><Table size="small">
            <TableHead><TableRow><TableCell>Class</TableCell><TableCell>Value</TableCell><TableCell>Source</TableCell><TableCell>As at</TableCell><TableCell>Confidence</TableCell></TableRow></TableHead>
            <TableBody>{(st.info_items ?? []).map((i: any, n: number) => (
              <TableRow key={n}><TableCell>{i.info_class}</TableCell><TableCell>{i.value}</TableCell><TableCell>{i.source} · {i.provider}</TableCell>
                <TableCell>{i.as_at}</TableCell><TableCell>{i.confidence === "low" ? <Chip size="small" color="warning" label="low — verify" /> : i.confidence}</TableCell></TableRow>))}
            </TableBody></Table></TableContainer>
          {!(st.info_items ?? []).length && <Empty>None captured yet.</Empty>}
        </Section>
      </Grid>
      <Grid size={{ xs: 12, md: 6 }}>
        <Section title="Parties">
          {(st.parties ?? []).length === 0 ? <Empty>None recorded.</Empty> : (
            <Table size="small"><TableHead><TableRow><TableCell>Name</TableCell><TableCell>Role</TableCell><TableCell>%</TableCell></TableRow></TableHead>
              <TableBody>{st.parties.map((x: any, i: number) => (
                <TableRow key={i}><TableCell>{x.name}</TableCell><TableCell>{x.role}{!x.individual && " (corporate)"}</TableCell><TableCell>{x.pct ?? ""}</TableCell></TableRow>))}</TableBody></Table>)}
        </Section>
      </Grid>
      <Grid size={{ xs: 12, md: 6 }}>
        <Section title="Registry discrepancies" sub={st.registry_record?.retrieved ? `Companies House record retrieved ${st.registry_record.retrieved}` : undefined}>
          {(st.registry_discrepancies ?? []).length === 0 ? <Empty>None.</Empty> : (
            <Stack spacing={1.5}>{st.registry_discrepancies.map((x: any, i: number) => (
              <Box key={i}>
                <Typography variant="body2"><b>{x.field}</b>: {x.issue} — supplied <i>{x.supplied ?? "—"}</i>, registry <i>{x.registry ?? "—"}</i></Typography>
                {x.resolved_by ? <Typography variant="caption" color="success.main">Resolved by {x.resolved_by}: {x.resolution}</Typography>
                  : p.resolve_discrepancy?.allowed ? (
                    <ActionDialog button="Resolve" title="Resolve registry discrepancy" submitLabel="Resolve" variant="outlined"
                      fields={[{ name: "resolution", label: "How it was resolved", required: true, multiline: true }]}
                      onSubmit={(v) => act.mutateAsync({ action: "resolve_discrepancy", body: { ...v, idx: i, _prereq: d.prereq[`disc:${i}`] } })}>
                      <Alert severity="info">{x.field}: supplied “{x.supplied ?? "—"}”, registry “{x.registry ?? "—"}” ({x.issue})</Alert>
                    </ActionDialog>) : <Denied reason={p.resolve_discrepancy?.reason} />}
              </Box>))}</Stack>)}
        </Section>
      </Grid>
      <Grid size={{ xs: 12, md: 6 }}>
        <Section title="Information requests">
          {(st.info_requests ?? []).length === 0 ? <Empty>None.</Empty> : (
            <Table size="small"><TableHead><TableRow><TableCell>Item</TableCell><TableCell>Recipient</TableCell><TableCell>Due</TableCell><TableCell>Status</TableCell></TableRow></TableHead>
              <TableBody>{st.info_requests.map((r: any) => (
                <TableRow key={r.id}><TableCell>{r.item}</TableCell><TableCell>{r.recipient}</TableCell><TableCell>{r.due}</TableCell><TableCell>{r.status}</TableCell></TableRow>))}</TableBody></Table>)}
        </Section>
      </Grid>
      <Grid size={{ xs: 12, md: 6 }}>
        <Section title="Notes" action={p.add_note?.allowed && (
          <ActionDialog button="Add note" title="Meeting or call note" submitLabel="Add note" variant="text"
            fields={[{ name: "text", label: "Note", required: true, multiline: true }, { name: "participants", label: "Participants (comma separated)" }]}
            onSubmit={(v) => act.mutateAsync({ action: "add_note", body: v })} />)}>
          {(st.notes ?? []).length === 0 ? <Empty>No notes.</Empty> : st.notes.map((n: any, i: number) => (
            <Typography key={i} variant="body2" sx={{ mb: 1 }}><b>{n.date}</b> {n.author}: {n.text}</Typography>))}
        </Section>
      </Grid>
    </Grid>
  );
}

// ---------------------------------------------------------------- Checks
export function ChecksTab({ d }: P) {
  const st = d.state, act = useAct(d.sid), p = d.permissions;
  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, lg: 7 }}>
        <Section title="Check register" sub="Every mandatory party × check from the DT-1 checklist">
          {!d.gate ? <Empty>Run preparation first.</Empty> : (
            <TableContainer><Table size="small">
              <TableHead><TableRow><TableCell>Party</TableCell><TableCell>Check</TableCell><TableCell>Status</TableCell><TableCell>Reason</TableCell></TableRow></TableHead>
              <TableBody>{d.gate.check_register.map((c, i) => (
                <TableRow key={i}><TableCell>{c.party}</TableCell><TableCell>{c.check}</TableCell>
                  <TableCell><Chip size="small" color={statusColor(c.status)} label={c.status + (c.manual ? " · manual" : "")} /></TableCell>
                  <TableCell><Typography variant="caption">{c.reason}</Typography></TableCell></TableRow>))}</TableBody>
            </Table></TableContainer>)}
        </Section>
      </Grid>
      <Grid size={{ xs: 12, lg: 5 }}>
        <Section title="Hits awaiting disposition" sub="Only a Financial Crime Analyst can disposition. The agent never clears a hit.">
          {(st.hits_open ?? []).length === 0 ? <Empty>None open.</Empty> : (
            <Stack spacing={1.5}>{st.hits_open.map((h: any, i: number) => (
              <Alert key={i} severity="error" action={p.disposition_hit?.allowed && (
                <ActionDialog button="Disposition" title={`Disposition: ${h.party} / ${h.check}`} submitLabel="Record disposition" color="error"
                  fields={[{ name: "disposition", label: "Disposition", options: ["false positive", "true match"] },
                           { name: "rationale", label: "Rationale", required: true, multiline: true }]}
                  onSubmit={(v) => act.mutateAsync({ action: "disposition_hit", body: { ...v, idx: i, _prereq: d.prereq[`hit:${i}`] } })}>
                  <Alert severity="warning">{h.result} for <b>{h.party}</b> ({h.check}). Evidence: {h.evidence_ref ?? "—"}.
                    A true match halts the case and is escalated; do not tell the dealer (LR-02).</Alert>
                </ActionDialog>)}>
                <b>{h.result}</b> — {h.party} / {h.check}</Alert>))}</Stack>)}
          {(st.hit_dispositions ?? []).map((x: any, i: number) => (
            <Typography key={i} variant="caption" display="block" sx={{ mt: 1 }}>{x.party}/{x.check}: <b>{x.disposition}</b> by {x.by} — {x.rationale}</Typography>))}
        </Section>
        <Section title="Customer Risk Assessment">
          {st.cra_recorded_by ? (<Stack spacing={0.5}><Typography color="success.main"><CheckCircleIcon fontSize="small" sx={{ verticalAlign: "middle", mr: 0.5 }} />
              {st.cra?.outcome} — recorded by {st.cra_recorded_by}</Typography>{st.cra && <Typography variant="body2">{st.cra.basis}</Typography>}</Stack>)
            : p.record_cra?.allowed ? (
              <ActionDialog button="Record CRA" title="Customer Risk Assessment" submitLabel="Record CRA"
                fields={[{ name: "outcome", label: "Outcome", options: ["low", "medium", "high"] }, { name: "basis", label: "Basis", required: true, multiline: true }]}
                onSubmit={(v) => act.mutateAsync({ action: "record_cra", body: v })} />)
            : <Empty>Awaiting the assessor.</Empty>}
        </Section>
        {p.record_manual_check?.allowed && (
          <Section title="Manual check" sub="REQ-035 / REQ-092: evidence is mandatory">
            <ActionDialog button="Record a manual check" title="Record a manual check" submitLabel="Record" variant="outlined"
              fields={[{ name: "party", label: "Party", required: true },
                       { name: "check", label: "Check", options: ["kyc", "aml", "sanctions", "idv", "adverse_media"] },
                       { name: "result", label: "Result", options: ["clear", "potential_match", "unavailable", "idv_failed"] },
                       { name: "tool_used", label: "Source or tool used", required: true },
                       { name: "evidence_ref", label: "Evidence reference", required: true }]}
              onSubmit={(v) => act.mutateAsync({ action: "record_manual_check", body: v })} />
          </Section>)}
      </Grid>
    </Grid>
  );
}

// ---------------------------------------------------------------- Analysis
const fmtVal = (v: number | string) => (typeof v === "number" ? fmtMoney(v) : v);
const BASIS: Record<string, string> = { audited: "audited", unaudited_accounts: "unaudited accounts", management: "management accounts",
  dealer_stated: "dealer-stated" };

export function AnalysisTab({ d }: P) {
  const st = d.state, act = useAct(d.sid), p = d.permissions;
  const md = Object.entries(st.measures_detail ?? {}) as [string, any][];
  const recon = d.reconciliation ?? [];
  const open = recon.filter((r) => r.severity === "BLOCK" && !r.explained);
  const used = new Set((st.financial_statements ?? []).map((s: any) => s.version_id));
  const versions: any[] = st.financial_statement_versions ?? st.financial_statements ?? [];
  const mb = st.measures_basis ?? {};
  return (
    <Grid container spacing={2}>
      <Grid size={12}>
        <Section title="Measures" sub={"Deterministic BA pack section N definitions; confirm against Credit policy (OQ-04, OQ-09)"
          + (mb.latest ? ` · latest period ${mb.latest.period_end} (${BASIS[mb.latest.basis] ?? mb.latest.basis ?? "accounts"})` : "")
          + (mb.prior ? ` · prior ${mb.prior.period_end} (${BASIS[mb.prior.basis] ?? mb.prior.basis ?? "accounts"})` : "")}>
          {md.length === 0 ? <Empty>Not calculated yet.</Empty> : (
            <Grid container spacing={1.5}>{md.map(([k, v]) => (
              <Grid key={k} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
                <Box sx={{ border: 1, borderColor: "divider", borderRadius: 2, p: 1.5, height: "100%" }}>
                  <Typography variant="caption" color="text.secondary">{v.calc} · {label(k)}</Typography>
                  <Typography variant="h6" sx={{ fontVariantNumeric: "tabular-nums" }}>{v.display}</Typography>
                  {(v.basis ?? []).length > 0 && <Typography variant="caption" color="text.secondary" display="block">Based on {v.basis.join(", ")}</Typography>}
                  {v.flags.map((f: string) => <Chip key={f} size="small" color="warning" variant="outlined" label={f} sx={{ mt: 0.5, mr: 0.5 }} />)}
                </Box>
              </Grid>))}</Grid>)}
        </Section>
      </Grid>
      <Grid size={12}>
        <Section title="Reconciliation" sub={recon.length === 0 ? "Figures checked against each other: totals, opening vs closing, versions, documents"
          : `${open.length} difference(s) to correct or explain before submission (DT-2 R5) · ${recon.length} item(s) in all`}>
          {recon.length === 0 ? <Empty>No differences found.</Empty> : (
            <Stack spacing={1.5}>{recon.map((r) => (
              <Box key={r.key} sx={{ border: 1, borderColor: r.explained ? "divider" : r.severity === "BLOCK" ? "error.light" : "warning.light", borderRadius: 2, p: 1.5 }}>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                  <Chip size="small" label={r.kind.replace("_", " ")} variant="outlined" />
                  <Chip size="small" label={r.explained ? "explained" : r.severity === "BLOCK" ? "blocks" : "advisory"}
                    color={r.explained ? "success" : r.severity === "BLOCK" ? "error" : "warning"} />
                  <Typography variant="body2" fontWeight={600}>{r.description}</Typography>
                </Stack>
                <Table size="small"><TableBody>{r.values.map((v, i) => (
                  <TableRow key={i}><TableCell>{v.label}</TableCell><TableCell align="right" sx={{ fontVariantNumeric: "tabular-nums" }}>{fmtVal(v.value)}</TableCell>
                    <TableCell><Typography variant="caption" color="text.secondary">{v.source}</Typography></TableCell></TableRow>))}
                  {r.difference !== null && <TableRow><TableCell><b>Difference</b></TableCell><TableCell align="right"><b>{fmtMoney(r.difference)}</b></TableCell>
                    <TableCell><Typography variant="caption" color="text.secondary">tolerance {r.tolerance ?? "—"}</Typography></TableCell></TableRow>}
                </TableBody></Table>
                {r.explained ? <Typography variant="caption" color="success.main">Explained by {r.explained.by} on {r.explained.date}: {r.explained.explanation}</Typography>
                  : r.severity === "BLOCK" && (p.explain_difference?.allowed ? (
                    <Box sx={{ mt: 1 }}><ActionDialog button="Explain" title="Explain financial difference" submitLabel="Record explanation" variant="outlined"
                      fields={[{ name: "explanation", label: "Why the figures differ, or why they are acceptable", required: true, multiline: true }]}
                      onSubmit={(v) => act.mutateAsync({ action: "explain_difference", body: { ...v, key: r.key, _prereq: d.prereq[`rec:${r.key}`] } })}>
                      <Alert severity="warning">{r.description}. {r.action}. If the figures are wrong, correct them and run preparation again instead.</Alert>
                    </ActionDialog></Box>) : <Denied reason={p.explain_difference?.reason} />)}
              </Box>))}</Stack>)}
        </Section>
      </Grid>
      <Grid size={{ xs: 12, md: 6 }}>
        <Section title="Data quality flags">
          {(st.financial_quality_flags ?? []).length === 0 ? <Empty>None.</Empty> : st.financial_quality_flags.map((f: any, i: number) => (
            <Alert key={i} severity="warning" sx={{ mb: 1 }}>{f.flag} — {f.action}</Alert>))}
        </Section>
      </Grid>
      <Grid size={{ xs: 12, md: 6 }}>
        <Section title="Borrowing profile">
          {(st.borrowing_profile ?? []).length === 0 ? <Empty>No facilities recorded.</Empty> : (
            <Table size="small"><TableHead><TableRow><TableCell>Line</TableCell><TableCell align="right">Drawn</TableCell><TableCell align="right">Limit</TableCell><TableCell>Utilisation</TableCell></TableRow></TableHead>
              <TableBody>{st.borrowing_profile.map((b: any, i: number) => (
                <TableRow key={i}><TableCell>{b.lending_line}</TableCell><TableCell align="right">{fmtMoney(b.drawn)}</TableCell>
                  <TableCell align="right">{fmtMoney(b.limit)}</TableCell><TableCell>{b.utilisation}</TableCell></TableRow>))}</TableBody></Table>)}
          {st.security && <Typography variant="body2" sx={{ mt: 1 }}>Security: {st.security.description}, {fmtMoney(st.security.value)} ({st.security.basis}, {st.security.date})</Typography>}
        </Section>
      </Grid>
      <Grid size={12}>
        <Section title="Financial statements" sub="Every version is kept; the analysis uses the best basis per period (policy financial_basis_precedence)">
          {versions.length === 0 ? <Empty>None recorded.</Empty> : (
            <TableContainer><Table size="small">
              <TableHead><TableRow><TableCell>Period end</TableCell><TableCell>Basis</TableCell><TableCell>Used</TableCell><TableCell>Currency</TableCell><TableCell>Source</TableCell><TableCell>Figures</TableCell></TableRow></TableHead>
              <TableBody>{versions.map((s: any) => {
                const basis = s.basis ?? (s.audited ? "audited" : "unaudited_accounts");
                const isUsed = s.id ? used.has(s.id) : true;
                return (
                  <TableRow key={s.id ?? s.period_end} sx={{ opacity: isUsed ? 1 : 0.6 }}><TableCell>{s.period_end}{s.period_months && s.period_months !== 12 ? ` (${s.period_months} months)` : ""}</TableCell>
                    <TableCell>{basis === "audited" ? BASIS[basis] : <Chip size="small" color="warning" label={BASIS[basis] ?? basis} />}</TableCell>
                    <TableCell>{isUsed ? <Chip size="small" color="success" variant="outlined" label="used" /> : "superseded"}</TableCell>
                    <TableCell>{s.currency}</TableCell><TableCell>{s.source}</TableCell>
                    <TableCell><Typography variant="caption">{Object.entries(s.figures).map(([k, v]) =>
                      `${label(k)} ${fmtMoney(v as number)}${s.refs?.[k] ? ` [${String(s.refs[k]).split(":").slice(1).join(":")}]` : ""}`).join(" · ")}</Typography></TableCell></TableRow>);
              })}</TableBody>
            </Table></TableContainer>)}
        </Section>
      </Grid>
    </Grid>
  );
}

// ---------------------------------------------------------------- Narrative
export function NarrativeTab({ d }: P) {
  const st = d.state, act = useAct(d.sid), p = d.permissions;
  const [editing, setEditing] = useState<Record<string, string | undefined>>({});
  const sections = Object.entries(st.sections ?? {}) as [string, any][];
  if (!sections.length) return <Section title="Narrative"><Empty>No sections drafted yet.</Empty></Section>;
  const review = (name: string, decision: string, text?: string) =>
    act.mutateAsync({ action: "review_section", body: { section: name, decision, text, _prereq: d.prereq[`sec:${name}`] } })
      .then(() => setEditing({ ...editing, [name]: undefined }));
  return (
    <Stack spacing={2}>
      {sections.map(([name, s]) => {
        const findings = (st.critic_findings ?? []).filter((f: any) => f.section === name);
        const ed = editing[name];
        return (
          <Section key={name} title={<>{label(name)} <Typography component="span" variant="caption" color="text.secondary">v{s.version}</Typography></>}
            action={s.reviewed ? <Chip color="success" size="small" icon={<CheckCircleIcon />} label={`Accepted by ${s.reviewed_by ?? "owner"}`} />
              : <Chip color="warning" size="small" icon={<WarningAmberIcon />} label="Non-human draft — needs review" />}>
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, md: 8 }}>
                {ed !== undefined ? <TextField multiline minRows={6} fullWidth value={ed} onChange={(e) => setEditing({ ...editing, [name]: e.target.value })} />
                  : <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>{s.text}</Typography>}
              </Grid>
              <Grid size={{ xs: 12, md: 4 }}>
                <Typography variant="subtitle2">Evidence cited</Typography>
                {(s.evidence ?? []).length ? s.evidence.map((e: string) => <Chip key={e} size="small" label={e} sx={{ mr: 0.5, mb: 0.5 }} />)
                  : <Typography variant="caption" color="error">None cited (ARCH-G08)</Typography>}
                {findings.map((f: any, i: number) => <Alert key={i} severity="warning" sx={{ mt: 1 }}>Critic: {f.issue} — {f.required_change}</Alert>)}
                {d.diffs[name] && (
                  <Accordion disableGutters variant="outlined" sx={{ mt: 1 }}>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}><Typography variant="body2">Changes from previous version</Typography></AccordionSummary>
                    <AccordionDetails><Box component="pre" sx={{ fontSize: 12, overflowX: "auto", m: 0 }}>{d.diffs[name]}</Box></AccordionDetails>
                  </Accordion>)}
              </Grid>
            </Grid>
            {!s.reviewed && (p.review_section?.allowed ? (
              <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
                {ed === undefined ? (<>
                  <Button variant="contained" color="success" disabled={act.isPending} onClick={() => review(name, "accept")}>Accept</Button>
                  <Button variant="outlined" onClick={() => setEditing({ ...editing, [name]: s.text })}>Amend</Button>
                  <Button variant="outlined" color="error" disabled={act.isPending} onClick={() => review(name, "reject")}>Reject</Button></>)
                  : (<><Button variant="contained" disabled={act.isPending || !ed.trim()} onClick={() => review(name, "amend", ed)}>Save amended text</Button>
                    <Button onClick={() => setEditing({ ...editing, [name]: undefined })}>Cancel</Button></>)}
              </Stack>) : <Box sx={{ mt: 1 }}><Denied reason={p.review_section?.reason} /></Box>)}
          </Section>);
      })}
    </Stack>
  );
}

// ---------------------------------------------------------------- Request & pricing
export function RequestTab({ d }: P) {
  const st = d.state, lr = st.lending_request, act = useAct(d.sid), p = d.permissions;
  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, md: 7 }}>
        <Section title="Lending request" sub="As proposed by the preparer (REQ-055..059)">
          {!lr ? <Empty>Not recorded yet.</Empty> : <KV rows={[
            ["Facility", lr.facility_type], ["Amount", fmtMoney(lr.amount)], ["Current limit", fmtMoney(lr.current_limit)],
            ["Purpose", lr.purpose], ["Change requested", lr.change_requested], ["Terms", lr.terms], ["Pricing", lr.pricing],
            ["Type-specific detail", lr.type_specific_detail], ["Preparer", lr.preparer]]} />}
        </Section>
      </Grid>
      <Grid size={{ xs: 12, md: 5 }}>
        <Section title="Pricing and terms authorisation" sub="Pricing authority only, never the preparer (BR-E02)">
          {st.pricing_authorised_by ? <Alert severity="success">Authorised by {st.pricing_authorised_by}</Alert>
            : !lr ? <Empty>Waiting for the lending request.</Empty>
            : p.authorise_pricing?.allowed ? (
              <ActionDialog button="Authorise pricing and terms" title="Authorise pricing and terms" submitLabel="Authorise"
                onSubmit={() => act.mutateAsync({ action: "authorise_pricing", body: { _prereq: d.prereq.pricing } })}>
                <Alert severity="info">You are authorising the request as proposed by <b>{lr.preparer}</b>.</Alert>
                <KV rows={[["Facility", lr.facility_type], ["Amount", fmtMoney(lr.amount)], ["Terms", lr.terms], ["Pricing", lr.pricing],
                  ["Utilisation", st.measures_detail?.utilisation_pct?.display], ["Security cover", st.measures_detail?.security_cover_x?.display]]} />
              </ActionDialog>)
            : <><Empty>Awaiting the pricing authority.</Empty><Denied reason={p.authorise_pricing?.reason} /></>}
        </Section>
      </Grid>
    </Grid>
  );
}

// ---------------------------------------------------------------- Submission
export function SubmissionTab({ d }: P) {
  const st = d.state, g = d.gate, act = useAct(d.sid), p = d.permissions;
  return (
    <Stack spacing={2}>
      <Section title="Submission to Credit" sub="Only the accountable case owner authorises (BR-E01)">
        {st.submitted ? (
          <Alert severity="success">Submitted {st.submitted.date} by {st.submitted.by} — pack version {st.submitted.pack_version},
            fingerprint <code>{st.submitted.sha256.slice(0, 16)}…</code><br /><Typography variant="caption">{st.submitted.receipt}</Typography></Alert>)
          : st.submission_authorised_by ? <Alert severity="info">Authorised by {st.submission_authorised_by}. Use <b>Run submission</b> above to transmit.</Alert>
          : !g ? <Empty>Run preparation first.</Empty> : (
            <Stack spacing={1.5}>
              <Stack direction="row" spacing={1} alignItems="center">
                {g.submission_may_be_authorised ? <CheckCircleIcon color="success" /> : <ErrorIcon color="error" />}
                <Typography>Gate <b>{g.result}</b>, completeness {g.completeness.display}{g.gaps.length ? ` — ${g.gaps.length} blocking gap(s) on the Gate tab` : ""}</Typography>
              </Stack>
              {p.authorise_submission?.allowed ? (
                <Box><ActionDialog button="Authorise submission" title="Authorise submission to Credit" submitLabel="Authorise submission"
                  disabled={!g.submission_may_be_authorised}
                  onSubmit={() => act.mutateAsync({ action: "authorise_submission", body: { _prereq: d.prereq.submission } })}>
                  <Alert severity="info">Gate {g.result} · completeness {g.completeness.display} · {Object.keys(st.sections ?? {}).length} accepted sections.
                    The pack will be stored as an unalterable version when transmitted.</Alert>
                </ActionDialog></Box>) : <Denied reason={p.authorise_submission?.reason} />}
            </Stack>)}
      </Section>
      <Section title="Pack versions" sub="Immutable once written (REQ-064)">
        {d.packs.length === 0 ? <Empty>None yet.</Empty> : (
          <Table size="small"><TableHead><TableRow><TableCell>Version</TableCell><TableCell>Created</TableCell><TableCell>By</TableCell><TableCell>Reason</TableCell><TableCell>SHA-256</TableCell></TableRow></TableHead>
            <TableBody>{d.packs.map((x) => (
              <TableRow key={x.id}><TableCell>{x.version}</TableCell><TableCell>{x.created_at.slice(0, 19)}</TableCell><TableCell>{x.created_by}</TableCell>
                <TableCell>{x.reason}</TableCell><TableCell><code>{x.sha256.slice(0, 16)}…</code></TableCell></TableRow>))}</TableBody></Table>)}
      </Section>
    </Stack>
  );
}

// ---------------------------------------------------------------- Credit
export function CreditTab({ d }: P) {
  const st = d.state, act = useAct(d.sid), p = d.permissions;
  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, md: 7 }}>
        <Section title="Credit queries" action={p.raise_query?.allowed && st.submitted && (
          <ActionDialog button="Raise query" title="Raise a Credit query" submitLabel="Raise query" variant="outlined"
            fields={[{ name: "text", label: "Query for the case owner", required: true, multiline: true }]}
            onSubmit={(v) => act.mutateAsync({ action: "raise_query", body: v })} />)}>
          {d.queries.length === 0 ? <Empty>No queries.</Empty> : (
            <Stack spacing={1.5}>{d.queries.map((q) => (
              <Box key={q.id} sx={{ border: 1, borderColor: "divider", borderRadius: 2, p: 1.5 }}>
                <Stack direction="row" justifyContent="space-between"><Typography variant="body2"><b>#{q.id}</b> {q.text}</Typography>
                  <Chip size="small" color={q.status === "resolved" ? "success" : "warning"} label={q.status} /></Stack>
                <Typography variant="caption" color="text.secondary">Raised by {q.raised_by} · owner {q.owner}</Typography>
                {q.status === "resolved" ? <Typography variant="body2" sx={{ mt: 0.5 }}>Resolution: {q.resolution}</Typography>
                  : p.resolve_query?.allowed && <ResolveQuery sid={d.sid} id={q.id} />}
              </Box>))}</Stack>)}
        </Section>
      </Grid>
      <Grid size={{ xs: 12, md: 5 }}>
        <Section title="Credit outcome" sub="Recorded only by a Credit Underwriter, from Credit's own assessment">
          {st.credit_outcome ? (<Stack spacing={1}>
              <Alert severity={st.credit_outcome === "declined" ? "error" : "success"}><b>{st.credit_outcome}</b> — {st.outcome_recorded_by}, {st.outcome_date}{st.credit_reference ? `, ref ${st.credit_reference}` : ""}</Alert>
              {(st.conditions ?? []).map((c: string, i: number) => <Typography key={i} variant="body2">Condition: {c}</Typography>)}</Stack>)
            : p.record_outcome?.allowed && st.submitted ? (
              <ActionDialog button="Record outcome" title="Record Credit outcome" submitLabel="Record outcome"
                fields={[{ name: "outcome", label: "Outcome", options: ["approved", "approved with conditions", "declined", "referred"] },
                         { name: "reference", label: "Credit reference" }, { name: "conditions", label: "Conditions (one per line)", multiline: true }]}
                onSubmit={(v) => act.mutateAsync({ action: "record_outcome", body: v })} />)
            : <Empty>{st.submitted ? "Awaiting Credit." : "Not submitted yet."}</Empty>}
        </Section>
      </Grid>
    </Grid>
  );
}

function ResolveQuery({ sid, id }: { sid: string; id: number }) {
  const act = useAct(sid);
  const [changed, setChanged] = useState(false);
  return (
    <Box sx={{ mt: 1 }}>
      <ActionDialog button="Resolve" title={`Resolve query #${id}`} submitLabel="Resolve" variant="outlined"
        fields={[{ name: "resolution", label: "Resolution", required: true, multiline: true }]}
        onSubmit={(v) => act.mutateAsync({ action: "resolve_query", body: { ...v, query_id: id, pack_changed: changed } })}>
        <FormControlLabel control={<Switch checked={changed} onChange={(e) => setChanged(e.target.checked)} />}
          label="The response changed the pack (creates a new pack version)" />
      </ActionDialog>
    </Box>
  );
}

// ---------------------------------------------------------------- Handoffs
export function HandoffsTab({ d }: P) {
  const st = d.state, act = useAct(d.sid), p = d.permissions;
  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, md: 7 }}>
        <Section title="Post-approval handoffs" sub="Start only after Credit's approval; approved terms pass unchanged (BR-P06, BR-P07)">
          {(st.handoffs ?? []).length === 0 ? <Empty>Handoffs start once approval is recorded and post-approval has run.</Empty> : (
            <Table size="small"><TableHead><TableRow><TableCell>Task</TableCell><TableCell>Status</TableCell><TableCell>Owner</TableCell><TableCell /></TableRow></TableHead>
              <TableBody>{st.handoffs.map((h: any, i: number) => (
                <TableRow key={i}><TableCell>{h.task}</TableCell>
                  <TableCell><Chip size="small" color={["complete", "closed"].includes(h.status) ? "success" : "default"} label={h.status} />{h.reason && <Typography variant="caption"> {h.reason}</Typography>}</TableCell>
                  <TableCell><Typography variant="caption">{h.owner}</Typography></TableCell>
                  <TableCell align="right">{p.update_handoff?.allowed && !["complete", "closed"].includes(h.status) && (
                    <ActionDialog button="Update" title={`Handoff: ${h.task}`} submitLabel="Update" variant="text"
                      fields={[{ name: "status", label: "Status", options: ["in progress", "complete", "closed"] }, { name: "reason", label: "Reason (required if closed)" }]}
                      onSubmit={(v) => act.mutateAsync({ action: "update_handoff", body: { ...v, kind: "handoff", idx: i } })} />)}</TableCell></TableRow>))}</TableBody></Table>)}
        </Section>
      </Grid>
      <Grid size={{ xs: 12, md: 5 }}>
        <Section title="Conditions of approval" sub="Satisfied with evidence before dependent steps (BR-P08)">
          {(st.conditions_status ?? []).length === 0 ? <Empty>None.</Empty> : (
            <Stack spacing={1}>{st.conditions_status.map((c: any, i: number) => (
              <Stack key={i} direction="row" spacing={1} alignItems="center" justifyContent="space-between">
                <Typography variant="body2">{c.condition}{c.evidence && <Typography component="span" variant="caption"> — evidence {c.evidence}</Typography>}</Typography>
                {c.status === "satisfied" ? <Chip size="small" color="success" label="satisfied" />
                  : p.update_handoff?.allowed ? (
                    <ActionDialog button="Mark satisfied" title={`Condition: ${c.condition}`} submitLabel="Mark satisfied" variant="outlined"
                      fields={[{ name: "evidence", label: "Evidence", required: true }]}
                      onSubmit={(v) => act.mutateAsync({ action: "update_handoff", body: { ...v, kind: "condition", idx: i } })} />)
                  : <Chip size="small" label="open" />}
              </Stack>))}</Stack>)}
          {st.next_review && <Alert severity="info" sx={{ mt: 2 }}>Next review due <b>{st.next_review.due}</b> ({st.next_review.cadence_months}-month cadence)</Alert>}
        </Section>
      </Grid>
    </Grid>
  );
}

// ---------------------------------------------------------------- Audit
export function AuditTab({ d }: P) {
  const q = useQuery({ queryKey: ["audit", d.sid], queryFn: () => api.audit(d.sid) });
  const [filter, setFilter] = useState("");
  const rows = (q.data?.events ?? []).filter((e) =>
    `${e.actor} ${e.action} ${e.tool ?? ""} ${JSON.stringify(e.detail ?? {})}`.toLowerCase().includes(filter.toLowerCase()));
  return (
    <Section title="Audit trail" sub="Append-only and hash-chained; the database refuses edits and deletes"
      action={q.data && <Chip color={q.data.chain.ok ? "success" : "error"} label={`${q.data.chain.events} events · chain ${q.data.chain.ok ? "intact" : `BROKEN at #${q.data.chain.broken_at}`}`} />}>
      {q.isLoading && <LinearProgress />}
      <TextField size="small" placeholder="Filter by person, agent, action or tool" value={filter} onChange={(e) => setFilter(e.target.value)} sx={{ mb: 1.5, width: { xs: "100%", sm: 380 } }} />
      <TableContainer sx={{ maxHeight: 620 }}><Table size="small" stickyHeader>
        <TableHead><TableRow><TableCell>#</TableCell><TableCell>When (UTC)</TableCell><TableCell>Who</TableCell><TableCell>What</TableCell></TableRow></TableHead>
        <TableBody>{rows.map((e, i) => (
          <TableRow key={i} hover><TableCell>{e.seq}</TableCell><TableCell sx={{ whiteSpace: "nowrap" }}>{e.at.slice(0, 19).replace("T", " ")}</TableCell>
            <TableCell><Chip size="small" variant="outlined" color={e.actor_type === "human" ? "primary" : "default"} label={e.actor_type} sx={{ mr: 1 }} />{e.actor}</TableCell>
            <TableCell>{e.action}{e.tool ? ` · ${e.tool}` : ""}{e.result_status ? ` → ${e.result_status}` : ""}
              {typeof e.detail?.label === "string" && <Typography component="span" variant="body2" color="text.secondary"> — {e.detail.label as string}</Typography>}
              {typeof e.detail?.reason === "string" && <Typography component="span" variant="body2" color="error"> — {e.detail.reason as string}</Typography>}</TableCell>
          </TableRow>))}</TableBody>
      </Table></TableContainer>
    </Section>
  );
}
