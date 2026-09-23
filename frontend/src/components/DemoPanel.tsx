import { useEffect, useState } from "react";
import { CheckCircle2, Circle, Loader2, Smartphone, X, XCircle } from "lucide-react";
import { getRun, type RunRecord } from "../api";
import ProofList, { proofOf } from "./ProofList";

type Props = { projectId: string; runId: string; telegram: boolean; onClose: () => void };

function outputText(run: RunRecord | null): string {
  const output = run?.output as { output?: Array<{ text?: string }> } | null | undefined;
  return (output?.output ?? []).map((item) => item.text ?? "").join("\n\n");
}

function parseTable(text: string): string[][] {
  return text
    .split("\n")
    .filter((line) => line.trim().startsWith("|") && !/^\s*\|[\s:|-]+\|\s*$/.test(line))
    .map((line) => line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.replace(/【[^】]*】|\[\d+\]|\(?https?:\/\/\S+\)?/g, "").replace(/\*\*/g, "").trim()));
}

function sources(text: string): string[] {
  return Array.from(new Set(text.match(/https?:\/\/[^\s)】\]]+/g) ?? []));
}

export default function DemoPanel({ projectId, runId, telegram, onClose }: Props) {
  const [run, setRun] = useState<RunRecord | null>(null);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const result = await getRun(projectId, runId);
        if (!active) return;
        setRun(result.run);
        if (result.run.status === "completed" || result.run.status === "failed") return;
      } catch {
        // keep polling; the run record may not be visible for a moment
      }
      if (active) timer = setTimeout(poll, 3000);
    };
    void poll();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [projectId, runId]);

  const events = run?.events ?? [];
  const done = (node: string) => events.some((e) => e.node_id === node && e.status === "completed");
  const started = (node: string) => events.some((e) => e.node_id === node);
  const failed = run?.status === "failed";
  const approved = (run?.output as { approved?: boolean } | null | undefined)?.approved;
  const steps = [
    { label: "Reading 3 live product pages", state: done("fetch_and_summarize") ? "done" : "active" },
    {
      label: telegram ? "Waiting for your tap on Telegram" : "Waiting for approval in the app",
      state: done("approval") ? "done" : started("approval") ? "active" : "todo",
    },
    { label: "Returning the verified result", state: run?.status === "completed" ? "done" : done("approval") ? "active" : "todo" },
  ];
  const text = outputText(run);
  const table = parseTable(text);

  return (
    <div className="demo-panel" role="dialog" aria-label="Live demo">
      <div className="demo-panel-head">
        <span><Smartphone size={15}/> Live demo · approve from your phone</span>
        <button className="icon-button" onClick={onClose} aria-label="Close demo"><X size={14}/></button>
      </div>
      <ol className="demo-steps">
        {steps.map((step) => (
          <li key={step.label} className={`demo-step demo-step-${failed && step.state === "active" ? "failed" : step.state}`}>
            {failed && step.state === "active" ? <XCircle size={15}/> : step.state === "done" ? <CheckCircle2 size={15}/> : step.state === "active" ? <Loader2 size={15} className="spin"/> : <Circle size={15}/>}
            {step.label}
          </li>
        ))}
      </ol>
      {failed && <div className="demo-error">{run?.error ? String(run.error).slice(0, 300) : approved === false ? "Rejected." : "The run did not finish."}</div>}
      {run?.status === "completed" && table.length > 1 && (
        <div className="demo-result">
          <div className="demo-result-title">Verified result {approved ? "· approved" : ""}</div>
          <table>
            <thead><tr>{table[0].map((cell) => <th key={cell}>{cell}</th>)}</tr></thead>
            <tbody>{table.slice(1).map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody>
          </table>
          {proofOf(run?.output) ? <ProofList proof={proofOf(run?.output)!}/> : (
            <div className="demo-sources">
              {sources(text).map((url) => <a key={url} href={url} target="_blank" rel="noreferrer">{url.replace(/^https?:\/\//, "")}</a>)}
            </div>
          )}
        </div>
      )}
      {run?.status === "completed" && table.length <= 1 && text && <pre className="demo-raw">{text.replace(/\s*【[^】]*】/g, "")}</pre>}
    </div>
  );
}
