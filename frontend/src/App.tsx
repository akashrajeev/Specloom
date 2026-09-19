import { useEffect, useMemo, useState } from "react";
import { activateVersion, approveRun, buildWorkflow, evaluateWorkflow, getConfig, getContext, getExampleWorkflow, getProject, getVersions, runWorkflow, simulateWorkflow, type BuildGap, type ContextGraph, type SimulationResult, type WorkflowVersion } from "./api";
import BuildDialog from "./components/BuildDialog";
import ProvenancePanel from "./components/ProvenancePanel";
import RunHistory from "./components/RunHistory";
import ContextDialog from "./components/ContextDialog";
import DeployView from "./components/DeployView";
import RunDetailDialog from "./components/RunDetailDialog";
import {
  Activity,
  Archive,
  ArrowRight,
  Bot,
  Check,
  ChevronDown,
  CircleAlert,
  Clock3,
  Code2,
  Database,
  FileCode2,
  FileText,
  GitBranch,
  GitPullRequest,
  Globe2,
  Layers3,
  LayoutDashboard,
  LockKeyhole,
  MoreHorizontal,
  Play,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  Users,
  Wrench,
  X,
} from "lucide-react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";

type Status = "verified" | "ready" | "running" | "warning";

type BuilderNodeData = {
  title: string;
  icon: "research" | "agent" | "tool" | "approval" | "output";
  status: Status;
  meta: string;
  detail: string;
};

const iconMap = {
  research: Globe2,
  agent: Bot,
  tool: Wrench,
  approval: Users,
  output: ArrowRight,
} as const;

