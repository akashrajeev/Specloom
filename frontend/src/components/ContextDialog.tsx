import { useState } from "react";
import { FileCode2, FileText, Github, Globe2, Type, UploadCloud, X } from "lucide-react";
import { addFileContext, addGitHubContext, addTextContext, addUrlContext } from "../api";

type Props = {
  projectId: string;
  open: boolean;
  onClose: () => void;
  onAdded: () => void;
};

type Mode = "text" | "url" | "github" | "file";

export default function ContextDialog({ projectId, open, onClose, onAdded }: Props) {
  const [mode, setMode] = useState<Mode>("text");
  const [name, setName] = useState("Project brief");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const submit = async () => {
    setError(null);
    setLoading(true);
    try {
      if (mode === "text") {
        if (!text.trim()) throw new Error("Paste some context first.");
        await addTextContext(projectId, name.trim() || "Untitled context", text.trim());
      } else if (mode === "url") {
        if (!url.trim()) throw new Error("Enter a URL first.");
        await addUrlContext(projectId, url.trim(), name.trim() || undefined);
      } else if (mode === "github") {
        if (!url.trim()) throw new Error("Enter a GitHub repository URL first.");
        await addGitHubContext(projectId, url.trim(), name.trim() || undefined);
      } else {
        if (!file) throw new Error("Choose a PDF first.");
        await addFileContext(projectId, file);
      }
      onAdded();
      onClose();
      setText("");
      setUrl("");
      setFile(null);
    } catch (value) {
      setError(value instanceof Error ? value.message : "Context upload failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="context-dialog" onMouseDown={(event) => event.stopPropagation()}>
        <div className="build-dialog-header">
          <div>
            <div className="section-kicker">ADD CONTEXT</div>
            <h2>Give Specloom something to understand.</h2>
            <p>Context becomes requirements, constraints, tools, examples, and provenance before the system is built.</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>

        <div className="context-mode-tabs">
          <button className={mode === "text" ? "selected" : ""} onClick={() => setMode("text")}><Type size={14}/> Text</button>
          <button className={mode === "url" ? "selected" : ""} onClick={() => setMode("url")}><Globe2 size={14}/> URL</button>
          <button className={mode === "github" ? "selected" : ""} onClick={() => setMode("github")}><Github size={14}/> GitHub</button>
          <button className={mode === "file" ? "selected" : ""} onClick={() => setMode("file")}><FileText size={14}/> PDF</button>
        </div>

        {mode !== "file" && (
          <input className="context-name-input" value={name} onChange={(event) => setName(event.target.value)} placeholder="Source name" />
        )}

        {mode === "text" && (
          <textarea className="context-editor" value={text} onChange={(event) => setText(event.target.value)} placeholder="Paste project rules, product requirements, API behavior, examples, or anything Specloom should know…" rows={10} />
        )}

        {mode === "url" && (
          <input className="context-url-input" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/specification" />
        )}

        {mode === "github" && (
          <div className="context-github-hint">
            <FileCode2 size={18} />
            <div>
              <strong>Connect a repository</strong>
              <span>Specloom reads a bounded set of source files, README/config, and repository metadata without executing the code.</span>
              <input className="context-url-input" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://github.com/owner/repository" />
            </div>
          </div>
        )}

        {mode === "file" && (
          <label className="context-file-picker">
            <UploadCloud size={21} />
            <strong>{file ? file.name : "Choose a PDF"}</strong>
            <span>PDF sources are ingested and traced back to their original text.</span>
            <input type="file" accept="application/pdf,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </label>
        )}

        {error && <div className="build-error">{error}</div>}

        <div className="build-dialog-footer">
          <span>Source content stays behind the context boundary.</span>
          <button className="primary-button" disabled={loading} onClick={submit}>
            {loading ? "Ingesting…" : "Add context"}
          </button>
        </div>
      </section>
    </div>
  );
}
