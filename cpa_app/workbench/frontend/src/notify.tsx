import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Alert, Snackbar } from "@mui/material";
import { ApiError } from "./api";

type Note = { kind: "success" | "error" | "info"; text: string };
const Ctx = createContext<{ ok: (t: string) => void; fail: (e: unknown) => void }>({ ok: () => {}, fail: () => {} });
export const useNotify = () => useContext(Ctx);

export function NotifyProvider({ children }: { children: ReactNode }) {
  const [note, setNote] = useState<Note | null>(null);
  const ok = useCallback((text: string) => setNote({ kind: "success", text }), []);
  const fail = useCallback((e: unknown) => {
    const text = e instanceof ApiError ? (e.hint ? `${e.message} — ${e.hint}` : e.message) : String(e);
    setNote({ kind: "error", text });
  }, []);
  return (
    <Ctx.Provider value={{ ok, fail }}>
      {children}
      <Snackbar open={!!note} autoHideDuration={note?.kind === "error" ? 9000 : 4000} onClose={() => setNote(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}>
        {note ? <Alert severity={note.kind} variant="filled" onClose={() => setNote(null)} sx={{ maxWidth: 720 }}>{note.text}</Alert> : undefined}
      </Snackbar>
    </Ctx.Provider>
  );
}
