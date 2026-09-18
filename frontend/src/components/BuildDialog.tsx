import { useState } from "react";
import { FileText, Github, Globe2, Play, X } from "lucide-react";

type Props = {
  open: boolean;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onBuild: (goal: string) => void;
};

export default function BuildDialog({ open, loading, error, onClose, onBuild }: Props) {
  const [goal, setGoal] = useState(
    "Every morning, research new AI developments, find the ones relevant to my project, verify them, and prepare GitHub issues for my approval.",
  );

  if (!open) return null;

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="build-dialog" onMouseDown={(event) => event.stopPropagation()}>
        <div className="build-dialog-header">
          <div>
            <div className="section-kicker">NEW SYSTEM</div>
            <h2>What should the system do?</h2>
            <p>Describe the outcome. Specloom will decide the agents, tools, control flow, and tests.</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <textarea
          className="goal-editor"
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          placeholder="Describe the job you want automated…"
          rows={5}
        />

        <div className="context-chips">
          <div><FileText size={14} /> Context files</div>
          <div><Globe2 size={14} /> Web sources</div>
          <div><Github size={14} /> GitHub</div>
        </div>

        {error && <div className="build-error">{error}</div>}

        <div className="build-dialog-footer">
          <span>Current mode: deterministic architect</span>
          <button
            className="primary-button"
            disabled={loading || goal.trim().length < 10}
            onClick={() => onBuild(goal.trim())}
          >
            <Play size={15} fill="currentColor" />
            {loading ? "Building…" : "Build system"}
          </button>
        </div>
      </section>
    </div>
  );
}
