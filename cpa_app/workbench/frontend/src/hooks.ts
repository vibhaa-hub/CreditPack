import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CaseDetail } from "./api";
import { useNotify } from "./notify";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60_000, retry: false });

export const useCase = (sid: string) =>
  useQuery({ queryKey: ["case", sid], queryFn: () => api.case(sid),
             refetchInterval: (q) => (["running", "waiting"].includes((q.state.data as CaseDetail | undefined)?.status.state ?? "") ? 3000 : false) });

/** Live updates: the server pushes a 'change' event when the case's audit trail grows
 *  (agents working, or other people acting); we refetch the case, list and queue. */
export function useCaseStream(sid: string) {
  const qc = useQueryClient();
  useEffect(() => {
    const es = new EventSource(`/api/cases/${sid}/stream`);
    es.addEventListener("change", () => {
      qc.invalidateQueries({ queryKey: ["case", sid] });
      qc.invalidateQueries({ queryKey: ["audit", sid] });
      qc.invalidateQueries({ queryKey: ["cases"] });
      qc.invalidateQueries({ queryKey: ["queue"] });
    });
    return () => es.close();
  }, [sid, qc]);
}

/** A human-gate action; refreshes everything that depends on the case. */
export function useAct(sid: string) {
  const qc = useQueryClient();
  const { ok, fail } = useNotify();
  return useMutation({
    mutationFn: ({ action, body }: { action: string; body: Record<string, unknown> }) => api.act(sid, action, body),
    onSuccess: (r) => ok(r.message),
    onError: fail,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["case", sid] });
      qc.invalidateQueries({ queryKey: ["queue"] });
      qc.invalidateQueries({ queryKey: ["cases"] });
    },
  });
}

export function useRun(sid: string) {
  const qc = useQueryClient();
  const { ok, fail } = useNotify();
  return useMutation({
    mutationFn: (workflow: string) => api.run(sid, workflow),
    onSuccess: (r) => ok(r.message),
    onError: fail,
    onSettled: () => qc.invalidateQueries({ queryKey: ["case", sid] }),
  });
}
