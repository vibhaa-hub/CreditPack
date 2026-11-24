import { useState, type ReactNode } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField } from "@mui/material";

export type Field = { name: string; label: string; required?: boolean; multiline?: boolean; options?: string[]; initial?: string };

/** A button that opens a dialog collecting the fields an action needs, with the evidence the
 *  approver must see (`children`) shown above the form (Arch 3.4 minimum prerequisites). */
export default function ActionDialog({ button, title, fields = [], children, submitLabel = "Confirm", onSubmit,
  variant = "contained", disabled, color = "primary" }: {
  button: ReactNode; title: string; fields?: Field[]; children?: ReactNode; submitLabel?: string; disabled?: boolean;
  onSubmit: (values: Record<string, string>) => Promise<unknown>; variant?: "contained" | "outlined" | "text";
  color?: "primary" | "error" | "warning" | "success";
}) {
  const init = () => Object.fromEntries(fields.map((f) => [f.name, f.initial ?? f.options?.[0] ?? ""]));
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>(init);
  const [busy, setBusy] = useState(false);
  const missing = fields.some((f) => f.required && !values[f.name]?.trim());
  const submit = async () => {
    setBusy(true);
    try { await onSubmit(values); setOpen(false); } catch { /* reported by the caller's notifier */ } finally { setBusy(false); }
  };
  return (
    <>
      <Button size="small" variant={variant} color={color} disabled={disabled} onClick={() => { setValues(init()); setOpen(true); }}>{button}</Button>
      <Dialog open={open} onClose={() => !busy && setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{title}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            {children}
            {fields.map((f) => (
              <TextField key={f.name} label={f.label} required={f.required} multiline={f.multiline} minRows={f.multiline ? 4 : undefined}
                select={!!f.options} value={values[f.name] ?? ""} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
                {f.options?.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
              </TextField>
            ))}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)} disabled={busy}>Cancel</Button>
          <Button variant="contained" color={color} onClick={submit} disabled={busy || missing}>{submitLabel}</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
