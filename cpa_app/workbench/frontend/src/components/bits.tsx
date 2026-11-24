import type { ReactNode } from "react";
import { Box, Card, CardContent, CardHeader, Chip, Typography } from "@mui/material";

export function GateChip({ gate }: { gate: string | null | undefined }) {
  const color = gate === "PASS" ? "success" : gate === "ADVISORY" ? "warning" : gate === "BLOCKED" || gate === "BLOCK" ? "error" : "default";
  return <Chip size="small" color={color} label={gate || "not run"} variant={gate ? "filled" : "outlined"} />;
}

export function RunChip({ state }: { state: string }) {
  const color = state === "running" || state === "waiting" ? "info" : state === "failed" || state === "interrupted" ? "error" : state === "finished" ? "success" : "default";
  return <Chip size="small" color={color} variant="outlined" label={state} />;
}

export function Section({ title, action, children, sub }: { title: ReactNode; action?: ReactNode; children: ReactNode; sub?: ReactNode }) {
  return (
    <Card sx={{ mb: 2 }}>
      <CardHeader title={title} subheader={sub} action={action} titleTypographyProps={{ variant: "h6", fontSize: 16 }}
        subheaderTypographyProps={{ variant: "body2" }} sx={{ pb: 0 }} />
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <Typography color="text.secondary" variant="body2">{children}</Typography>;
}

export function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <Box component="dl" sx={{ display: "grid", gridTemplateColumns: "minmax(140px, max-content) 1fr", gap: "6px 16px", m: 0 }}>
      {rows.map(([k, v]) => (
        <Box key={k} sx={{ display: "contents" }}>
          <Typography component="dt" variant="body2" color="text.secondary">{k}</Typography>
          <Typography component="dd" variant="body2" sx={{ m: 0 }}>{v ?? "—"}</Typography>
        </Box>
      ))}
    </Box>
  );
}
