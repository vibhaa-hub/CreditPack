import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { CssBaseline, ThemeProvider, createTheme, useMediaQuery } from "@mui/material";

type Mode = "light" | "dark";
const ModeCtx = createContext<{ mode: Mode; toggle: () => void }>({ mode: "light", toggle: () => {} });
export const useColorMode = () => useContext(ModeCtx);

function stored(): Mode | null {
  try { return (localStorage.getItem("cpa-mode") as Mode) || null; } catch { return null; }
}

export function AppThemeProvider({ children }: { children: ReactNode }) {
  const prefersDark = useMediaQuery("(prefers-color-scheme: dark)");
  const [mode, setMode] = useState<Mode | null>(stored());
  const effective: Mode = mode ?? (prefersDark ? "dark" : "light");
  const theme = useMemo(() => createTheme({
    palette: {
      mode: effective,
      primary: { main: effective === "dark" ? "#7aa7ff" : "#1f5fbf" },
      secondary: { main: effective === "dark" ? "#c9a7ff" : "#6b3fa0" },
      background: effective === "dark" ? { default: "#121418", paper: "#1a1d23" } : { default: "#f4f6f9", paper: "#ffffff" },
    },
    shape: { borderRadius: 8 },
    typography: { fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif", h5: { fontWeight: 650 }, h6: { fontWeight: 600 } },
    components: {
      MuiCard: { defaultProps: { variant: "outlined" } },
      MuiTableCell: { styleOverrides: { head: { fontWeight: 600, fontSize: 12.5, textTransform: "uppercase", letterSpacing: ".03em" } } },
      MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { textTransform: "none" } } },
      MuiTab: { styleOverrides: { root: { textTransform: "none", minHeight: 44 } } },
    },
  }), [effective]);
  const toggle = () => {
    const next: Mode = effective === "dark" ? "light" : "dark";
    setMode(next);
    try { localStorage.setItem("cpa-mode", next); } catch { /* per-viewer convenience only */ }
  };
  return (
    <ModeCtx.Provider value={{ mode: effective, toggle }}>
      <ThemeProvider theme={theme}><CssBaseline />{children}</ThemeProvider>
    </ModeCtx.Provider>
  );
}
