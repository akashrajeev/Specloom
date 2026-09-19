import { useState } from "react";
import { FileText, Globe2, Type, UploadCloud, X } from "lucide-react";
import { addFileContext, addTextContext, addUrlContext } from "../api";

type Props = {
  open: boolean;
  onClose: () => void;
  onAdded: () => void;
};

type Mode = "text" | "url" | "file";

export default function ContextDialog({ open, onClose, onAdded }: Props) {
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
        await addTextContext("researchhunter", name.trim() || "Untitled context", text.trim());
      } else if (mode === "url") {
        if (!url.trim()) throw new Error("Enter a URL first.");
        await addUrlContext("researchhunter", url.trim(), name.trim() || undefined);
      } else {
        if (!file) throw new Error("Choose a PDF first.");
        await addFileContext("researchhunter", file);
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
