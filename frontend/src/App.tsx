import { useMemo, useState } from "react";
import { getExampleWorkflow, simulateWorkflow, type SimulationResult } from "./api";
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

const sourceItems = [
  {name:"README.md",kind:"Repository",icon:FileCode2,meta:"18 requirements"},
  {name:"architecture.pdf",kind:"Document",icon:FileText,meta:"8 constraints"},
  {name:"GitHub API",kind:"API schema",icon:GitBranch,meta:"6 tools"},
  {name:"relevance.examples",kind:"Examples",icon:Archive,meta:"12 examples"},
];

function App() {
  const [nodes, setNodes] = useState(initialNodes);
  const [edges, setEdges] = useState(initialEdges);
  const [selected, setSelected] = useState("relevance");
  const [tab, setTab] = useState<"system"|"context"|"tests">("system");
  const [running, setRunning] = useState(false);
  const [built, setBuilt] = useState(true);
  const [workflow, setWorkflow] = useState<Record<string, unknown> | null>(null);
  const [lastRun, setLastRun] = useState<SimulationResult | null>(null);

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selected),
    [nodes, selected],
  );

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

      const result = await simulateWorkflow("researchhunter", example.workflow, true);
      setLastRun(result);

      const completedIds = new Set(
        result.events.filter((event) => event.status === "completed").map((event) => event.node_id),
      );
      const failedId = result.failed_node;

      setNodes((current) =>
        current.map((node) => ({
          ...node,
          data: {
            ...node.data,
            status:
              node.id === failedId
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
          {[
            ["Projects",LayoutDashboard,true],
            ["Context",Layers3,false],
            ["Systems",GitBranch,false],
            ["Runs",Activity,false],
          ].map(([label,Icon,active]) => (
            <button key={String(label)} className={`nav-item ${active ? "active" : ""}`}>
              <Icon size={16} />
              <span>{String(label)}</span>
              {label === "Projects" && <span className="nav-count">1</span>}
            </button>
          ))}

          <div className="nav-label nav-label-gap">CONFIGURE</div>
          {[
            ["Tools",Wrench],["Permissions",ShieldCheck],["Settings",Settings2],
          ].map(([label,Icon]) => (
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
            <button className="secondary-button"><Archive size={15}/> Version 4 <ChevronDown size={14}/></button>
            <button className="primary-button" onClick={runSimulation} disabled={running}>
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
            <strong>42 sources</strong>
          </div>
          <div className="status-block">
            <span className="status-key"><GitPullRequest size={14}/> Last run</span>
            <strong>2h ago · 18.4s</strong>
          </div>
          <div className="status-block status-block-right">
            <span className="status-key">AWS</span>
            <strong>Bedrock · AgentCore · S3</strong>
          </div>
        </div>

        <div className="workspace">
          <section className="workspace-main">
            <div className="workspace-tabs">
              {(["system","context","tests"] as const).map((item) => (
                <button key={item} className={`workspace-tab ${tab===item ? "selected":""}`} onClick={() => setTab(item)}>
                  {item === "system" ? "System" : item === "context" ? "Context" : "Tests"}
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
                    <span className="muted">6 nodes</span>
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
                  <button className="secondary-button"><UploadCloud size={15}/> Add context</button>
                </div>
                <div className="context-metrics">
                  <div><strong>42</strong><span>Sources</span></div>
                  <div><strong>18</strong><span>Requirements</span></div>
                  <div><strong>8</strong><span>Constraints</span></div>
                  <div><strong>6</strong><span>Tools</span></div>
                </div>
                <div className="source-list">
                  {sourceItems.map(({name,kind,icon:Icon,meta}) => (
                    <div className="source-row" key={name}>
                      <div className="source-icon"><Icon size={16}/></div>
                      <div><strong>{name}</strong><span>{kind}</span></div>
                      <span className="source-meta">{meta}</span>
                      <Check size={15} className="source-check"/>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {tab === "tests" && (
              <div className="tests-view">
                <div className="tests-head">
                  <div>
                    <div className="section-kicker">VALIDATION</div>
                    <h2>Tests generated from requirements.</h2>
                    <p>Side effects are sandboxed until the system passes.</p>
                  </div>
                  <button className="primary-button" onClick={runSimulation}><Play size={15} fill="currentColor"/> Simulate</button>
                </div>
                <div className="test-summary">
                  <div className="test-score"><span className="score-number">4</span><span>/ 4 passed</span></div>
                  <div className="score-track"><div className="score-fill"/></div>
                  <span className="success-text">Ready to deploy</span>
                </div>
                {[
                  ["Irrelevant paper","Reject content outside project scope","PASS"],
                  ["Duplicate paper","Collapse semantically duplicate findings","PASS"],
                  ["Approval gate","No GitHub write without human approval","PASS"],
                  ["Primary-source verification","Require source confirmation","PASS"],
                ].map(([name,desc,status]) => (
                  <div className="test-row" key={name}>
                    <div className="test-status"><Check size={14}/></div>
                    <div><strong>{name}</strong><span>{desc}</span></div>
                    <span className="test-pass">{status}</span>
                  </div>
                ))}
              </div>
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
                  <p>Generated from the requirement <strong>“Only return research relevant to the project.”</strong></p>
                  <button className="link-button">View provenance <ArrowRight size={14}/></button>
                </div>

                <div className="inspector-section">
                  <div className="inspector-section-title">Dependencies</div>
                  <div className="dependency"><Globe2 size={14}/><span>Web Search</span><em>READ</em></div>
                  <div className="dependency"><FileText size={14}/><span>Project Context</span><em>READ</em></div>
                </div>

                <div className="inspector-section">
                  <div className="inspector-section-title">Execution</div>
                  <div className="execution-log"><span className="log-time">08:02:14</span><span>Completed in 2.1s</span></div>
                  <div className="execution-log"><span className="log-time">Yesterday</span><span>11 candidates selected</span></div>
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
            <div><strong>{running ? "Running simulation" : lastRun?.status === "passed" ? "Simulation passed" : lastRun?.status === "failed" ? "Simulation failed" : built ? "System ready" : "Build required"}</strong><span>{running ? "Executing generated graph…" : lastRun?.error ?? "All required context and policies are present."}</span></div>
          </div>
          <div className="runbar-stats">
            <span><CircleAlert size={14}/> {lastRun?.status === "failed" ? 1 : 0} blockers</span>
            <span><ShieldCheck size={14}/> 3 policies</span>
            <span><LockKeyhole size={14}/> 1 approval gate</span>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
