import { useEffect, useState } from "react";
import { FileText, Github, Globe2, Play, ShieldAlert, X } from "lucide-react";
import type { BuildGap } from "../api";

type Props = {
  open: boolean;
  loading: boolean;
  error: string | null;
  gaps: BuildGap[];
  architectMode: string;
  onClose: () => void;
  onBuild: (goal: string, gapAnswers: Record<string, string>) => void;
  initialGoal?: string;
};

export default function BuildDialog({ open, loading, error, gaps, architectMode, onClose, onBuild, initialGoal }: Props) {
  const [goal, setGoal] = useState(
    initialGoal ?? "Describe the problem or outcome you want automated. Specloom will determine the agents, tools, control flow, approvals, and tests.",
  );
  const [answers, setAnswers] = useState<Record<string, string>>({});

  useEffect(() => {
    setAnswers({});
  }, [gaps]);

  useEffect(() => {
    if (open && initialGoal) setGoal(initialGoal);
  }, [open, initialGoal]);

  if (!open) return null;

  const blockingGaps = gaps.filter((gap) => gap.severity === "blocking");
  const allAnswered = blockingGaps.every((gap) => answers[gap.id]?.trim());

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className={"build-dialog " + (gaps.length ? "build-dialog-gaps" : "")} onMouseDown={(event) => event.stopPropagation()}>
        <div className="build-dialog-header">
          <div>
            <div className="section-kicker">{gaps.length ? "CONTEXT CHECK" : "NEW SYSTEM"}</div>
            <h2>{gaps.length ? "Specloom needs a little more context." : "What should the system do?"}</h2>
            <p>{gaps.length
              ? "The architect found information that could change the system. Resolve the blocking questions instead of letting it guess."
              : "Describe the outcome. Specloom will decide the agents, tools, control flow, and tests."}</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close"><X size={16} /></button>
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

        {gaps.length > 0 && (
          <div className="gap-list">
            <div className="gap-list-header">
              <div>
                <span className="section-kicker">MISSING INPUT</span>
                <strong>{gaps.length} context signal{gaps.length === 1 ? "" : "s"} found</strong>
              </div>
              <span className="gap-count"><ShieldAlert size={12} /> {blockingGaps.length} blocking</span>
            </div>
            {gaps.map((gap) => (
              <div className="gap-card" key={gap.id}>
                <div className={"gap-severity " + gap.severity}>{gap.severity}</div>
                <div className="gap-body">
                  <strong>{gap.question}</strong>
                  <span>{gap.category}{gap.related_requirement ? " · " + gap.related_requirement : ""}</span>
                  {gap.severity === "blocking" && (
                    <input
                      value={answers[gap.id] ?? ""}
                      onChange={(event) => setAnswers((current) => ({ ...current, [gap.id]: event.target.value }))}
                      placeholder="Answer this before Specloom builds the system…"
                    />
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className={loading && /Queued|Compiling|still running/.test(error) ? "build-progress" : "build-error"}>
            {loading && <span className="build-progress-dot" />}
            <span>{error}</span>
          </div>
        )}

        <div className="build-dialog-footer">
          <span>{loading ? "Running in the AWS compiler plane · this page can stay open." : gaps.length ? "Answers become traceable project context." : "Architect: " + architectMode}</span>
          <button
            className="primary-button"
            disabled={loading || goal.trim().length < 10 || (gaps.length > 0 && !allAnswered)}
            onClick={() => onBuild(goal.trim(), answers)}
          >
            <Play size={15} fill="currentColor" />
            {loading ? "Building…" : gaps.length ? "Continue build" : "Build system"}
          </button>
        </div>
      </section>
    </div>
  );
}
