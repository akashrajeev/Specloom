import { useEffect, useState } from "react";
import { Check, Copy, FileCode2, X } from "lucide-react";

type Props = {
  open: boolean;
  workflow: Record<string, unknown> | null;
  loading?: boolean;
  error?: string | null;
  onClose: () => void;
  onSave: (workflow: Record<string, unknown>) => void;
};

export default function IRDialog({ open, workflow, loading, error, onClose, onSave }: Props) {
  const [text, setText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open) return;
    setText(workflow ? JSON.stringify(workflow, null, 2) : "{}");
    setParseError(null);
    setCopied(false);
  }, [open, workflow]);

  if (!open) return null;

  const format = () => {
    try {
      const parsed = JSON.parse(text);
      setText(JSON.stringify(parsed, null, 2));
      setParseError(null);
    } catch {
      setParseError("The current text is not valid JSON.");
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  const save = () => {
    try {
      const parsed = JSON.parse(text);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
      setParseError(null);
      onSave(parsed as Record<string, unknown>);
    } catch {
      setParseError("Fix the JSON before applying the workflow.");
    }
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="ir-dialog" onMouseDown={(event) => event.stopPropagation()}>
        <div className="build-dialog-header">
          <div>
            <div className="section-kicker">WORKFLOW IR</div>
            <h2>Edit the executable system definition</h2>
            <p>Changes are validated server-side before a new workflow version is created.</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close"><X size={16}/></button>
        </div>

        <div className="ir-toolbar">
          <div><FileCode2 size={14}/><span>WorkflowIR · schema-backed</span></div>
          <div className="modal-actions">
            <button className="tiny-button" onClick={format}>Format JSON</button>
            <button className="tiny-button" onClick={copy}>{copied ? <Check size={13}/> : <Copy size={13}/>} {copied ? "Copied" : "Copy"}</button>
          </div>
        </div>

        <textarea className="ir-editor" value={text} onChange={(event) => { setText(event.target.value); setParseError(null); }} spellCheck={false} />
        {(parseError || error) && <div className="build-error">{parseError || error}</div>}

        <div className="build-dialog-footer">
          <span>Server validation protects graph references and terminal output rules.</span>
          <div className="modal-actions">
            <button className="secondary-button" onClick={onClose} disabled={loading}>Cancel</button>
            <button className="primary-button" onClick={save} disabled={loading}>{loading ? "Validating…" : "Apply new version"}</button>
          </div>
        </div>
      </section>
    </div>
  );
}
