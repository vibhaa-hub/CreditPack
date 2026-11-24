import { useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Box, Button, Card, CardActions, CardContent, Checkbox, Chip, Divider, FormControlLabel, Grid2 as Grid,
  Stack, TextField, Typography } from "@mui/material";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import ScienceIcon from "@mui/icons-material/Science";
import { api, ApiError } from "../api";
import { useNotify } from "../notify";

const ACCEPT = [".pdf", ".docx", ".xlsx", ".csv", ".txt", ".eml"];
const MAX = 20 * 1024 * 1024;

export default function NewCase() {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [runNow, setRunNow] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const nav = useNavigate();
  const qc = useQueryClient();
  const { ok } = useNotify();
  const samples = useQuery({ queryKey: ["samples"], queryFn: api.samples });
  const [opening, setOpening] = useState("");
  const openSample = async (name: string) => {
    setOpening(name); setError("");
    try {
      const r = await api.openSample(name);
      qc.invalidateQueries({ queryKey: ["cases"] });
      ok("Sample case opened — preparation agents started");
      nav(`/cases/${r.sid}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally { setOpening(""); }
  };

  const add = (list: FileList | null) => {
    if (!list) return;
    const next = [...files];
    for (const f of Array.from(list)) {
      const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
      if (!ACCEPT.includes(ext)) { setError(`${f.name}: file type not allowed`); continue; }
      if (f.size > MAX) { setError(`${f.name}: larger than 20 MB`); continue; }
      next.push(f);
    }
    setFiles(next);
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files); };

  const submit = async () => {
    setBusy(true); setError("");
    const form = new FormData();
    form.set("request_text", text);
    form.set("run_now", String(runNow));
    files.forEach((f) => form.append("files", f));
    try {
      const r = await api.createCase(form);
      qc.invalidateQueries({ queryKey: ["cases"] });
      ok(runNow ? "Case opened — preparation agents started" : "Case opened");
      nav(`/cases/${r.sid}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  };

  return (
    <Stack spacing={2} sx={{ maxWidth: 1000 }}>
      <Typography variant="h5">New case</Typography>
      {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}
      {(samples.data?.samples.length ?? 0) > 0 && (<>
        <Typography variant="h6" sx={{ fontSize: 16 }}>Start from a sample</Typography>
        <Typography variant="body2" color="text.secondary">Fictional cases with their documents. One click opens the case and starts the agents.</Typography>
        <Grid container spacing={2}>
          {samples.data!.samples.map((s) => (
            <Grid key={s.name} size={{ xs: 12, md: 6 }}>
              <Card sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
                <CardContent sx={{ flexGrow: 1 }}>
                  <Stack direction="row" spacing={1} alignItems="center"><ScienceIcon color="secondary" fontSize="small" />
                    <Typography fontWeight={600}>{s.title}</Typography></Stack>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>{s.summary}</Typography>
                  <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
                    {s.documents.map((d) => <Chip key={d} size="small" variant="outlined" label={d} />)}
                  </Stack>
                  {s.expect.length > 0 && (<Box sx={{ mt: 1 }}>
                    <Typography variant="caption" fontWeight={600}>What it should show</Typography>
                    {s.expect.map((x, i) => <Typography key={i} variant="caption" display="block" color="text.secondary">• {x}</Typography>)}
                  </Box>)}
                </CardContent>
                <CardActions><Button variant="contained" disabled={!!opening} onClick={() => openSample(s.name)}>
                  {opening === s.name ? "Opening…" : "Open this sample"}</Button></CardActions>
              </Card>
            </Grid>))}
        </Grid>
        <Divider sx={{ pt: 1 }}>or describe a new request</Divider>
      </>)}
      <Card><CardContent><Stack spacing={2.5}>
        <TextField label="Request" multiline minRows={8} value={text} onChange={(e) => setText(e.target.value)} required
          helperText="Who referred it, the dealer and registered number, case type(s), the accountable owner, what is requested and anything the dealer supplied." />
        <Box onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
          onClick={() => input.current?.click()}
          sx={{ border: 2, borderStyle: "dashed", borderColor: drag ? "primary.main" : "divider", borderRadius: 2, p: 3,
                textAlign: "center", cursor: "pointer", bgcolor: drag ? "action.hover" : "transparent" }}>
          <UploadFileIcon color="action" fontSize="large" />
          <Typography>Drop documents here or click to choose</Typography>
          <Typography variant="caption" color="text.secondary">PDF, Word, Excel, CSV, text or email — up to 20 MB each</Typography>
          <input ref={input} type="file" multiple hidden accept={ACCEPT.join(",")} onChange={(e) => add(e.target.files)} />
        </Box>
        {files.length > 0 && (
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {files.map((f, i) => <Chip key={i} label={`${f.name} · ${(f.size / 1024).toFixed(0)} KB`}
              onDelete={() => setFiles(files.filter((_, j) => j !== i))} />)}
          </Stack>
        )}
        <FormControlLabel control={<Checkbox checked={runNow} onChange={(e) => setRunNow(e.target.checked)} />}
          label="Start the preparation agents straight away" />
        <Box><Button variant="contained" size="large" onClick={submit} disabled={busy || !text.trim()}>Open case</Button></Box>
      </Stack></CardContent></Card>
    </Stack>
  );
}
