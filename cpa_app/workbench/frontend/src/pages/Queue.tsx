import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Alert, Card, Chip, List, ListItemButton, ListItemIcon, ListItemText, Stack, Typography } from "@mui/material";
import TaskAltIcon from "@mui/icons-material/TaskAlt";
import AssignmentLateIcon from "@mui/icons-material/AssignmentLate";
import { api } from "../api";

export default function Queue() {
  const q = useQuery({ queryKey: ["queue"], queryFn: api.queue, refetchInterval: 15_000 });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const nav = useNavigate();
  const items = q.data?.items ?? [];
  return (
    <Stack spacing={2}>
      <Typography variant="h5">My queue</Typography>
      <Typography color="text.secondary" variant="body2">Everything waiting on your role, across all cases. Select an item to go straight to it.</Typography>
      {q.isError && <Alert severity="error">{String(q.error)}</Alert>}
      <Card>
        {items.length === 0 && !q.isLoading ? (
          <Stack alignItems="center" spacing={1} sx={{ py: 6, color: "text.secondary" }}>
            <TaskAltIcon color="success" fontSize="large" /><Typography>Nothing is waiting on you.</Typography>
          </Stack>
        ) : (
          <List disablePadding>
            {items.map((i, n) => (
              <ListItemButton key={n} divider onClick={() => nav(`/cases/${i.sid}/${i.tab}`)}>
                <ListItemIcon><AssignmentLateIcon color="warning" /></ListItemIcon>
                <ListItemText primary={i.item} secondary={`${i.case_id ?? "new case"} · ${i.dealer}`} />
                <Chip size="small" label={me.data?.roles[i.role] ?? i.role} sx={{ mr: 1 }} />
                <Chip size="small" variant="outlined" label={i.stage} />
              </ListItemButton>
            ))}
          </List>
        )}
      </Card>
    </Stack>
  );
}
