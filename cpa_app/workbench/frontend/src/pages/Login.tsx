import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Alert, Box, Button, Card, CardContent, Stack, TextField, Typography } from "@mui/material";
import AccountBalanceIcon from "@mui/icons-material/AccountBalance";
import { api, ApiError } from "../api";

export default function Login() {
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const nav = useNavigate();
  const [params] = useSearchParams();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      await api.login(username, password);
      await qc.invalidateQueries({ queryKey: ["me"] });
      const next = params.get("next");
      nav(next && next.startsWith("/") && next !== "/login" ? next : "/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed");
    } finally { setBusy(false); }
  };

  return (
    <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center", bgcolor: "background.default", p: 2 }}>
      <Card sx={{ width: "100%", maxWidth: 400 }}>
        <CardContent component="form" onSubmit={submit} sx={{ p: 4 }}>
          <Stack spacing={2.5}>
            <Stack direction="row" spacing={1} alignItems="center">
              <AccountBalanceIcon color="primary" />
              <Typography variant="h6">Credit Pack Workbench</Typography>
            </Stack>
            <Typography variant="body2" color="text.secondary">Sign in with your workbench account.</Typography>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField label="Username" value={username} onChange={(e) => setU(e.target.value)} autoComplete="username" autoFocus required />
            <TextField label="Password" type="password" value={password} onChange={(e) => setP(e.target.value)} autoComplete="current-password" required />
            <Button type="submit" variant="contained" size="large" disabled={busy}>Sign in</Button>
            <Typography variant="caption" color="text.secondary">Every action you take is recorded in the case audit trail under your name.</Typography>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}
