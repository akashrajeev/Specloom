import { Activity, CheckCircle2, Cloud, Database, ExternalLink, Globe2, LockKeyhole, Server, Zap } from "lucide-react";

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
  const configured = runtimeMode !== "local" || storageMode !== "memory";

  return (
    <div className="deploy-view">
      <div className="deploy-hero">
        <div>
          <div className="section-kicker">SHIP IT</div>
          <h2>Turn the generated system into an AWS service.</h2>
          <p>Specloom keeps the workflow definition portable while the deployment layer supplies durable state, scheduling, execution, and observability.</p>
        </div>
        <div className={"deploy-state " + (configured ? "configured" : "ready")}>
          <span className="status-dot status-verified" />
          {configured ? "AWS mode configured" : "Deployment manifest ready"}
        </div>
      </div>

      <div className="deploy-grid">
        {layers.map(({ label, service, icon: Icon }) => (
          <div className="deploy-card" key={label}>
            <div className="deploy-card-icon"><Icon size={16} /></div>
            <div>
              <span>{label}</span>
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
            <p>The current browser is reading this from the control-plane configuration.</p>
          </div>
          <span className="deploy-badge"><LockKeyhole size={11} /> policy-bound</span>
        </div>
        <div className="deploy-runtime-row"><span>Runtime</span><strong>{runtimeMode}</strong></div>
        <div className="deploy-runtime-row"><span>Persistence</span><strong>{storageMode}</strong></div>
        <div className="deploy-runtime-row"><span>Agent execution</span><strong>{runtimeMode === "sagemaker" ? "SageMaker AI" : runtimeMode === "bedrock" ? "Bedrock / Strands" : "Deterministic"}</strong></div>
      </div>

      <div className="deploy-command">
        <div>
          <div className="inspector-section-title">Deploy from repository</div>
          <p>Build the SAM template, deploy the AWS control plane, then point Amplify at <code>frontend/</code>.</p>
        </div>
        <code>sam build &amp;&amp; sam deploy --guided</code>
      </div>

      <div className="deploy-note">
        <ExternalLink size={13} />
        <span>The repository contains the AWS deployment manifest; the live URL appears here once the stack is deployed and its frontend origin is configured.</span>
      </div>
    </div>
  );
}