function BuilderNode({ data }: NodeProps<Node<BuilderNodeData>>) {
  const Icon = iconMap[data.icon];
  return (
    <div className="flow-node">
      <Handle type="target" position={Position.Left} />
      <div className="flow-node-top">
        <div className="node-icon"><Icon size={15} strokeWidth={1.8} /></div>
        <span className={`status-dot status-${data.status}`} />
      </div>
      <div className="flow-node-title">{data.title}</div>
      <div className="flow-node-meta">{data.meta}</div>
      <div className="flow-node-detail">{data.detail}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { builderNode: BuilderNode };

function graphIconFor(type: string): BuilderNodeData["icon"] {
  if (type === "tool") return "tool";
  if (type === "human_approval") return "approval";
  if (type === "output") return "output";
  return type === "trigger" ? "research" : "agent";
}

function workflowToCanvas(workflow: Record<string, any>) {
  const all = [
    workflow.trigger
      ? { id: workflow.trigger.id, name: workflow.trigger.name, type: workflow.trigger.type, config: {}, description: workflow.trigger.description }
      : null,
    ...(workflow.nodes ?? []),
  ].filter(Boolean) as Array<{ id: string; name: string; type: string; config?: Record<string, unknown>; description?: string }>;

  const positions = all.map((_, index) => ({
    x: 60 + (index % 4) * 250,
    y: 130 + Math.floor(index / 4) * 190,
  }));

  return {
    nodes: all.map((node, index) => ({
      id: node.id,
      type: "builderNode",
      position: positions[index],
      data: {
        title: node.name,
        icon: graphIconFor(node.type),
        status: "ready" as Status,
        meta: `${node.type} · ${node.type === "tool" && node.config?.tool_ref ? "TOOL" : node.type === "human_approval" ? "PAUSE" : "READ"}`,
        detail: node.description ?? String(node.config?.role ?? node.config?.tool_ref ?? "Generated system node"),
      },
    })),
    edges: (workflow.edges ?? []).map((edge: { from: string; to: string; label?: string | null }) => ({
      id: `generated-${edge.from}-${edge.to}`,
      source: edge.from,
      target: edge.to,
      label: edge.label ?? undefined,
      animated: true,
    })),
  };
}

const initialNodes: Node<BuilderNodeData>[] = [
  {
    id:"research",
    type:"builderNode",
    position:{x:60,y:210},
    data:{title:"Research",icon:"research",status:"verified",meta:"Agent · READ",detail:"Search configured sources"},
  },
  {
    id:"relevance",
    type:"builderNode",
    position:{x:300,y:210},
    data:{title:"Relevance",icon:"agent",status:"verified",meta:"Agent · READ",detail:"Compare against project context"},
  },
  {
    id:"dedup",
    type:"builderNode",
    position:{x:540,y:105},
    data:{title:"Deduplicate",icon:"agent",status:"ready",meta:"Agent · LOCAL",detail:"Collapse similar findings"},
  },
  {
    id:"verify",
    type:"builderNode",
    position:{x:540,y:315},
    data:{title:"Verify",icon:"tool",status:"ready",meta:"Tool · READ",detail:"Confirm primary source metadata"},
  },
  {
    id:"approval",
    type:"builderNode",
    position:{x:790,y:210},
    data:{title:"Human Review",icon:"approval",status:"warning",meta:"Approval · PAUSE",detail:"Required before write"},
  },
  {
    id:"github",
    type:"builderNode",
    position:{x:1030,y:210},
    data:{title:"GitHub Issue",icon:"tool",status:"ready",meta:"Tool · WRITE",detail:"Create approved issue"},
  },
];

const initialEdges: Edge[] = [
  {id:"e1",source:"research",target:"relevance",animated:true},
  {id:"e2",source:"relevance",target:"dedup",animated:true},
  {id:"e3",source:"relevance",target:"verify",animated:true},
  {id:"e4",source:"dedup",target:"approval",animated:true},
  {id:"e5",source:"verify",target:"approval",animated:true},
  {id:"e6",source:"approval",target:"github",animated:true},
];

function App() {
  const [nodes, setNodes] = useState(initialNodes);
  const [edges, setEdges] = useState(initialEdges);
  const [selected, setSelected] = useState("relevance");
  const [tab, setTab] = useState<"system"|"context"|"tests"|"deploy">("system");
  const [running, setRunning] = useState(false);
  const [built, setBuilt] = useState(true);
  const [workflow, setWorkflow] = useState<Record<string, unknown> | null>(null);
  const [lastRun, setLastRun] = useState<SimulationResult | null>(null);
  const [buildOpen, setBuildOpen] = useState(false);
  const [buildLoading, setBuildLoading] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [buildGaps, setBuildGaps] = useState<BuildGap[]>([]);
  const [runRefreshKey, setRunRefreshKey] = useState(0);
  const [pendingRunId, setPendingRunId] = useState<string | null>(null);
  const [contextGraph, setContextGraph] = useState<ContextGraph | null>(null);
  const [config, setConfig] = useState<{ architect_mode: string; runtime_mode: string; storage_mode: string } | null>(null);
  const [workflowVersionCount, setWorkflowVersionCount] = useState(1);
  const [contextOpen, setContextOpen] = useState(false);
  const [selectedRun, setSelectedRun] = useState<import("./api").RunRecord | null>(null);
  const [evaluation, setEvaluation] = useState<{ status: string; passed: number; failed: number; tests: Array<{ test_id: string; name: string; status: string; message: string }> } | null>(null);
  const [versions, setVersions] = useState<WorkflowVersion[]>([]);

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selected),
    [nodes, selected],
  );

  useEffect(() => {
    getContext("researchhunter")
      .then((result) => setContextGraph(result.graph))
      .catch(() => setContextGraph(null));
    getConfig()
      .then((result) => setConfig(result))
      .catch(() => setConfig(null));
    getProject("researchhunter")
      .then((result) => {
        setWorkflowVersionCount(result.workflow_versions || 1);
        if (result.workflow) {
          setWorkflow(result.workflow);
          const canvas = workflowToCanvas(result.workflow);
          setNodes(canvas.nodes);
          setEdges(canvas.edges);
          if (canvas.nodes.length) setSelected(canvas.nodes[0].id);
          evaluateWorkflow("researchhunter", result.workflow)
            .then((value) => setEvaluation(value as { status: string; passed: number; failed: number; tests: Array<{ test_id: string; name: string; status: string; message: string }> }))
            .catch(() => setEvaluation(null));
        }
      })
      .catch(() => setWorkflowVersionCount(1));
    getVersions("researchhunter")
      .then((result) => setVersions(result.versions))
      .catch(() => setVersions([]));
  }, []);

  const handleBuild = async (goal: string, gapAnswers: Record<string, string> = {}) => {
    setBuildLoading(true);
    setBuildError(null);

    try {
      const result = await buildWorkflow("researchhunter", goal, gapAnswers);
      if (!result.ready || !result.workflow) {
        setBuildGaps(result.gaps ?? []);
        setBuildError("Resolve the blocking context questions below, then continue.");
        return;
      }
      setBuildGaps([]);
      setWorkflow(result.workflow);
      evaluateWorkflow("researchhunter", result.workflow)
        .then((value) => setEvaluation(value as { status: string; passed: number; failed: number; tests: Array<{ test_id: string; name: string; status: string; message: string }> }))
        .catch(() => setEvaluation(null));
      getContext("researchhunter").then((value) => setContextGraph(value.graph)).catch(() => {});
      getProject("researchhunter").then((value) => setWorkflowVersionCount(value.workflow_versions || 1)).catch(() => {});
      getVersions("researchhunter").then((value) => setVersions(value.versions)).catch(() => {});

      const canvas = workflowToCanvas(result.workflow);
      setNodes(canvas.nodes);
      setEdges(canvas.edges);

      setBuildOpen(false);
      setBuildGaps([]);
      setBuilt(true);
    } catch (error) {
      setBuildError(error instanceof Error ? error.message : "Build request failed");
    } finally {
      setBuildLoading(false);
    }
  };

  const runSystem = async () => {
    setRunning(true);
    setBuildError(null);
    try {
      const example = workflow ? { workflow } : await getExampleWorkflow();
      if (!workflow) setWorkflow(example.workflow);
      const result = await runWorkflow("researchhunter", example.workflow);
      setLastRun(result);
      setPendingRunId(result.status === "waiting" ? result.run_id ?? null : null);
      setRunRefreshKey((value) => value + 1);

      const completedIds = new Set(result.events.filter((event) => event.status === "completed").map((event) => event.node_id));
      const waitingIds = new Set(result.events.filter((event) => event.status === "waiting").map((event) => event.node_id));
      setNodes((current) => current.map((node) => ({
        ...node,
        data: {
          ...node.data,
          status: waitingIds.has(node.id) ? "warning" : completedIds.has(node.id) ? "verified" : node.data.status,
        },
      })));
    } catch (error) {
      setBuildError(error instanceof Error ? error.message : "Runtime execution failed");
    } finally {
      setRunning(false);
    }
  };

  const runSimulation = async () => {
    setRunning(true);
    setNodes((current) =>
      current.map((node, index) => ({
        ...node,
        data: {...node.data, status:index < 4 ? "running" : node.data.status},
      })),
    );

    try {
      const example = workflow
        ? { workflow }
        : await getExampleWorkflow();
      if (!workflow) setWorkflow(example.workflow);

      const result = await simulateWorkflow("researchhunter", example.workflow, false);
      setLastRun(result);
      setRunRefreshKey((value) => value + 1);
      setPendingRunId(result.status === "waiting" ? result.run_id ?? null : null);

      const completedIds = new Set(
        result.events.filter((event) => event.status === "completed").map((event) => event.node_id),
      );
      const failedId = result.failed_node;

      const waitingIds = new Set(
        result.events.filter((event) => event.status === "waiting").map((event) => event.node_id),
      );

      setNodes((current) =>
        current.map((node) => ({
          ...node,
          data: {
            ...node.data,
            status:
              node.id === failedId || waitingIds.has(node.id)
                ? "warning"
                : completedIds.has(node.id)
                  ? "verified"
                  : node.data.status === "running"
                    ? "ready"
                    : node.data.status,
          },
        })),
      );
    } catch (error) {
      setLastRun({
        project_id:"researchhunter",
        workflow_id:"unknown",
        status:"failed",
        events:[],
        output:null,
        failed_node:null,
        error:error instanceof Error ? error.message : "Simulation request failed",
        side_effects:[],
        metrics:{},
      });
      setNodes((current) =>
        current.map((node) => ({
          ...node,
          data: {...node.data, status: node.data.status === "running" ? "warning" : node.data.status},
        })),
      );
    } finally {
      setRunning(false);
    }
  };

  const approvePendingRun = async () => {
    if (!pendingRunId) return;
    setRunning(true);
    try {
      const result = await approveRun("researchhunter", pendingRunId);
      setLastRun(result);
      setPendingRunId(null);
      setRunRefreshKey((value) => value + 1);
      const completedIds = new Set(result.events.filter((event) => event.status === "completed").map((event) => event.node_id));
      setNodes((current) => current.map((node) => ({
        ...node,
        data: {
          ...node.data,
          status: completedIds.has(node.id) ? "verified" : node.data.status,
        },
      })));
    } catch (error) {
      setBuildError(error instanceof Error ? error.message : "Approval failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">S</div>
          <div>
            <div className="brand-name">Specloom</div>
            <div className="brand-sub">System compiler</div>
          </div>
        </div>

        <nav className="side-nav">
          <div className="nav-label">WORKSPACE</div>
          {([
            ["Projects", LayoutDashboard, true],
            ["Context", Layers3, false],
            ["Systems", GitBranch, false],
            ["Runs", Activity, false],
          ] as const).map(([label, Icon, active]) => (
            <button key={String(label)} className={`nav-item ${active ? "active" : ""}`}>
              <Icon size={16} />
              <span>{String(label)}</span>
              {label === "Projects" && <span className="nav-count">1</span>}
            </button>
          ))}

          <div className="nav-label nav-label-gap">CONFIGURE</div>
          {([
            ["Tools", Wrench],
            ["Permissions", ShieldCheck],
            ["Settings", Settings2],
          ] as const).map(([label, Icon]) => (
            <button key={String(label)} className="nav-item">
              <Icon size={16} />
              <span>{String(label)}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="workspace-card">
            <div className="workspace-avatar">AK</div>
            <div className="workspace-copy">
              <strong>Akash's Workspace</strong>
              <span>Developer</span>
            </div>
            <ChevronDown size={15} />
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Projects</span><span>/</span><strong>ResearchHunter</strong>
          </div>
          <div className="topbar-actions">
            <button className="ghost-button"><Search size={15}/> Search</button>
            <button className="icon-button"><MoreHorizontal size={17}/></button>
            <button className="avatar-button">AK</button>
          </div>
        </header>

        <section className="project-header">
          <div>
            <div className="eyebrow"><span className="live-pill">LIVE</span> ResearchHunter</div>
            <h1>Research new AI developments and prepare relevant GitHub issues.</h1>
            <p className="project-description">
              Watches configured research sources, verifies findings, and pauses for approval before any write.
            </p>
          </div>
          <div className="header-actions">
            <button className="secondary-button" onClick={() => setBuildOpen(true)}><Plus size={15}/> New system</button>
            <label className="version-control">
              <Archive size={14}/>
              <select
                value={versions.find((version) => version.active)?.version ?? workflowVersionCount}
                onChange={async (event) => {
                  const nextVersion = Number(event.target.value);
                  try {
                    const result = await activateVersion("researchhunter", nextVersion);
                    setWorkflow(result.workflow);
                    const canvas = workflowToCanvas(result.workflow);
                    setNodes(canvas.nodes);
                    setEdges(canvas.edges);
                    setSelected(canvas.nodes[0]?.id ?? "");
                    const refreshed = await getVersions("researchhunter");
                    setVersions(refreshed.versions);
                  } catch (error) {
                    setBuildError(error instanceof Error ? error.message : "Could not activate workflow version");
                  }
                }}
                aria-label="Workflow version"
              >
                {(versions.length ? versions : [{version: workflowVersionCount, workflow_id: "", name: "Current", active: true}]).map((version) => (
                  <option key={version.version} value={version.version}>Version {version.version}</option>
                ))}
              </select>
              <ChevronDown size={13}/>
            </label>
            <button className="primary-button" onClick={runSystem} disabled={running}>
              <Play size={15} fill="currentColor"/>{running ? "Running…" : "Run now"}
            </button>
          </div>
        </section>

        <div className="status-strip">
          <div className="status-block">
            <span className="status-key"><ShieldCheck size={14}/> System</span>
            <strong className="success-text">Verified</strong>
          </div>
          <div className="status-block">
            <span className="status-key"><Clock3 size={14}/> Schedule</span>
            <strong>Every day · 08:00</strong>
          </div>
          <div className="status-block">
            <span className="status-key"><Database size={14}/> Context</span>
            <strong>{contextGraph?.sources.length ?? 0} sources</strong>
          </div>
          <div className="status-block">
            <span className="status-key"><GitPullRequest size={14}/> Last run</span>
            <strong>2h ago · 18.4s</strong>
          </div>
          <div className="status-block status-block-right">
            <span className="status-key">RUNTIME</span>
            <strong>{config ? `${config.runtime_mode} · ${config.storage_mode}` : "loading…"}</strong>
          </div>
        </div>

        <div className="workspace">
          <section className="workspace-main">
            <div className="workspace-tabs">
              {(["system","context","tests","deploy"] as const).map((item) => (
                <button key={item} className={`workspace-tab ${tab===item ? "selected":""}`} onClick={() => setTab(item)}>
                  {item === "system" ? "System" : item === "context" ? "Context" : item === "tests" ? "Tests" : "Deploy"}
                  {item==="tests" && <span className="tab-badge">4</span>}
                </button>
              ))}
            </div>

            {tab === "system" && (
              <div className="canvas-wrap">
                <div className="canvas-toolbar">
                  <div className="canvas-title">
                    <span className="canvas-dot" />
                    Generated system
                    <span className="tiny-divider">·</span>
                    <span className="muted">{nodes.length} nodes</span>
                  </div>
                  <div className="toolbar-actions">
                    <button className="tiny-button"><Plus size={14}/> Node</button>
                    <button className="tiny-button"><Code2 size={14}/> IR</button>
                  </div>
                </div>
                <div className="flow-area">
                  <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    nodeTypes={nodeTypes}
                    fitView
                    fitViewOptions={{padding:0.22}}
                    nodesDraggable={false}
                    onNodeClick={(_, node) => setSelected(node.id)}
                    proOptions={{hideAttribution:true}}
                  >
                    <Background gap={22} size={1} color="#e8e8e3" />
                    <MiniMap
                      pannable
                      zoomable
                      nodeColor={(node) => node.id===selected ? "#111" : "#d5d5ce"}
                      maskColor="rgba(249,249,246,.82)"
                    />
                    <Controls showInteractive={false} />
                  </ReactFlow>
                </div>
              </div>
            )}

            {tab === "context" && (
              <div className="context-view">
                <div className="context-hero">
                  <div>
                    <div className="section-kicker">CONTEXT UNDERSTANDING</div>
                    <h2>Specloom understands before it builds.</h2>
                    <p>Sources are normalized into requirements, constraints, tools, examples, and provenance.</p>
                  </div>
                  <button className="secondary-button" onClick={() => setContextOpen(true)}><UploadCloud size={15}/> Add context</button>
                </div>
                <div className="context-metrics">
                  <div><strong>{contextGraph?.sources.length ?? 0}</strong><span>Sources</span></div>
                  <div><strong>{contextGraph?.requirements.length ?? 0}</strong><span>Requirements</span></div>
                  <div><strong>{contextGraph?.constraints.length ?? 0}</strong><span>Constraints</span></div>
                  <div><strong>{contextGraph?.tools.length ?? 0}</strong><span>Tools</span></div>
                </div>
                <div className="source-list">
                  {(contextGraph?.sources ?? []).map((source) => {
                    const Icon = source.kind === "github" ? GitBranch : source.kind === "pdf" ? FileText : FileCode2;
                    return (
                      <div className="source-row" key={source.id}>
                        <div className="source-icon"><Icon size={16}/></div>
                        <div><strong>{source.name}</strong><span>{source.kind}</span></div>
                        <span className="source-meta">ingested</span>
                        <Check size={15} className="source-check"/>
                      </div>
                    );
                  })}
                  {!contextGraph?.sources.length && <div className="provenance-empty">Add context to give Specloom more to compile against.</div>}
                </div>
              </div>
            )}

            {tab === "tests" && (
              <div className="tests-view">
                <div className="tests-head">
                  <div>
                    <div className="section-kicker">VALIDATION</div>
                    <h2>Tests generated from requirements.</h2>
                    <p>Specloom evaluates the current workflow before it is promoted to a deployable system.</p>
                  </div>
                  <button className="primary-button" onClick={runSimulation}><Play size={15} fill="currentColor"/> Simulate</button>
                </div>
                <div className="test-summary">
                  <div className="test-score">
                    <span className="score-number">{evaluation?.passed ?? 0}</span>
                    <span>/ {((evaluation?.passed ?? 0) + (evaluation?.failed ?? 0))} passed</span>
                  </div>
                  <div className="score-track">
                    <div
                      className="score-fill"
                      style={{ width: (((evaluation?.passed ?? 0) / Math.max(1, (evaluation?.passed ?? 0) + (evaluation?.failed ?? 0))) * 100) + "%" }}
                    />
                  </div>
                  <span className={evaluation?.failed ? "warning-text" : "success-text"}>
                    {evaluation?.status === "passed" ? "Ready to deploy" : evaluation ? "Needs repair" : "Evaluating…"}
                  </span>
                </div>
                {(evaluation?.tests ?? []).map((test) => (
                  <div className="test-row" key={test.test_id}>
                    <div className={"test-status " + (test.status === "passed" ? "" : "test-status-fail")}><Check size={14}/></div>
                    <div><strong>{test.name}</strong><span>{test.message}</span></div>
                    <span className={test.status === "passed" ? "test-pass" : "test-fail"}>{test.status.toUpperCase()}</span>
                  </div>
                ))}
                {!evaluation?.tests.length && <div className="provenance-empty">No workflow tests are currently attached.</div>}
              </div>
            )}

            {tab === "deploy" && (
              <DeployView
                runtimeMode={config?.runtime_mode ?? "local"}
                storageMode={config?.storage_mode ?? "memory"}
              />
            )}


          </section>

          <aside className="inspector">
            <div className="inspector-header">
              <div>
                <div className="section-kicker">SYSTEM INSPECTOR</div>
                <h3>{selectedNode?.data.title ?? "Select a node"}</h3>
              </div>
              <button className="icon-button"><X size={16}/></button>
            </div>

            {selectedNode && (
              <>
                <div className="inspector-status"><span className={`status-dot status-${selectedNode.data.status}`}/>{selectedNode.data.status === "warning" ? "Needs attention" : "Verified"}</div>
                <div className="inspector-card">
                  <div className="inspector-row"><span>Type</span><strong>{selectedNode.data.icon === "tool" ? "Tool" : "Agent"}</strong></div>
                  <div className="inspector-row"><span>Access</span><strong>{selectedNode.data.meta.split("·")[1]}</strong></div>
                  <div className="inspector-row"><span>Purpose</span><strong>{selectedNode.data.detail}</strong></div>
                </div>

                <div className="inspector-section">
                  <div className="inspector-section-title">Why does this exist?</div>
                  <ProvenancePanel projectId="researchhunter" nodeId={selectedNode.id} />
                </div>

                <div className="inspector-section">
                  <div className="inspector-section-title">Dependencies</div>
                  <div className="dependency"><Globe2 size={14}/><span>Graph upstream</span><em>{selectedNode.data.meta.split("·")[0]}</em></div>
                  <div className="dependency"><FileText size={14}/><span>Context + policy</span><em>BOUND</em></div>
                </div>

                <div className="inspector-section">
                  <div className="inspector-section-title">Recent execution</div>
                  {lastRun?.events.filter((event) => event.node_id === selectedNode.id).map((event) => (
                    <div className="execution-log" key={event.sequence}>
                      <span className="log-time">#{event.sequence}</span>
                      <span>{event.message}</span>
                    </div>
                  ))}
                  {!lastRun?.events.some((event) => event.node_id === selectedNode.id) && (
                    <span className="provenance-muted">No execution recorded for this node in the current session.</span>
                  )}
                </div>

                <div className="inspector-section">
                  <div className="inspector-section-title">Run history</div>
                  <RunHistory projectId="researchhunter" refreshKey={runRefreshKey} onSelect={setSelectedRun} />
                </div>
              </>
            )}

            <div className="inspector-footer">
              <button className="secondary-button full"><Settings2 size={15}/> Configure node</button>
            </div>
          </aside>
        </div>

        <div className={`bottom-runbar ${running ? "is-running" : ""}`}>
          <div className="runbar-left">
            <span className="runbar-icon"><Sparkles size={14}/></span>
            <div><strong>{running ? "Running system" : pendingRunId ? "Human approval required" : lastRun?.status === "passed" ? "Run completed" : lastRun?.status === "failed" ? "Run failed" : built ? "System ready" : "Build required"}</strong><span>{running ? "Executing generated graph…" : pendingRunId ? "The workflow is paused before the write-capable step." : lastRun?.error ?? "All required context and policies are present."}</span></div>
          </div>
          <div className="runbar-stats">
            <span><CircleAlert size={14}/> {lastRun?.status === "failed" ? 1 : 0} blockers</span>
            <span><ShieldCheck size={14}/> 3 policies</span>
            <span><LockKeyhole size={14}/> 1 approval gate</span>
            {pendingRunId && <button className="primary-button approval-action" onClick={approvePendingRun} disabled={running}><Check size={14}/> Approve & continue</button>}
            {pendingRunId && <button className="primary-button approval-action" onClick={approvePendingRun} disabled={running}><Check size={14}/> Approve & continue</button>}
          </div>
        </div>
        <ContextDialog
          open={contextOpen}
          onClose={() => setContextOpen(false)}
          onAdded={() => getContext("researchhunter").then((value) => setContextGraph(value.graph)).catch(() => {})}
        />
        <RunDetailDialog run={selectedRun} onClose={() => setSelectedRun(null)} />
        <BuildDialog
          open={buildOpen}
          loading={buildLoading}
          error={buildError}
          gaps={buildGaps}
          architectMode={config?.architect_mode ?? "showcase"}
          onClose={() => {
            if (!buildLoading) {
              setBuildOpen(false);
              setBuildError(null);
              setBuildGaps([]);
            }
          }}
          onBuild={handleBuild}
        />
      </main>
    </div>
  );
}

export default App;
