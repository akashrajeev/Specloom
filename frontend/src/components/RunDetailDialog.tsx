import { Activity, Check, Clock3, X } from "lucide-react";
import type { RunRecord } from "../api";

type Props = {
  run: RunRecord | null;
  onClose: () => void;
};

function statusClass(status: string) {
  if (status === "failed") return "warning";
  if (status === "waiting") return "ready";
  return "verified";
}

export default function RunDetailDialog({ run, onClose }: Props) {
  if (!run) return null;

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="run-detail-dialog" onMouseDown={(event) => event.stopPropagation()}>
        <div className="build-dialog-header">
          <div>
            <div className="section-kicker">EXECUTION TRACE</div>
            <h2>{run.kind === "simulation" ? "Simulation" : "Runtime"} · {run.status}</h2>
            <p>{run.run_id} · {new Date(run.created_at).toLocaleString()}</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>

        <div className="run-detail-summary">
          <div><span>Status</span><strong><span className={"status-dot status-" + statusClass(run.status)} /> {run.status}</strong></div>
          <div><span>Events</span><strong>{run.events?.length ?? 0}</strong></div>
          <div><span>Workflow</span><strong>{run.workflow_id}</strong></div>
        </div>

        <div className="run-timeline">
          {(run.events ?? []).map((event) => (
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

        {(run.error || run.output || run.side_effects?.length) && (
          <div className="run-detail-foot">
            {run.error && <div className="run-output run-output-error"><span>Error</span><strong>{run.error}</strong></div>}
            {run.output && <div className="run-output"><span>Output</span><pre>{JSON.stringify(run.output, null, 2)}</pre></div>}
            {run.side_effects?.length ? <div className="run-output"><span>Side effects</span><strong>{run.side_effects.length} recorded</strong></div> : null}
          </div>
        )}

        <div className="run-detail-footer"><Activity size={12} /> Trace is persisted with the project run record.</div>
      </section>
    </div>
  );
}
