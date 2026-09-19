import { useEffect, useState } from "react";
import { Activity, ChevronRight, Clock3 } from "lucide-react";
import { getRuns, type RunRecord } from "../api";

type Props = { projectId: string; refreshKey: number };

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function RunHistory({ projectId, refreshKey }: Props) {
  const [runs, setRuns] = useState<RunRecord[]>([]);

  useEffect(() => {
    let active = true;
    getRuns(projectId, 8)
      .then((result) => { if (active) setRuns(result.runs); })
      .catch(() => { if (active) setRuns([]); });
    return () => { active = false; };
  }, [projectId, refreshKey]);

  return (
    <div className="run-history">
      {runs.length === 0 ? (
        <div className="provenance-empty">No executions recorded yet.</div>
      ) : (
        runs.slice(0, 5).map((run) => (
          <div className="run-history-row" key={run.run_id}>
            <div className="run-history-mark"><span className={"status-dot status-" + (run.status === "failed" ? "warning" : run.status === "waiting" ? "ready" : "verified")} /></div>
            <div className="run-history-copy">
              <strong>{run.kind === "simulation" ? "Simulation" : "Runtime"} · {run.status}</strong>
              <span><Clock3 size={10} /> {formatTime(run.created_at)} · {run.events?.length ?? 0} events</span>
            </div>
            <ChevronRight size={13} className="run-history-arrow" />
          </div>
        ))
      )}
      {runs.length > 5 && <div className="run-history-footer"><Activity size={11} /> {runs.length} recent runs retained</div>}
    </div>
  );
}
