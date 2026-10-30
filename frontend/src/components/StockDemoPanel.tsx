import { useEffect, useState } from "react";
import { LineChart, Loader2, X } from "lucide-react";
import { approveStockOrder, requestStockApproval, type StockOrder, type StockProposal, type StockQuote } from "../api";

type Props = { onClose: () => void };

function message(e: unknown, fallback: string): string {
  if (!(e instanceof Error)) return fallback;
  try { return String(JSON.parse(e.message).detail ?? e.message); } catch { return e.message || fallback; }
}

function ago(seconds: number): string {
  if (seconds < 90) return `${seconds}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export default function StockDemoPanel({ onClose }: Props) {
  const [quotes, setQuotes] = useState<StockQuote[]>([]);
  const [proposal, setProposal] = useState<StockProposal | null>(null);
  const [source, setSource] = useState("");
  const [order, setOrder] = useState<StockOrder | null>(null);
  const [rejected, setRejected] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setBusy(true); setError(null); setOrder(null); setRejected(false); setProposal(null);
    try {
      const result = await requestStockApproval();
      setQuotes(result.quotes); setProposal(result.proposal); setSource(result.source);
    } catch (e) {
      setError(message(e, "Could not fetch quotes"));
    } finally { setBusy(false); }
  };
  useEffect(() => { void start(); }, []);

  const approve = async () => {
    if (!proposal) return;
    setBusy(true); setError(null);
    try { setOrder((await approveStockOrder(proposal.token)).order); setProposal(null); }
    catch (e) { setError(message(e, "Could not place the paper order")); }
    finally { setBusy(false); }
  };
  const money = (v: number, c: string) => `${c} ${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  const stale = quotes.some((q) => !q.fresh);

  return (
    <div className="demo-panel" role="dialog" aria-label="Stock price demo">
      <div className="demo-panel-head">
        <span><LineChart size={15}/> Stock price monitor · paper trading</span>
        <button className="icon-button" onClick={onClose} aria-label="Close demo"><X size={14}/></button>
      </div>
      {busy && !quotes.length && <p><Loader2 size={14} className="spin"/> Fetching live quotes…</p>}
      {quotes.length > 0 && (
        <div className="demo-result">
          <table>
            <thead><tr><th>Stock</th><th>Price</th><th>Day</th><th>Quote time</th></tr></thead>
            <tbody>{quotes.map((q) => (
              <tr key={q.symbol}><td>{q.symbol}</td><td>{money(q.price, q.currency)}</td><td>{q.change_pct > 0 ? "+" : ""}{q.change_pct}%</td><td>{ago(q.age_seconds)}{q.fresh ? "" : " · closed"}</td></tr>
            ))}</tbody>
          </table>
          <div className="demo-sources"><span>Source: {source}</span></div>
          {stale && <div className="demo-sources"><span>Some markets are closed, so their prices are the last trade, not live.</span></div>}
        </div>
      )}
      {proposal && (
        <div className="demo-decision">
          <p><strong>Approve a paper buy?</strong> {proposal.qty} × {proposal.symbol} at about {money(proposal.quote_price, proposal.currency)} (≈ {money(proposal.est_cost, proposal.currency)}). {proposal.reason}</p>
          {proposal.stale && <p>This market is closed, so the price is the last close, not live.</p>}
          <p>If the price moves more than {proposal.max_slippage_pct}% before you approve, the paper order is cancelled.</p>
          <p>Simulated only. No real money, no brokerage order.</p>
          <div className="demo-decision-actions">
            <button className="secondary-button" onClick={() => { setRejected(true); setProposal(null); }} disabled={busy}>Reject</button>
            <button className="primary-button" onClick={() => void approve()} disabled={busy}>{busy ? "Placing…" : "Approve paper buy"}</button>
          </div>
        </div>
      )}
      {order && (
        <div className="demo-result">
          <div className="demo-result-title">{order.mode}</div>
          <p>Bought {order.qty} × {order.symbol} at {money(order.fill_price, order.currency)}, total {money(order.total, order.currency)}. Price used was last traded {ago(order.quote_age_seconds)}{order.fresh ? "" : " (market closed or delayed)"}; it was {money(order.price_when_requested, order.currency)} when requested.</p>
        </div>
      )}
      {rejected && <div className="demo-sources"><span>Rejected. Nothing was bought.</span></div>}
      {error && <div className="demo-error">{error}</div>}
      {(order || rejected || error) && <button className="secondary-button" onClick={() => void start()} disabled={busy}>Run again</button>}
    </div>
  );
}
