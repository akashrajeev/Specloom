import { useEffect, useState } from "react";
import { Activity, CheckCircle2, Cloud, Database, ExternalLink, Globe2, LockKeyhole, Server, Zap } from "lucide-react";
import { getDeployCheck, getDeployStatus } from "../api";

type Props = {
  runtimeMode: string;
  storageMode: string;
};

const layers = [
  { label: "Frontend", service: "Amplify Hosting", icon: Globe2 },
  { label: "API", service: "API Gateway + Lambda", icon: Server },
  { label: "State", service: "DynamoDB", icon: Database },
  { label: "Sources", service: "S3", icon: Cloud },
  { label: "Schedules", service: "EventBridge", icon: Zap },
  { label: "Observability", service: "CloudWatch", icon: Activity },
];

export default function DeployView({ runtimeMode, storageMode }: Props) {
  const [check, setCheck] = useState<{
    ready: boolean;
    checks: Array<{ id: string; label: string; status: "pass" | "warn" | "fail"; detail?: string }>;
  } | null>(null);
  const [status, setStatus] = useState<{
    deployment: "live" | "ready" | "local";
    public_url: string | null;
    persistence_ready: boolean;
    runtime_ready: boolean;
    agentcore_runtime_arn: string | null;
    region: string | null;
  } | null>(null);

  useEffect(() => {
    getDeployStatus().then(setStatus).catch(() => setStatus(null));
    getDeployCheck("researchhunter").then(setCheck).catch(() => setCheck(null));
  }, []);

  const label =
    status?.deployment === "live"
      ? "Live"
      : status?.deployment === "ready"
        ? "AWS ready"
        : "Local";

  return (
    <div className="deploy-view">
      <div className="deploy-hero">
        <div>
          <div className="section-kicker">SHIP IT</div>
          <h2>Turn the generated system into an AWS service.</h2>
          <p>Specloom keeps the workflow definition portable while deployment supplies durable state, scheduling, execution, and observability.</p>
        </div>
        <div className={"deploy-state " + (status?.deployment === "live" ? "configured" : "ready")}>
          <span className="status-dot status-verified" />
          {label}
        </div>
      </div>

      <div className="deploy-grid">
        {layers.map(({ label: layer, service, icon: Icon }) => (
          <div className="deploy-card" key={layer}>
            <div className="deploy-card-icon"><Icon size={16} /></div>
            <div>
              <span>{layer}</span>
              <strong>{service}</strong>
            </div>
            <CheckCircle2 size={14} className="deploy-check" />
          </div>
        ))}
      </div>

      <div className="deploy-runtime">
        <div className="deploy-runtime-head">
          <div>
            <div className="inspector-section-title">Runtime profile</div>
            <p>The browser is reading deployment configuration from the control plane.</p>
          </div>
          <span className="deploy-badge"><LockKeyhole size={11} /> policy-bound</span>
        </div>
        <div className="deploy-runtime-row"><span>Runtime</span><strong>{runtimeMode}</strong></div>
        <div className="deploy-runtime-row"><span>Persistence</span><strong>{storageMode}</strong></div>
        <div className="deploy-runtime-row"><span>Runtime configured</span><strong>{status?.runtime_ready ? "yes" : "no"}</strong></div>
        <div className="deploy-runtime-row"><span>Persistence configured</span><strong>{status?.persistence_ready ? "yes" : "no"}</strong></div>
        <div className="deploy-runtime-row"><span>AWS region</span><strong>{status?.region ?? "not configured"}</strong></div>
        <div className="deploy-runtime-row"><span>AgentCore</span><strong>{status?.agentcore_runtime_arn ? "configured" : "deployment target"}</strong></div>
      </div>

      <div className="deploy-checks">
        <div className="deploy-runtime-head">
          <div>
            <div className="inspector-section-title">Deployment checks</div>
            <p>Promotion is gated by workflow validity and test results; infrastructure checks remain visible.</p>
          </div>
          <span className="deploy-badge"><LockKeyhole size={11} /> {check?.ready ? "candidate ready" : "checks pending"}</span>
        </div>
        {(check?.checks ?? []).map((item) => (
          <div className="deploy-check-row" key={item.id}>
            <span className={"deploy-check-icon " + item.status}>
              {item.status === "pass" ? "✓" : item.status === "warn" ? "!" : "×"}
            </span>
            <div><strong>{item.label}</strong><span>{item.detail ?? (item.status === "pass" ? "ok" : item.status === "warn" ? "configuration needed" : "must be fixed")}</span></div>
          </div>
        ))}
      </div>

      <div className="deploy-command">
        <div>
          <div className="inspector-section-title">Deploy from repository</div>
          <p>Build the SAM template, deploy the AWS control plane, then point Amplify at <code>frontend/</code>.</p>
        </div>
        <code>sam build &amp;&amp; sam deploy --guided</code>
      </div>

      <div className="deploy-note">
        {status?.public_url ? <ExternalLink size={13} /> : <Activity size={13} />}
        <span>
          {status?.public_url
            ? <>Live URL configured: <a href={status.public_url} target="_blank" rel="noreferrer">{status.public_url}</a></>
            : "No public URL is configured yet. The deployment manifest is ready, but the application is not claiming a live endpoint."}
        </span>
      </div>
    </div>
  );
}
