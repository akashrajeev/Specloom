import { useEffect, useState } from "react";
import { Activity, ChevronRight, Clock3 } from "lucide-react";
import { getRuns, getRun, type RunRecord } from "../api";

type Props = { projectId: string; refreshKey: number; onSelect?: (run: RunRecord) => void };

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function RunHistory({ projectId, refreshKey, onSelect }: Props) {
  const [runs, setRuns] = useState<RunRecord[]>([]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const refresh = async () => {
      try {
        const result = await getRuns(projectId, 8);
        if (!active) return;
        setRuns(result.runs);

        const running = result.runs.filter((run) => run.status === "running");
        if (running.length) {
          await Promise.all(
            running.map(async (run) => {
              try {
                const detail = await getRun(projectId, run.run_id);
                if (!active) return;
                setRuns((current) =>
                  current.map((item) =>
                    item.run_id === run.run_id ? detail.run : item,
                  ),
                );
              } catch {
                // Keep the last durable state visible when a poll fails transiently.
              }
            }),
          );
          if (active) timer = setTimeout(refresh, 3000);
        }
      } catch {
        if (active) setRuns([]);
      }
    };

    void refresh();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [projectId, refreshKey]);

  return (
    <div className="run-history">
      {runs.length === 0 ? (
        <div className="provenance-empty">No executions recorded yet.</div>
      ) : (
        runs.slice(0, 5).map((run) => (
          <button className="run-history-row run-history-button" key={run.run_id} onClick={() => onSelect?.(run)}>
            <div className="run-history-mark"><span className={"status-dot status-" + (run.status === "failed" ? "warning" : run.status === "waiting" ? "ready" : run.status === "running" ? "ready" : "verified")} /></div>
            <div className="run-history-copy">
              <strong>{run.kind === "simulation" ? "Simulation" : run.trigger === "schedule" ? "Scheduled" : "Runtime"} · {run.status}{run.trigger === "schedule" && typeof run.changed === "boolean" ? (run.changed ? " · changed" : " · no change") : ""}</strong>
              <span><Clock3 size={10} /> {formatTime(run.created_at)} · {run.events?.length ?? 0} events</span>
            </div>
            <ChevronRight size={13} className="run-history-arrow" />
          </button>
        ))
      )}
      {runs.length > 5 && <div className="run-history-footer"><Activity size={11} /> {runs.length} recent runs retained</div>}
    </div>
  );
}
