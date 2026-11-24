import { useNavigate, useParams } from "react-router-dom";
import { Alert, Box, Button, Card, CardContent, Chip, CircularProgress, LinearProgress, Stack, Step, StepLabel, Stepper,
  Tab, Tabs, Typography } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import SendIcon from "@mui/icons-material/Send";
import { useCase, useCaseStream, useRun } from "../hooks";
import { GateChip, RunChip } from "../components/bits";
import { AnalysisTab, AuditTab, ChecksTab, CreditTab, EvidenceTab, GateTab, HandoffsTab, NarrativeTab, RequestTab,
  SubmissionTab } from "../components/tabs";

const TABS = ["gate", "evidence", "checks", "analysis", "narrative", "request", "submission", "credit", "handoffs", "audit"] as const;

// preparation pipeline stages (Arch 3.3) and the agents that complete each one
const STAGES: [string, string[]][] = [
  ["Intake", ["intake_classifier"]],
  ["Evidence", ["entity_structure", "document_ingestion", "bureau_external", "dd_summary"]],
  ["Gaps", ["gap_consolidator"]],
  ["Request", ["pack_request"]],
  ["Analysis", ["financial_analysis"]],
  ["Drafting", ["nd_critic"]],
  ["Validation", ["pack_validation"]],
];

export default function CasePage() {
  const { sid = "", tab = "gate" } = useParams();
  const nav = useNavigate();
  useCaseStream(sid);
  const q = useCase(sid);
  const run = useRun(sid);
  if (q.isLoading) return <Box sx={{ display: "grid", placeItems: "center", py: 10 }}><CircularProgress /></Box>;
  if (q.isError || !q.data) return <Alert severity="error">{String(q.error ?? "Case not found")}</Alert>;
  const d = q.data, st = d.state, p = d.permissions, running = d.status.state === "running" || d.status.state === "waiting";
  const done = new Set(d.status.workflow === "preparation" || st.gate_status ? d.status.agents_completed : []);
  const prepDone = !!st.gate_status;
  const activeStage = prepDone ? STAGES.length : STAGES.findIndex(([, agents]) => !agents.every((a) => done.has(a)));
  const current = TABS.includes(tab as (typeof TABS)[number]) ? tab : "gate";

  return (
    <Stack spacing={2}>
      <Card>
        {running && <LinearProgress />}
        <CardContent>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} justifyContent="space-between" alignItems={{ md: "flex-start" }}>
            <Box>
              <Typography variant="h5">{st.case_id ?? "New case"} <Typography component="span" color="text.secondary" variant="h6">{st.dealer_name ? `· ${st.dealer_name}` : ""}</Typography></Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap alignItems="center">
                <Typography variant="body2" color="text.secondary">Owner <b>{d.owner}</b></Typography>
                {(st.case_types ?? []).map((t: string) => <Chip key={t} size="small" label={t} />)}
                <GateChip gate={st.gate_status} />
                <RunChip state={d.status.state} />
                {st.submitted && <Chip size="small" color="primary" label={`Submitted · pack v${st.submitted.pack_version}`} />}
                {st.credit_outcome && <Chip size="small" color="success" label={st.credit_outcome} />}
              </Stack>
            </Box>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {p.run_preparation?.allowed && !st.submitted && (
                <Button variant="outlined" startIcon={<PlayArrowIcon />} disabled={running || run.isPending}
                  onClick={() => run.mutate("preparation")}>{prepDone ? "Re-run preparation" : "Run preparation"}</Button>)}
              {p.run_submission?.allowed && st.submission_authorised_by && !st.submitted && (
                <Button variant="contained" startIcon={<SendIcon />} disabled={running || run.isPending}
                  onClick={() => run.mutate("submission")}>Run submission</Button>)}
              {p.run_post_approval?.allowed && ["approved", "approved with conditions"].includes(st.credit_outcome) && !st.handoffs?.length && (
                <Button variant="contained" startIcon={<PlayArrowIcon />} disabled={running || run.isPending}
                  onClick={() => run.mutate("post_approval")}>Run post-approval</Button>)}
            </Stack>
          </Stack>
          {(running || !prepDone) && (
            <Box sx={{ mt: 2, overflowX: "auto" }}>
              <Stepper activeStep={activeStage < 0 ? STAGES.length : activeStage} alternativeLabel>
                {STAGES.map(([name]) => <Step key={name}><StepLabel>{name}</StepLabel></Step>)}
              </Stepper>
              {running && <Typography variant="caption" color="text.secondary" sx={{ display: "block", textAlign: "center", mt: 1 }}>
                {d.status.workflow} running · {d.status.agents_completed.length} agent steps done
                {d.status.agents_completed.length ? ` · last: ${d.status.agents_completed.at(-1)}` : ""}</Typography>}
            </Box>
          )}
          {d.status.error && <Alert severity="error" sx={{ mt: 2 }}>Last run failed: {d.status.error}</Alert>}
          {d.status.state === "waiting" && <Alert severity="info" sx={{ mt: 2 }}>Waiting for {d.status.waiting_on}: no worker for that unit is running. The run continues when one starts.</Alert>}
          {d.status.state === "interrupted" && <Alert severity="warning" sx={{ mt: 2 }}>The last run was interrupted (its orchestrator stopped). Work up to the last completed agent is saved; run it again to continue.</Alert>}
        </CardContent>
        <Tabs value={current} onChange={(_, v) => nav(`/cases/${sid}/${v}`)} variant="scrollable" scrollButtons="auto"
          sx={{ borderTop: 1, borderColor: "divider", px: 1 }}>
          {TABS.map((t) => <Tab key={t} value={t} label={t[0].toUpperCase() + t.slice(1)} />)}
        </Tabs>
      </Card>
      <Box>
        {current === "gate" && <GateTab d={d} />}
        {current === "evidence" && <EvidenceTab d={d} />}
        {current === "checks" && <ChecksTab d={d} />}
        {current === "analysis" && <AnalysisTab d={d} />}
        {current === "narrative" && <NarrativeTab d={d} />}
        {current === "request" && <RequestTab d={d} />}
        {current === "submission" && <SubmissionTab d={d} />}
        {current === "credit" && <CreditTab d={d} />}
        {current === "handoffs" && <HandoffsTab d={d} />}
        {current === "audit" && <AuditTab d={d} />}
      </Box>
    </Stack>
  );
}
