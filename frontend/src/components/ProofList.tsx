import { AlertTriangle, CheckCircle2, ExternalLink, XCircle } from "lucide-react";

export type ProofLine = {
  text: string;
  status: "supported" | "partial" | "not_found";
  source?: string | null;
  quote?: string | null;
  link?: string | null;
  missing?: string[];
};
export type Proof = { lines: ProofLine[]; supported: number; total: number; from_step?: string };

export function proofOf(output: unknown): Proof | null {
  const proof = (output as { proof?: Proof } | null | undefined)?.proof;
  return proof && Array.isArray(proof.lines) && proof.lines.length ? proof : null;
}

function highlight(quote: string, line: string) {
  const numbers = Array.from(new Set(line.match(/[£$€₹]?\d[\d,]*(?:\.\d+)?/g) ?? [])).filter((n) => quote.includes(n));
  if (!numbers.length) return quote;
  const pattern = new RegExp(`(${numbers.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
  return quote.split(pattern).map((part, i) => (numbers.includes(part) ? <mark key={i}>{part}</mark> : part));
}

export default function ProofList({ proof }: { proof: Proof }) {
  const allGood = proof.supported === proof.total;
  return (
    <div className="proof">
      <div className={`proof-head ${allGood ? "proof-ok" : "proof-warn"}`}>
        {allGood ? <CheckCircle2 size={13}/> : <AlertTriangle size={13}/>}
        Proof · {proof.supported}/{proof.total} lines backed by a quote from the page
      </div>
      <ol className="proof-lines">
        {proof.lines.map((line, i) => (
          <li key={i} className={`proof-line proof-${line.status}`}>
            <div className="proof-text">
              {line.status === "supported" ? <CheckCircle2 size={13}/> : line.status === "partial" ? <AlertTriangle size={13}/> : <XCircle size={13}/>}
              <span>{line.text}</span>
            </div>
            {line.quote && (
              <blockquote>
                "{highlight(line.quote, line.text)}"
              </blockquote>
            )}
            {line.status !== "supported" && (
              <div className="proof-note">
                {line.missing?.length ? `Not on the page: ${line.missing.join(", ")}` : "No matching quote found on the pages it read."}
              </div>
            )}
            {line.link && (
              <a href={line.link} target="_blank" rel="noreferrer">
                {line.status === "supported" ? "Open the quote" : "Open source"} <ExternalLink size={11}/>
                <span className="proof-host">{(line.source ?? "").replace(/^https?:\/\//, "").slice(0, 60)}</span>
              </a>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
