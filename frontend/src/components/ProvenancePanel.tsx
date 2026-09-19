import { useEffect, useState } from "react";
import { ArrowRight, FileText, ShieldCheck, TestTube2 } from "lucide-react";
import { getNodeProvenance, type NodeProvenance } from "../api";

type Props = { projectId: string; nodeId: string };

export default function ProvenancePanel({ projectId, nodeId }: Props) {
  const [data, setData] = useState<NodeProvenance | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getNodeProvenance(projectId, nodeId)
      .then((value) => { if (active) setData(value); })
      .catch(() => { if (active) setData(null); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [projectId, nodeId]);

  if (loading) {
    return <div className="provenance-loading"><span className="status-dot status-running" /> Tracing node provenance…</div>;
  }
  if (!data) {
    return <div className="provenance-empty">No provenance record is available for this node yet.</div>;
  }

  return (
    <div className="provenance-panel">
      <div className="provenance-block">
        <div className="inspector-section-title">Context basis</div>
        {data.requirements.length === 0 && data.constraints.length === 0 ? (
          <p className="provenance-muted">No direct requirement match was found.</p>
        ) : (
          <div className="provenance-items">
            {data.requirements.map((item) => (
              <div className="provenance-item" key={item.id}>
                <span className="provenance-kind">REQ</span>
                <div>
                  <strong>{item.statement}</strong>
                  {item.provenance?.[0]?.quote && <span>“{item.provenance[0].quote}” · {item.provenance[0].locator}</span>}
                </div>
              </div>
            ))}
            {data.constraints.map((item) => (
              <div className="provenance-item" key={item.id}>
                <span className="provenance-kind constraint">POLICY</span>
                <div>
                  <strong>{item.statement}</strong>
                  {item.provenance?.[0]?.quote && <span>“{item.provenance[0].quote}” · {item.provenance[0].locator}</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="provenance-block provenance-grid">
        <div>
          <div className="inspector-section-title"><FileText size={12} /> Sources</div>
          {data.sources.length ? data.sources.map((source) => (
            <div className="mini-reference" key={source.id}><span>{source.name}</span><em>{source.kind}</em></div>
          )) : <span className="provenance-muted">No linked source</span>}
        </div>
        <div>
          <div className="inspector-section-title"><ShieldCheck size={12} /> Policy</div>
          {data.policies.length ? data.policies.map((policy) => (
            <div className="mini-reference" key={String(policy.id)}><span>{String(policy.id)}</span><em>enforced</em></div>
          )) : <span className="provenance-muted">No explicit policy</span>}
        </div>
      </div>

      <div className="provenance-block">
        <div className="inspector-section-title"><TestTube2 size={12} /> Tests</div>
        {data.tests.length ? data.tests.map((test) => (
          <div className="mini-reference" key={String(test.id)}><span>{String(test.name)}</span><em>linked</em></div>
        )) : <span className="provenance-muted">No directly linked tests</span>}
      </div>

      <div className="provenance-block">
        <div className="inspector-section-title">Graph position</div>
        <div className="provenance-deps"><span>{data.dependencies.upstream.length} upstream</span><ArrowRight size={12} /><span>{data.dependencies.downstream.length} downstream</span></div>
      </div>
    </div>
  );
}
