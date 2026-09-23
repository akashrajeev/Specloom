import { useEffect, useRef, useState } from "react";
import { ArrowRight, ArrowUp, CheckCircle2, Circle, Clock3, Loader2 } from "lucide-react";
import type { DemoWorkflow, ProjectSummary } from "../api";

const STAGES = [
  "Reading your request",
  "Designing the workflow",
  "Checking structure and permissions",
  "Writing and running tests",
  "Deploying to AWS Step Functions",
];

const EXAMPLES = [
  {
    label: "Price watch",
    goal: "Every day at 8am, read https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html and https://books.toscrape.com/catalogue/soumission_998/index.html, summarize the price and availability, and ask me before sending the summary.",
  },
  {
    label: "Support triage",
    goal: "Classify incoming customer support requests by urgency, draft a helpful reply for each, and require my approval before anything urgent is sent.",
  },
  {
    label: "Daily research digest",
    goal: "Every weekday at 9am, find new AI research relevant to my project, rank it by relevance, and prepare a short digest for review.",
  },
];

type Props = {
  projects: ProjectSummary[];
  demos: DemoWorkflow[];
  building: boolean;
  buildMessage: string | null;
  onBuild: (goal: string) => void;
  onOpenProject: (projectId: string) => void;
};

export default function HomeScreen({ projects, demos, building, buildMessage, onBuild, onOpenProject }: Props) {
  const [goal, setGoal] = useState("");
  const [started, setStarted] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);
  useEffect(() => {
    if (!building) { setStarted(null); return; }
    setStarted((value) => value ?? Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [building]);

  // The build job only reports queued/compiling/complete, so the stage list advances with
  // elapsed time and always stops on the last unfinished step until the job really finishes.
  const elapsed = started ? Math.floor((now - started) / 1000) : 0;
  const activeStage = Math.min(STAGES.length - 1, Math.floor(elapsed / 18));
  const examples = [
    ...EXAMPLES,
    ...demos.filter((demo) => !EXAMPLES.some((item) => item.label.toLowerCase() === demo.name.toLowerCase())).slice(0, 2).map((demo) => ({ label: demo.name, goal: demo.goal })),
  ];
  const submit = () => { if (goal.trim().length >= 10 && !building) onBuild(goal.trim()); };

  return (
    <div className="home">
      <section className="home-hero">
        <h1>What should Specloom build?</h1>
        <p>Describe the job in plain English. Specloom asks about anything unclear, designs the workflow, tests it, and runs it on AWS.</p>
        <div className={`prompt-box ${building ? "is-building" : ""}`}>
          <textarea
            ref={inputRef}
            value={goal}
            disabled={building}
            onChange={(event) => setGoal(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit(); }}
            placeholder="e.g. Every morning at 8, check these product pages and tell me if any price dropped. Ask me before sending anything."
            rows={4}
          />
          <div className="prompt-foot">
            <span className="prompt-hint">{goal.trim().length < 10 ? "A sentence or two is enough" : "Ctrl + Enter to build"}</span>
            <button className="prompt-submit" onClick={submit} disabled={building || goal.trim().length < 10} aria-label="Build workflow">
              {building ? <Loader2 size={16} className="spin"/> : <ArrowUp size={16}/>}
              {building ? "Building" : "Build"}
            </button>
          </div>
        </div>
        {!building && (
          <div className="example-chips">
            {examples.map((example) => (
              <button key={example.label} className="example-chip" onClick={() => { setGoal(example.goal); inputRef.current?.focus(); }}>
                {example.label}
              </button>
            ))}
          </div>
        )}
        {building && (
          <ol className="build-progress" aria-live="polite">
            {STAGES.map((stage, index) => (
              <li key={stage} className={index < activeStage ? "done" : index === activeStage ? "active" : ""}>
                {index < activeStage ? <CheckCircle2 size={15}/> : index === activeStage ? <Loader2 size={15} className="spin"/> : <Circle size={15}/>}
                {stage}
              </li>
            ))}
            <li className="build-progress-note"><Clock3 size={13}/> {elapsed}s · {buildMessage ?? "Usually about two minutes"}</li>
          </ol>
        )}
        {!building && buildMessage && <p className="home-error">{buildMessage}</p>}
      </section>

      {projects.length > 0 && (
        <section className="home-projects">
          <h2>Your workflows</h2>
          <div className="project-grid">
            {projects.map((project) => (
              <button key={project.project_id} className="project-card" onClick={() => onOpenProject(project.project_id)}>
                <div className="project-card-top">
                  <strong>{project.name || project.project_id}</strong>
                  <ArrowRight size={14}/>
                </div>
                {project.goal ? <p>{project.goal}</p> : <p className="is-empty">Open to see the workflow graph and runs</p>}
                <div className="project-card-meta">
                  <span>{project.node_count} steps</span>
                  <span>{project.run_count} {project.run_count === 1 ? "run" : "runs"}</span>
                  <span>v{project.workflow_versions || 1}</span>
                </div>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
