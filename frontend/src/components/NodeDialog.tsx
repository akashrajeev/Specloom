import { useEffect, useState } from "react";
import { X, Wrench, Bot, GitBranch, ShieldCheck, Split, GitMerge } from "lucide-react";

type WorkflowNode = {
  id: string;
  type: string;
  name: string;
  description?: string | null;
  config?: Record<string, unknown>;
  policy_ref?: string | null;
  timeout_seconds?: number | null;
};

type Props = {
  open: boolean;
  node: WorkflowNode | null;
  mode: "add" | "edit";
  loading?: boolean;
  error?: string | null;
  onClose: () => void;
  onSave: (payload: {
    type?: string;
    name: string;
    description: string;
    config: Record<string, unknown>;
    policy_ref: string | null;
    timeout_seconds: number | null;
  }) => void;
};

const types = [
  ["agent", "Agent", Bot],
  ["tool", "Tool", Wrench],
  ["condition", "Condition", GitBranch],
  ["human_approval", "Human approval", ShieldCheck],
  ["parallel", "Parallel", Split],
  ["loop", "Loop", GitMerge],
  ["output", "Output", GitBranch],
] as const;

function defaults(type: string): Record<string, unknown> {
  if (type === "agent") return { role: "Task agent" };
  if (type === "tool") return { mode: "mock" };
  if (type === "condition") return { expression: "true" };
  if (type === "parallel") return { branches: [] };
  if (type === "loop") return { body: "", max_iterations: 3 };
  return {};
}

export default function NodeDialog({ open, node, mode, loading, error, onClose, onSave }: Props) {
  const [type, setType] = useState("agent");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [configText, setConfigText] = useState("{}");
  const [policyRef, setPolicyRef] = useState("");
  const [timeout, setTimeoutValue] = useState("");
  const [configError, setConfigError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const currentType = node?.type ?? "agent";
    setType(currentType);
    setName(node?.name ?? "New agent");
    setDescription(node?.description ?? "");
    setConfigText(JSON.stringify(node?.config ?? defaults(currentType), null, 2));
    setPolicyRef(node?.policy_ref ?? "");
    setTimeoutValue(node?.timeout_seconds ? String(node.timeout_seconds) : "");
    setConfigError(null);
  }, [open, node]);

  if (!open) return null;

  const save = () => {
    let config: Record<string, unknown>;
    try {
      const parsed = JSON.parse(configText || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Config must be a JSON object.");
      config = parsed as Record<string, unknown>;
    } catch (value) {
      setConfigError(value instanceof Error ? value.message : "Config must be valid JSON.");
      return;
    }

    onSave({
      type,
      name: name.trim() || "Untitled node",
      description: description.trim(),
      config,
      policy_ref: policyRef.trim() || null,
      timeout_seconds: timeout.trim() ? Number(timeout) : null,
    });
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="node-dialog" onMouseDown={(event) => event.stopPropagation()}>
        <div className="build-dialog-header">
          <div>
            <div className="section-kicker">NODE CONFIGURATION</div>
            <h2>{mode === "add" ? "Add a system node" : "Configure node"}</h2>
            <p>Change the executable contract while keeping the workflow validation boundary intact.</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close"><X size={16}/></button>
        </div>

        <div className="node-form">
          {mode === "add" && (
            <div className="node-type-grid">
              {types.map(([value, label, Icon]) => (
                <button key={value} className={type === value ? "node-type selected" : "node-type"} onClick={() => { setType(value); setConfigText(JSON.stringify(defaults(value), null, 2)); }}>
                  <Icon size={15}/>
                  <span>{label}</span>
                </button>
              ))}
            </div>
          )}

          <label className="form-field">
            <span>Name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>

          <label className="form-field">
            <span>Description</span>
            <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What this node is responsible for" />
          </label>

          <label className="form-field">
            <span>Configuration JSON</span>
            <textarea value={configText} onChange={(event) => setConfigText(event.target.value)} spellCheck={false} rows={9} />
          </label>

          <div className="form-grid">
            <label className="form-field">
              <span>Policy reference</span>
              <input value={policyRef} onChange={(event) => setPolicyRef(event.target.value)} placeholder="policy_id (optional)" />
            </label>
            <label className="form-field">
              <span>Timeout (seconds)</span>
              <input value={timeout} onChange={(event) => setTimeoutValue(event.target.value)} inputMode="numeric" placeholder="optional" />
            </label>
          </div>

          {(configError || error) && <div className="build-error">{configError || error}</div>}
        </div>

        <div className="build-dialog-footer">
          <span>{node ? `${node.id} · ${type}` : `Insert before the selected node · ${type}`}</span>
          <div className="modal-actions">
            <button className="secondary-button" onClick={onClose} disabled={loading}>Cancel</button>
            <button className="primary-button" onClick={save} disabled={loading}>{loading ? "Saving…" : mode === "add" ? "Add node" : "Save changes"}</button>
          </div>
        </div>
      </section>
    </div>
  );
}
