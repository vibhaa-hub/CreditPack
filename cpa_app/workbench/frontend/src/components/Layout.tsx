import { useState, type ReactNode } from "react";
import { Link as RouterLink, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppBar, Avatar, Badge, Box, Button, Chip, Container, Divider, IconButton, ListItemText, Menu, MenuItem,
  Toolbar, Tooltip, Typography } from "@mui/material";
import AccountBalanceIcon from "@mui/icons-material/AccountBalance";
import AddIcon from "@mui/icons-material/Add";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import LightModeIcon from "@mui/icons-material/LightMode";
import { api, type Me } from "../api";
import { useColorMode } from "../theme";

export default function Layout({ me, children }: { me: Me; children: ReactNode }) {
  const loc = useLocation();
  const qc = useQueryClient();
  const { mode, toggle } = useColorMode();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const queue = useQuery({ queryKey: ["queue"], queryFn: api.queue, refetchInterval: 20_000 });
  const n = queue.data?.items.length ?? 0;
  const initials = me.user.display_name.split(" ").map((p) => p[0]).join("").slice(0, 2);
  const nav = (to: string, text: ReactNode) => (
    <Button component={RouterLink} to={to} color="inherit"
      sx={{ opacity: loc.pathname === to ? 1 : 0.8, fontWeight: loc.pathname === to ? 650 : 500 }}>{text}</Button>
  );
  const signOut = async () => { await api.logout(); qc.clear(); window.location.href = "/login"; };

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="sticky" color="default" elevation={0} sx={{ borderBottom: 1, borderColor: "divider", bgcolor: "background.paper" }}>
        <Toolbar sx={{ gap: 1, flexWrap: "wrap" }}>
          <AccountBalanceIcon color="primary" />
          <Typography variant="h6" sx={{ mr: 2 }} component={RouterLink} to="/" color="inherit" style={{ textDecoration: "none" }}>
            Credit Pack Workbench
          </Typography>
          {nav("/", "Cases")}
          {nav("/queue", <Badge color="error" badgeContent={n} max={99}><Box sx={{ pr: n ? 1.5 : 0 }}>My queue</Box></Badge>)}
          <Box sx={{ flexGrow: 1 }} />
          {me.can.create_case && (
            <Button component={RouterLink} to="/cases/new" variant="contained" startIcon={<AddIcon />}>New case</Button>
          )}
          <Tooltip title={mode === "dark" ? "Light theme" : "Dark theme"}>
            <IconButton onClick={toggle} aria-label="toggle theme">{mode === "dark" ? <LightModeIcon /> : <DarkModeIcon />}</IconButton>
          </Tooltip>
          <IconButton onClick={(e) => setAnchor(e.currentTarget)} aria-label="account">
            <Avatar sx={{ width: 32, height: 32, bgcolor: "primary.main", fontSize: 14 }}>{initials}</Avatar>
          </IconButton>
          <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
            <Box sx={{ px: 2, py: 1 }}>
              <ListItemText primary={me.user.display_name} secondary={me.user.username} />
              <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap", mt: 0.5 }}>
                {me.user.roles.map((r) => <Chip key={r} size="small" label={me.roles[r] ?? r} />)}
              </Box>
            </Box>
            <Divider />
            <MenuItem onClick={signOut}>Sign out</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Container maxWidth="xl" sx={{ py: 3 }}>{children}</Container>
    </Box>
  );
}
