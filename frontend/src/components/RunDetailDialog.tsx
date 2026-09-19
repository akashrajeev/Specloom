import { useEffect, useState } from "react";
import { Activity, Check, Clock3, X } from "lucide-react";
import { getRun, type RunRecord } from "../api";

type Props = {
  projectId: string;
  run: RunRecord | null;
  onClose: () => void;
};

function statusClass(status: string) {
  if (status === "failed") return "warning";
  if (status === "waiting" || status === "running") return "ready";
  return "verified";
}

export default function RunDetailDialog({ projectId, run, onClose }: Props) {
  const [currentRun, setCurrentRun] = useState<RunRecord | null>(run);

  useEffect(() => {
    setCurrentRun(run);
  }, [run]);

  useEffect(() => {
    if (!currentRun || currentRun.status !== "running") return;
    let active = true;
    const poll = async () => {
      try {
        const result = await getRun(projectId, currentRun.run_id);
        if (active) setCurrentRun(result.run);
      } catch {
        // Keep the latest durable snapshot visible during transient failures.
      }
    };
    const timer = setInterval(poll, 3000);
    void poll();
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [projectId, currentRun?.run_id, currentRun?.status]);

  if (!currentRun) return null;

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="run-detail-dialog" onMouseDown={(event) => event.stopPropagation()}>
        <div className="build-dialog-header">
          <div>
            <div className="section-kicker">EXECUTION TRACE</div>
            <h2>{currentRun.kind === "simulation" ? "Simulation" : "Runtime"} · {currentRun.status}</h2>
            <p>{currentRun.run_id} · {new Date(currentRun.created_at).toLocaleString()}</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>

        <div className="run-detail-summary">
          <div><span>Status</span><strong><span className={"status-dot status-" + statusClass(currentRun.status)} /> {currentRun.status}</strong></div>
          <div><span>Events</span><strong>{currentRun.events?.length ?? 0}</strong></div>
          <div><span>Workflow</span><strong>{currentRun.workflow_id}</strong></div>
        </div>

        <div className="run-timeline">
          {(currentRun.events ?? []).map((event) => (
            <div className="run-timeline-row" key={event.sequence + ":" + event.node_id}>
              <div className="run-timeline-seq">{event.sequence}</div>
              <div className="run-timeline-main">
                <div className="run-timeline-top">
                  <strong>{event.node_id}</strong>
                  <span><span className={"status-dot status-" + statusClass(event.status)} /> {event.status}</span>
                </div>
                <p>{event.message}</p>
              </div>
            </div>
          ))}
        </div>

        {(currentRun.error || currentRun.output || currentRun.side_effects?.length) && (
          <div className="run-detail-foot">
            {currentRun.error && <div className="run-output run-output-error"><span>Error</span><strong>{currentRun.error}</strong></div>}
            {currentRun.output && <div className="run-output"><span>Output</span><pre>{String(JSON.stringify(currentRun.output, null, 2))}</pre></div>}
            {currentRun.side_effects?.length ? <div className="run-output"><span>Side effects</span><strong>{currentRun.side_effects.length} recorded</strong></div> : null}
          </div>
        )}

        <div className="run-detail-footer"><Activity size={12} /> {currentRun.status === "running" ? "Durable execution is still running; the trace refreshes automatically." : "Trace is persisted with the project run record."}</div>
      </section>
    </div>
  );
}
