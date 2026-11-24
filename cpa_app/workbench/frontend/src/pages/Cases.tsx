import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Alert, Box, Card, Chip, InputAdornment, LinearProgress, Stack, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TextField, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import { api, label } from "../api";
import { GateChip, RunChip } from "../components/bits";

const STAGES = ["all", "new", "preparing", "awaiting people", "with Credit", "post-approval"];

export default function Cases() {
  const q = useQuery({ queryKey: ["cases"], queryFn: api.cases, refetchInterval: 15_000 });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const nav = useNavigate();
  const [text, setText] = useState("");
  const [stage, setStage] = useState("all");
  const rows = useMemo(() => (q.data?.cases ?? []).filter((c) =>
    (stage === "all" || c.stage === stage) &&
    `${c.case_id} ${c.dealer} ${c.owner}`.toLowerCase().includes(text.toLowerCase())), [q.data, stage, text]);

  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }} justifyContent="space-between">
        <Typography variant="h5">Cases</Typography>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
          <TextField size="small" placeholder="Search case, dealer, owner" value={text} onChange={(e) => setText(e.target.value)}
            InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} />
          <ToggleButtonGroup size="small" exclusive value={stage} onChange={(_, v) => v && setStage(v)}>
            {STAGES.map((s) => <ToggleButton key={s} value={s}>{label(s)}</ToggleButton>)}
          </ToggleButtonGroup>
        </Stack>
      </Stack>
      {q.isError && <Alert severity="error">{String(q.error)}</Alert>}
      <Card>
        {q.isFetching && <LinearProgress />}
        <TableContainer>
          <Table size="small">
            <TableHead><TableRow>
              <TableCell>Case</TableCell><TableCell>Dealer</TableCell><TableCell>Owner</TableCell><TableCell>Stage</TableCell>
              <TableCell>Gate</TableCell><TableCell>Agents</TableCell><TableCell>Waiting on</TableCell>
            </TableRow></TableHead>
            <TableBody>
              {rows.map((c) => (
                <TableRow key={c.sid} hover sx={{ cursor: "pointer" }} onClick={() => nav(`/cases/${c.sid}`)}>
                  <TableCell><Typography variant="body2" fontWeight={600}>{c.case_id ?? "not registered yet"}</Typography>
                    <Typography variant="caption" color="text.secondary">{c.types.join(", ")}</Typography></TableCell>
                  <TableCell>{c.dealer}</TableCell>
                  <TableCell>{c.owner}</TableCell>
                  <TableCell><Chip size="small" label={c.stage} /></TableCell>
                  <TableCell><GateChip gate={c.gate} /></TableCell>
                  <TableCell><RunChip state={c.run} /></TableCell>
                  <TableCell>
                    {c.waiting.slice(0, 2).map((w, i) => (
                      <Typography key={i} variant="caption" display="block">
                        <b>{me.data?.roles[w.role] ?? w.role}</b>: {w.item}</Typography>))}
                    {c.waiting.length > 2 && <Typography variant="caption" color="text.secondary">+{c.waiting.length - 2} more</Typography>}
                  </TableCell>
                </TableRow>
              ))}
              {!q.isLoading && rows.length === 0 && (
                <TableRow><TableCell colSpan={7}><Box sx={{ py: 3, textAlign: "center", color: "text.secondary" }}>No cases match.</Box></TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Card>
    </Stack>
  );
}
