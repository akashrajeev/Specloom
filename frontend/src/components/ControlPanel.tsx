import { Settings2, ShieldCheck, Wrench, X, Database, Bot, LockKeyhole, GitBranch, LayoutDashboard, Plus } from "lucide-react";
import type { ProjectSummary } from "../api";

type Props = {
  kind: "projects" | "tools" | "permissions" | "settings";
  projects?: ProjectSummary[];
  currentProjectId?: string;
  onOpenProject?: (projectId: string) => void;
  onNewSystem?: () => void;
  config: Record<string, string> | null;
  tools: Array<{ id: string; name: string; capabilities: string[]; permissions: string[]; side_effecting?: boolean }>;
  workflow: Record<string, any> | null;
  onClose: () => void;
};

export default function ControlPanel({ kind, config, tools, workflow, projects = [], currentProjectId, onOpenProject, onNewSystem, onClose }: Props) {
  const titles = {
    projects: ["WORKSPACE", "Projects"],
    tools: ["CAPABILITY REGISTRY", "Tools available to this workspace"],
    permissions: ["POLICY & SAFETY", "Permissions and approval boundaries"],
    settings: ["CONTROL PLANE", "Runtime configuration for this deployment"],
  } as const;

  const Icon = kind === "projects" ? LayoutDashboard : kind === "tools" ? Wrench : kind === "permissions" ? ShieldCheck : Settings2;

  return (
    <div className="control-overlay" role="presentation" onMouseDown={onClose}>
      <section className="control-panel" onMouseDown={(event) => event.stopPropagation()}>
        <div className="control-panel-header">
          <div className="panel-title"><span className="panel-icon"><Icon size={16}/></span><div><div className="section-kicker">{titles[kind][0]}</div><h2>{titles[kind][1]}</h2></div></div>
          <button className="icon-button" onClick={onClose} aria-label="Close"><X size={16}/></button>
        </div>

        {kind === "projects" && (
          <div className="control-list">
            {projects.map((project) => (
              <button
                type="button"
                className={`control-list-row project-row ${project.project_id === currentProjectId ? "is-current" : ""}`}
                key={project.project_id}
                onClick={() => onOpenProject?.(project.project_id)}
              >
                <div className="control-row-icon"><GitBranch size={14}/></div>
                <div className="control-row-copy"><strong>{project.name}</strong><span>{project.project_id}</span><em>{project.goal ?? "No goal recorded"}</em></div>
                <span className="control-badge">{project.project_id === currentProjectId ? "OPEN" : `${project.node_count} nodes · v${project.workflow_versions}`}</span>
              </button>
            ))}
            {!projects.length && <div className="panel-empty">No built projects yet. Start with a new system.</div>}
            <button type="button" className="secondary-button full" onClick={onNewSystem}><Plus size={15}/> New system</button>
          </div>
        )}

        {kind === "tools" && (
          <div className="control-list">
            {tools.length ? tools.map((tool) => (
              <div className="control-list-row" key={tool.id}>
                <div className="control-row-icon"><Wrench size={14}/></div>
                <div className="control-row-copy"><strong>{tool.name}</strong><span>{tool.id}</span><em>{tool.capabilities.slice(0, 4).join(" · ") || "registered capability"}</em></div>
                <span className={tool.side_effecting ? "control-badge warning" : "control-badge"}>{tool.side_effecting ? "WRITE" : tool.permissions.join("/") || "READ"}</span>
              </div>
            )) : <div className="panel-empty">No tools are currently registered in this project context.</div>}
          </div>
        )}

        {kind === "permissions" && (
          <div className="control-list">
            <div className="control-summary-grid">
              <div><strong>{Array.isArray(workflow?.policies) ? workflow.policies.length : 0}</strong><span>Policies</span></div>
              <div><strong>{Array.isArray(workflow?.nodes) ? workflow.nodes.filter((node:any) => node.type === "human_approval").length : 0}</strong><span>Approval gates</span></div>
            </div>
            {(Array.isArray(workflow?.policies) ? workflow.policies : []).map((policy: any, index: number) => (
              <div className="control-list-row" key={String(policy.id ?? index)}>
                <div className="control-row-icon"><LockKeyhole size={14}/></div>
                <div className="control-row-copy"><strong>{String(policy.name ?? policy.id ?? `Policy ${index + 1}`)}</strong><span>{String(policy.id ?? "inline policy")}</span><em>{String(policy.description ?? "Workflow safety policy")}</em></div>
                <span className="control-badge">BOUND</span>
              </div>
            ))}
            {(!workflow?.policies || !workflow.policies.length) && <div className="panel-empty">No explicit workflow policies are attached. Side-effecting capabilities remain validator-gated.</div>}
          </div>
        )}

        {kind === "settings" && (
          <div className="settings-grid">
            <div className="setting-card"><Bot size={14}/><span>Architect</span><strong>{config?.architect_mode ?? "loading"}</strong></div>
            <div className="setting-card"><GitBranch size={14}/><span>Runtime</span><strong>{config?.runtime_mode ?? "loading"}</strong></div>
            <div className="setting-card"><Database size={14}/><span>Storage</span><strong>{config?.storage_mode ?? "loading"}</strong></div>
            <div className="setting-card"><ShieldCheck size={14}/><span>Auth</span><strong>{config?.auth_mode ?? "loading"}</strong></div>
          </div>
        )}
      </section>
    </div>
  );
}
