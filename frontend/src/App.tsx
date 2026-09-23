import { useEffect, useMemo, useRef, useState } from "react";
import { activateVersion, addNode, applyRepair, approveDurableRun, approveRun, startBuildAsync, getBuildJob, evaluateWorkflow, getConfig, getContext, getDemoWorkflows, getDurableApprovals, getExampleWorkflow, getProject, getRuns, getVersions, listProjects, rejectDurableRun, repairWorkflow, runWorkflow, simulateWorkflow, updateNode, updateNodeMode, updateWorkflow, type BuildGap, type ProjectSummary, type ContextGraph, type DurableApproval, type RepairCandidate, type SimulationResult, type WorkflowVersion } from "./api";
import BuildDialog from "./components/BuildDialog";
import ProvenancePanel from "./components/ProvenancePanel";
import RunHistory from "./components/RunHistory";
import ContextDialog from "./components/ContextDialog";
import DeployView from "./components/DeployView";
import RunDetailDialog from "./components/RunDetailDialog";
import NodeDialog from "./components/NodeDialog";
import IRDialog from "./components/IRDialog";
import ControlPanel from "./components/ControlPanel";
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
  Moon,
  Play,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
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
  useNodesInitialized,
  useReactFlow,
} from "@xyflow/react";

function FitOnChange({ signature }: { signature: string }) {
  const { fitView } = useReactFlow();
  const ready = useNodesInitialized();
  useEffect(() => {
    if (!signature || !ready) return;
    const id = window.setTimeout(() => { void fitView({ padding: 0.12, maxZoom: 1.1, minZoom: 0.25 }); }, 30);
    return () => window.clearTimeout(id);
  }, [signature, ready, fitView]);
  return null;
}

const NODE_TYPE_LABELS: Record<string, string> = { trigger: "Trigger", agent: "Agent", tool: "Tool", human_approval: "Approval", output: "Output", condition: "Condition" };
function nodeTypeLabel(meta: string) {
  const raw = meta.split(" · ")[0]?.trim() ?? "";
  return NODE_TYPE_LABELS[raw.toLowerCase()] ?? (raw ? raw[0].toUpperCase() + raw.slice(1) : "Node");
}

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

function projectSlug(goal: string): string {
  const slug = goal
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 42);
  return `system-${slug || "untitled"}-${Date.now().toString(36)}`;
}

function projectTitle(goal: string): string {
  const cleaned = goal.trim().replace(/[.!?]+$/, "");
  const words = cleaned.split(/\s+/).slice(0, 5);
  return words.length ? words.map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ") : "New System";
}

function triggerLabel(current: Record<string, unknown> | null): string {
  const trigger = current?.trigger as { config?: { mode?: string; cron?: string } } | undefined;
  if (!trigger?.config?.mode) return "Manual";
  if (trigger.config.mode === "schedule" && trigger.config.cron) return `Schedule · ${trigger.config.cron}`;
  return trigger.config.mode.charAt(0).toUpperCase() + trigger.config.mode.slice(1);
}

function layeredPositions(ids: string[], edges: Array<{ from?: string; to?: string }>, rootId?: string) {
  // Longest-path layering from the trigger so the graph reads left to right without crossings piling up.
  const depth = new Map<string, number>();
  ids.forEach((id) => depth.set(id, id === rootId ? 0 : -1));
  const valid = edges.filter((edge) => edge.from && edge.to && depth.has(edge.from) && depth.has(edge.to));
  if (rootId && depth.has(rootId)) depth.set(rootId, 0);
  for (let pass = 0; pass < ids.length; pass += 1) {
    let changed = false;
    for (const edge of valid) {
      const from = depth.get(edge.from as string) ?? -1;
      const to = depth.get(edge.to as string) ?? -1;
      if (from >= 0 && from + 1 > to) {
        depth.set(edge.to as string, from + 1);
        changed = true;
      }
    }
    if (!changed) break;
  }
  let fallback = Math.max(0, ...Array.from(depth.values())) + 1;
  ids.forEach((id) => { if ((depth.get(id) ?? -1) < 0) depth.set(id, fallback++); });
  const lanes = new Map<number, string[]>();
  ids.forEach((id) => {
    const layer = depth.get(id) ?? 0;
    lanes.set(layer, [...(lanes.get(layer) ?? []), id]);
  });
  const tallest = Math.max(1, ...Array.from(lanes.values()).map((lane) => lane.length));
  return ids.map((id) => {
    const layer = depth.get(id) ?? 0;
    const lane = lanes.get(layer) ?? [id];
    const index = lane.indexOf(id);
    const offset = ((tallest - lane.length) * 170) / 2;
    return { x: 40 + layer * 250, y: 80 + offset + index * 170 };
  });
}

const PROJECT_STORAGE_KEY = "specloom-project";

function initialProjectId(): string {
  const fromUrl = new URLSearchParams(window.location.search).get("project");
  if (fromUrl && /^[a-z0-9-]{1,80}$/.test(fromUrl)) return fromUrl;
  const stored = window.localStorage.getItem(PROJECT_STORAGE_KEY);
  return stored && /^[a-z0-9-]{1,80}$/.test(stored) ? stored : "researchhunter";
}

function workflowToCanvas(workflow: Record<string, any>) {
  const all = [
    workflow.trigger
      ? { id: workflow.trigger.id, name: workflow.trigger.name, type: workflow.trigger.type, config: {}, description: workflow.trigger.description }
      : null,
    ...(workflow.nodes ?? []),
  ].filter(Boolean) as Array<{ id: string; name: string; type: string; config?: Record<string, unknown>; description?: string }>;

  const positions = layeredPositions(all.map((node) => node.id), workflow.edges ?? [], workflow.trigger?.id);

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
  const [nodes, setNodes] = useState<typeof initialNodes>([]);
  const [edges, setEdges] = useState<typeof initialEdges>([]);
  const [projectId, setProjectId] = useState(initialProjectId);
  const [projectName, setProjectName] = useState("Loading project…");
  const [projectGoal, setProjectGoal] = useState("");
  const [projectLoading, setProjectLoading] = useState(true);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [recentRuns, setRecentRuns] = useState<import("./api").RunRecord[]>([]);
  const [selected, setSelected] = useState("");
  const [tab, setTab] = useState<"system"|"context"|"tests"|"deploy">("system");
  const [running, setRunning] = useState(false);
  const [built, setBuilt] = useState(false);
  const [workflow, setWorkflow] = useState<Record<string, unknown> | null>(null);
  const [lastRun, setLastRun] = useState<SimulationResult | null>(null);
  const [buildOpen, setBuildOpen] = useState(false);
  const [buildLoading, setBuildLoading] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [buildGaps, setBuildGaps] = useState<BuildGap[]>([]);
  const [runRefreshKey, setRunRefreshKey] = useState(0);
  const [pendingRunId, setPendingRunId] = useState<string | null>(null);
  const [contextGraph, setContextGraph] = useState<ContextGraph | null>(null);
  const [config, setConfig] = useState<Record<string, string> | null>(null);
  const [nodeDialogOpen, setNodeDialogOpen] = useState(false);
  const [nodeDialogMode, setNodeDialogMode] = useState<"add" | "edit">("edit");
  const [nodeMutationLoading, setNodeMutationLoading] = useState(false);
  const [irOpen, setIrOpen] = useState(false);
  const [irLoading, setIrLoading] = useState(false);
  const [controlPanel, setControlPanel] = useState<"projects" | "tools" | "permissions" | "settings" | null>(null);
  const [workflowVersionCount, setWorkflowVersionCount] = useState(1);
  const [contextOpen, setContextOpen] = useState(false);
  const [selectedRun, setSelectedRun] = useState<import("./api").RunRecord | null>(null);
  const [evaluation, setEvaluation] = useState<{ status: string; passed: number; failed: number; tests: Array<{ test_id: string; name: string; status: string; message: string }> } | null>(null);
  const [versions, setVersions] = useState<WorkflowVersion[]>([]);
  const [repairCandidate, setRepairCandidate] = useState<RepairCandidate | null>(null);
  const [repairLoading, setRepairLoading] = useState(false);
  const [pendingApproval, setPendingApproval] = useState<DurableApproval | null>(null);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [demos, setDemos] = useState<import("./api").DemoWorkflow[]>([]);
  const [demoGoal, setDemoGoal] = useState<string | undefined>(undefined);
  const [demoInput, setDemoInput] = useState<Record<string, unknown>>({});
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const stored = window.localStorage.getItem("specloom-theme");
    return stored === "dark" ? "dark" : "light";
  });

  const policyCount = Array.isArray((workflow as any)?.policies) ? (workflow as any).policies.length : 0;
  const approvalGateCount = Array.isArray((workflow as any)?.nodes)
    ? (workflow as any).nodes.filter((node: any) => node.type === "human_approval").length
    : 0;
  const blockerCount = (evaluation?.failed ?? 0) + (lastRun?.status === "failed" ? 1 : 0);

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selected),
    [nodes, selected],
  );

  const selectedIRNode = useMemo(() => {
    const current = workflow as {
      trigger?: { id: string; type: string; config?: Record<string, unknown> };
      nodes?: Array<{ id: string; type: string; config?: Record<string, unknown> }>;
    } | null;
    if (!current) return null;
    return [current.trigger, ...(current.nodes ?? [])].find((node) => node?.id === selected) ?? null;
  }, [workflow, selected]);

  const applyWorkflowState = async (nextWorkflow: Record<string, unknown>) => {
    setWorkflow(nextWorkflow);
    const canvas = workflowToCanvas(nextWorkflow);
    setNodes(canvas.nodes);
    setEdges(canvas.edges);
    setSelected(canvas.nodes[0]?.id ?? "");
    const [versionsResult, evaluationResult] = await Promise.allSettled([
      getVersions(projectId),
      evaluateWorkflow(projectId, nextWorkflow),
    ]);
    if (versionsResult.status === "fulfilled") {
      setVersions(versionsResult.value.versions);
      setWorkflowVersionCount(versionsResult.value.versions.length || 1);
    }
    if (evaluationResult.status === "fulfilled") {
      setEvaluation(evaluationResult.value as { status: string; passed: number; failed: number; tests: Array<{ test_id: string; name: string; status: string; message: string }> });
    }
  };

  const openAddNode = () => {
    if (!workflow) {
      setBuildError("Build a system before adding nodes.");
      return;
    }
    setNodeDialogMode("add");
    setNodeDialogOpen(true);
  };

  const openConfigureNode = () => {
    if (!selectedIRNode || !workflow) {
      setBuildError("Select a node to configure it.");
      return;
    }
    setNodeDialogMode("edit");
    setNodeDialogOpen(true);
  };

  const handleNodeSave = async (payload: {
    type?: string;
    name: string;
    description: string;
    config: Record<string, unknown>;
    policy_ref: string | null;
    timeout_seconds: number | null;
  }) => {
    setNodeMutationLoading(true);
    setBuildError(null);
    try {
      const result = nodeDialogMode === "add"
        ? await addNode(projectId, {
            type: payload.type ?? "agent",
            name: payload.name,
            description: payload.description,
            config: payload.config,
            policy_ref: payload.policy_ref,
            timeout_seconds: payload.timeout_seconds,
            before_node_id: selectedIRNode?.id ?? null,
          })
        : await updateNode(projectId, selectedIRNode?.id ?? "", payload);
      await applyWorkflowState(result.workflow);
      setNodeDialogOpen(false);
    } catch (error) {
      setBuildError(error instanceof Error ? error.message : "Could not save node");
    } finally {
      setNodeMutationLoading(false);
    }
  };

  const handleIRSave = async (nextWorkflow: Record<string, unknown>) => {
    setIrLoading(true);
    setBuildError(null);
    try {
      const result = await updateWorkflow(projectId, nextWorkflow);
      await applyWorkflowState(result.workflow);
      setIrOpen(false);
    } catch (error) {
      setBuildError(error instanceof Error ? error.message : "Workflow IR validation failed");
    } finally {
      setIrLoading(false);
    }
  };

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem("specloom-theme", theme);
  }, [theme]);

  useEffect(() => {
    getDemoWorkflows().then((result) => setDemos(result.demos)).catch(() => setDemos([]));
  }, []);

  useEffect(() => {
    getConfig()
      .then((result) => setConfig(result))
      .catch(() => setConfig(null));
  }, []);

  const refreshProjects = () => {
    listProjects().then((result) => setProjects(result.projects)).catch(() => setProjects([]));
  };

  useEffect(() => {
    refreshProjects();
  }, [projectId]);

  useEffect(() => {
    window.localStorage.setItem(PROJECT_STORAGE_KEY, projectId);
    const url = new URL(window.location.href);
    url.searchParams.set("project", projectId);
    window.history.replaceState(null, "", url);
  }, [projectId]);

  useEffect(() => {
    getRuns(projectId, 8)
      .then((result) => setRecentRuns(result.runs))
      .catch(() => setRecentRuns([]));
  }, [projectId, runRefreshKey]);

  useEffect(() => {
    let active = true;
    setProjectLoading(true);
    setLastRun(null);
    setEvaluation(null);
    setWorkflow(null);
    setNodes([]);
    setEdges([]);
    setSelected("");
    setBuilt(false);
    getContext(projectId)
      .then((result) => { if (active) setContextGraph(result.graph); })
      .catch(() => { if (active) setContextGraph(null); });
    getProject(projectId)
      .then((result) => {
        if (!active) return;
        setWorkflowVersionCount(result.workflow_versions || 1);
        const current = result.workflow as { name?: string; description?: string } | null;
        if (result.workflow && current) {
          setWorkflow(result.workflow);
          setProjectName(current.name || projectId);
          setProjectGoal(current.description || "");
          const canvas = workflowToCanvas(result.workflow);
          setNodes(canvas.nodes);
          setEdges(canvas.edges);
          setSelected(canvas.nodes[0]?.id ?? "");
          setBuilt(true);
          evaluateWorkflow(projectId, result.workflow)
            .then((value) => { if (active) setEvaluation(value as { status: string; passed: number; failed: number; tests: Array<{ test_id: string; name: string; status: string; message: string }> }); })
            .catch(() => { if (active) setEvaluation(null); });
        } else {
          setProjectName("New project");
          setProjectGoal("Describe a problem and Specloom will design the system.");
        }
      })
      .catch(() => {
        if (!active) return;
        setWorkflowVersionCount(1);
        setProjectName("Project unavailable");
        setProjectGoal("Couldn't load this project. Check that the API is reachable, then refresh.");
      })
      .finally(() => { if (active) setProjectLoading(false); });
    getVersions(projectId)
      .then((result) => { if (active) setVersions(result.versions); })
      .catch(() => { if (active) setVersions([]); });
    return () => { active = false; };
  }, [projectId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (buildOpen && !buildLoading) { setBuildOpen(false); setBuildError(null); setBuildGaps([]); return; }
      if (controlPanel) { setControlPanel(null); return; }
      if (irOpen && !irLoading) { setIrOpen(false); return; }
      if (nodeDialogOpen && !nodeMutationLoading) { setNodeDialogOpen(false); return; }
      if (contextOpen) { setContextOpen(false); return; }
      if (selectedRun) setSelectedRun(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [buildOpen, buildLoading, controlPanel, irOpen, irLoading, nodeDialogOpen, nodeMutationLoading, contextOpen, selectedRun]);

  useEffect(() => {
    if (config?.runtime_mode !== "stepfunctions") {
      setPendingApproval(null);
      return;
    }

    let active = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const result = await getDurableApprovals(projectId);
        if (!active) return;
        setPendingApproval(result.approvals[0] ?? null);
        timer = setTimeout(poll, 3000);
      } catch {
        if (active) timer = setTimeout(poll, 5000);
      }
    };

    void poll();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [projectId, runRefreshKey, config?.runtime_mode]);

  const openDemo = (demo: import("./api").DemoWorkflow) => {
    // Opening a starter only prefills the dialog. The current project stays on screen
    // until a build actually succeeds.
    setBuildError(null);
    setBuildGaps([]);
    setDemoGoal(demo.goal);
    setDemoInput(demo.input_data);
    setBuildOpen(true);
  };

  const pendingBuild = useRef<{ goal: string; projectId: string } | null>(null);

  const handleBuild = async (goal: string, gapAnswers: Record<string, string> = {}) => {
    setBuildLoading(true);
    setBuildError(null);

    try {
      // Every new goal gets its own project so builds never overwrite another system.
      // Answering gap questions for the same goal continues the pending project.
      const targetProjectId =
        pendingBuild.current && pendingBuild.current.goal === goal
          ? pendingBuild.current.projectId
          : projectSlug(goal);
      pendingBuild.current = { goal, projectId: targetProjectId };
      const finishBuild = () => {
        pendingBuild.current = null;
        setProjectName(projectTitle(goal));
        setProjectGoal(goal);
        setProjectId(targetProjectId);
        setRunRefreshKey((value) => value + 1);
      };

      const queued = await startBuildAsync(targetProjectId, goal, gapAnswers);

      if (queued.status === "failed") {
        setBuildError(String(queued.error ?? "Build could not be queued."));
        return;
      }

      if (queued.status === "completed" && queued.build) {
        const result = queued.build;
        if (!result.ready || !result.workflow) {
          setBuildGaps(result.gaps ?? []);
          setBuildError("Resolve the blocking context questions below, then continue.");
          return;
        }
        finishBuild();
        setBuildOpen(false);
        setDemoGoal(undefined);
        return;
      }

      setBuildError("Queued in AWS. Specloom will compile, verify, and return the system here.");
      const deadline = Date.now() + 12 * 60 * 1000;

      while (Date.now() < deadline) {
        await new Promise((resolve) => window.setTimeout(resolve, 2500));
        const job = await getBuildJob(targetProjectId, queued.run_id);

        if (job.status === "queued" || job.status === "running") {
          setBuildError(job.status === "queued"
            ? "Queued in AWS. Specloom will compile, verify, and return the system here."
            : "Compiling in AWS. Specloom is architecting, validating, and verifying the system…");
          continue;
        }

        if (job.status === "failed") {
          setBuildError(typeof job.error === "string"
            ? job.error
            : "Build failed. Open Runs for the detailed execution record.");
          return;
        }

        const result = job.build;
        if (!result?.workflow || !result.ready) {
          setBuildGaps(result?.gaps ?? []);
          setBuildError("Specloom needs more context before it can build this system.");
          return;
        }

        setBuildGaps([]);
        finishBuild();
        setBuildOpen(false);
        setDemoGoal(undefined);
        setBuildError(null);
        return;
      }

      setBuildError("The AWS build is still running. Open Runs to follow the build rather than starting another one.");
    } catch (error) {
      setBuildError(error instanceof Error ? error.message : "Could not reach the Specloom API");
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
      const result = await runWorkflow(projectId, example.workflow, demoInput);
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

      const result = await simulateWorkflow(projectId, example.workflow, false);
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
        project_id:projectId,
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

  const handleNodeModeChange = async (mode: "mock" | "sandbox" | "live") => {
    if (!selectedIRNode || selectedIRNode.type !== "tool" || !workflow) return;
    try {
      const result = await updateNodeMode(projectId, selectedIRNode.id, mode);
      setWorkflow(result.workflow);
      const canvas = workflowToCanvas(result.workflow);
      setNodes((current) => canvas.nodes.map((node) => ({
        ...node,
        data: {
          ...node.data,
          status: current.find((item) => item.id === node.id)?.data.status ?? node.data.status,
        },
      })));
      setEdges(canvas.edges);
      setSelected(selectedIRNode.id);
      setWorkflowVersionCount(result.version);
      getVersions(projectId).then((value) => setVersions(value.versions)).catch(() => {});
      evaluateWorkflow(projectId, result.workflow)
        .then((value) => setEvaluation(value as { status: string; passed: number; failed: number; tests: Array<{ test_id: string; name: string; status: string; message: string }> }))
        .catch(() => setEvaluation(null));
    } catch (error) {
      setBuildError(error instanceof Error ? error.message : "Could not update tool mode");
    }
  };

  const diagnoseRepair = async () => {
    if (!workflow) return;
    setRepairLoading(true);
    try {
      const candidate = await repairWorkflow(projectId, workflow);
      setRepairCandidate(candidate);
    } catch (error) {
      setRepairCandidate({
        repaired: false,
        patch: null,
        workflow: null,
      });
      setBuildError(error instanceof Error ? error.message : "Repair diagnostics failed");
    } finally {
      setRepairLoading(false);
    }
  };

  const acceptRepair = async () => {
    if (!workflow || !repairCandidate?.patch) return;
    setRepairLoading(true);
    try {
      const result = await applyRepair(projectId, workflow, repairCandidate.patch);
      setWorkflow(result.workflow);
      const canvas = workflowToCanvas(result.workflow);
      setNodes(canvas.nodes);
      setEdges(canvas.edges);
      setSelected(canvas.nodes[0]?.id ?? "");
      setWorkflowVersionCount(result.version);
      setRepairCandidate(null);
      getVersions(projectId).then((value) => setVersions(value.versions)).catch(() => {});
      const value = await evaluateWorkflow(projectId, result.workflow);
      setEvaluation(value as { status: string; passed: number; failed: number; tests: Array<{ test_id: string; name: string; status: string; message: string }> });
    } catch (error) {
      setBuildError(error instanceof Error ? error.message : "Could not apply repair");
    } finally {
      setRepairLoading(false);
    }
  };

  const approveDurablePending = async () => {
    if (!pendingApproval) return;
    setApprovalLoading(true);
    try {
      const separator = pendingApproval.approval_id.lastIndexOf(":");
      const runId = separator >= 0 ? pendingApproval.approval_id.slice(0, separator) : pendingApproval.approval_id;
      await approveDurableRun(projectId, runId, pendingApproval.node_id);
      setPendingApproval(null);
      setRunRefreshKey((value) => value + 1);
    } catch (error) {
      setBuildError(error instanceof Error ? error.message : "Durable approval failed");
    } finally {
      setApprovalLoading(false);
    }
  };

  const rejectDurablePending = async () => {
    if (!pendingApproval) return;
    setApprovalLoading(true);
    try {
      const separator = pendingApproval.approval_id.lastIndexOf(":");
      const runId = separator >= 0 ? pendingApproval.approval_id.slice(0, separator) : pendingApproval.approval_id;
      await rejectDurableRun(projectId, runId, pendingApproval.node_id);
      setPendingApproval(null);
      setRunRefreshKey((value) => value + 1);
    } catch (error) {
      setBuildError(error instanceof Error ? error.message : "Durable rejection failed");
    } finally {
      setApprovalLoading(false);
    }
  };

  const approvePendingRun = async () => {
    if (!pendingRunId) return;
    setRunning(true);
    try {
      const result = await approveRun(projectId, pendingRunId);
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
            ["Projects", LayoutDashboard, () => { refreshProjects(); setControlPanel("projects"); }],
            ["System", GitBranch, () => { setControlPanel(null); setTab("system"); }],
            ["Context", Layers3, () => { setControlPanel(null); setTab("context"); }],
            ["Tests", Activity, () => { setControlPanel(null); setTab("tests"); }],
          ] as const).map(([label, Icon, action]) => (
            <button
              key={String(label)}
              className={`nav-item ${(label === "Projects" && controlPanel === "projects") || (label === "System" && !controlPanel && tab === "system") || (label === "Context" && !controlPanel && tab === "context") || (label === "Tests" && !controlPanel && tab === "tests") ? "active" : ""}`}
              onClick={action}
            >
              <Icon size={16} />
              <span>{String(label)}</span>
              {label === "Projects" && projects.length > 0 && <span className="nav-count">{projects.length}</span>}
            </button>
          ))}

          <div className="nav-label nav-label-gap">CONFIGURE</div>
          {([
            ["Tools", Wrench, "tools"],
            ["Permissions", ShieldCheck, "permissions"],
            ["Settings", Settings2, "settings"],
          ] as const).map(([label, Icon, kind]) => (
            <button key={String(label)} className={`nav-item ${controlPanel === kind ? "active" : ""}`} onClick={() => setControlPanel(kind)}>
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
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="breadcrumbs">
            <button className="crumb-link" onClick={() => { refreshProjects(); setControlPanel("projects"); }}>Projects</button><span>/</span><strong>{projectName}</strong>
          </div>
          <div className="topbar-actions">
            <button className="ghost-button" onClick={() => { refreshProjects(); setControlPanel("projects"); }}><Search size={15}/> <span className="hide-sm">Projects</span></button>
            <button
              className="icon-button theme-toggle"
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
              aria-label={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
              title={theme === "light" ? "Dark mode" : "Light mode"}
            >
              {theme === "light" ? <Moon size={16}/> : <Sun size={16}/>}
            </button>
          </div>
        </header>

        <section className="project-header">
          <div>
            <div className="eyebrow">{built ? <span className="live-pill">LIVE</span> : <span className="draft-pill">{projectLoading ? "LOADING" : "DRAFT"}</span>} {projectName}</div>
            <h1 className={projectLoading ? "is-loading" : ""}>{projectLoading ? "Loading project…" : projectGoal}</h1>
            <p className="project-description">
              {workflow
                ? "Specloom compiled this system from the stated goal, available context, registered capabilities, and safety constraints."
                : "Pick a starter below or click New system to describe what you need. Specloom will ask about anything it can't infer."}
            </p>
          </div>
          <div className="header-actions">
            <button className="secondary-button" onClick={() => { setDemoGoal(undefined); setDemoInput({}); setBuildError(null); setBuildGaps([]); setBuildOpen(true); }}><Plus size={15}/> New system</button>
            {workflow && <label className="version-control">
              <Archive size={14}/>
              <select
                value={versions.find((version) => version.active)?.version ?? workflowVersionCount}
                onChange={async (event) => {
                  const nextVersion = Number(event.target.value);
                  if (!window.confirm(`Make version ${nextVersion} the active workflow? Runs and deploys will use it.`)) {
                    event.target.value = String(versions.find((version) => version.active)?.version ?? workflowVersionCount);
                    return;
                  }
                  try {
                    const result = await activateVersion(projectId, nextVersion);
                    setWorkflow(result.workflow);
                    const canvas = workflowToCanvas(result.workflow);
                    setNodes(canvas.nodes);
                    setEdges(canvas.edges);
                    setSelected(canvas.nodes[0]?.id ?? "");
                    const refreshed = await getVersions(projectId);
                    setVersions(refreshed.versions);
                  } catch (error) {
                    setBuildError(error instanceof Error ? error.message : "Could not activate workflow version");
                  }
                }}
                aria-label="Workflow version"
              >
                {(versions.length ? versions : [{version: workflowVersionCount, workflow_id: "", name: "Current", active: true}]).map((version) => (
                  <option key={version.version} value={version.version}>Version {version.version}{version.name ? ` · ${version.name}` : ""}</option>
                ))}
              </select>
              <ChevronDown size={13}/>
            </label>}
            <button className="primary-button" onClick={runSystem} disabled={running || !workflow} title={workflow ? undefined : "Build a system first"}>
              <Play size={15} fill="currentColor"/>{running ? "Running…" : "Run now"}
            </button>
          </div>
        </section>

        <div className="status-strip">
          <div className="status-block">
            <span className="status-key"><ShieldCheck size={14}/> System</span>
            <strong className={evaluation?.status === "passed" ? "success-text" : evaluation?.status === "failed" ? "danger-text" : ""}>{!built ? "Not built" : evaluation ? (evaluation.status === "passed" ? "Verified" : `${evaluation.failed} failing`) : "Checking…"}</strong>
          </div>
          <div className="status-block">
            <span className="status-key"><Clock3 size={14}/> Schedule</span>
            <strong>{triggerLabel(workflow)}</strong>
          </div>
          <div className="status-block">
            <span className="status-key"><Database size={14}/> Context</span>
            <strong>{contextGraph?.sources.length ?? 0} sources</strong>
          </div>
          <div className="status-block">
            <span className="status-key"><GitPullRequest size={14}/> Last run</span>
            <strong>{lastRun ? `${lastRun.status} · ${lastRun.events.length} events` : recentRuns[0] ? `${recentRuns[0].status} · ${recentRuns[0].kind}` : "No runs yet"}</strong>
          </div>
          <div className="status-block status-block-right">
            <span className="status-key">RUNTIME</span>
            <strong>{config ? `${config.runtime_mode} · ${config.storage_mode}` : "loading…"}</strong>
          </div>
        </div>

        <section className="demo-strip">
          <div className="demo-strip-head">
            <div>
              <div className="section-kicker">DEMO GALLERY</div>
              <strong>Start with a real problem</strong>
              <span>Real problem starters using the normal build and run flow.</span>
            </div>
            <span className="demo-proof"><ShieldCheck size={12}/> real runtime</span>
          </div>
          <div className="demo-cards">
            {demos.slice(0, 3).map((demo) => (
              <button className="demo-card" key={demo.id} onClick={() => void openDemo(demo)}>
                <span className="demo-card-icon">{demo.id === "support-triage" ? <Users size={15}/> : demo.id === "document-brief" ? <FileText size={15}/> : <Sparkles size={15}/>}</span>
                <span className="demo-card-copy"><strong>{demo.name}</strong><span>{demo.description}</span></span>
                <ArrowRight size={14}/>
              </button>
            ))}
          </div>
        </section>

        <div className="workspace">
          <section className="workspace-main">
            <div className="workspace-tabs">
              {(["system","context","tests","deploy"] as const).map((item) => (
                <button key={item} className={`workspace-tab ${tab===item ? "selected":""}`} onClick={() => setTab(item)}>
                  {item === "system" ? "System" : item === "context" ? "Context" : item === "tests" ? "Tests" : "Deploy"}
                  {item==="tests" && <span className="tab-badge">{evaluation?.tests.length ?? 0}</span>}
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
                    <button className="tiny-button" onClick={openAddNode} disabled={!workflow}><Plus size={14}/> Node</button>
                    <button className="tiny-button" onClick={() => setIrOpen(true)} disabled={!workflow}><Code2 size={14}/> IR</button>
                  </div>
                </div>
                <div className="flow-area">
                  <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    nodeTypes={nodeTypes}
                    fitView
                    fitViewOptions={{padding:0.22}}
                    minZoom={0.25}
                    nodesDraggable={false}
                    onNodeClick={(_, node) => setSelected(node.id)}
                    proOptions={{hideAttribution:true}}
                  >
                    <FitOnChange signature={nodes.map((node) => node.id).join("|")} />
                    <Background gap={22} size={1} color="var(--canvas-grid)" />
                    <MiniMap
                      pannable
                      zoomable
                      nodeColor={(node) => node.id===selected ? "#111" : "#d5d5ce"}
                      maskColor="var(--canvas-mask)"
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

                <div className="repair-card">
                  <div>
                    <div className="inspector-section-title">Repair engine</div>
                    <p>Diagnose simulator failures and propose a constrained IR patch. Applying it always creates a new workflow version.</p>
                  </div>
                  {!repairCandidate?.repaired ? (
                    <button className="secondary-button" onClick={diagnoseRepair} disabled={repairLoading}>
                      {repairLoading ? "Diagnosing…" : "Run repair diagnostics"}
                    </button>
                  ) : (
                    <>
                      <div className="repair-diff">
                        <span>{repairCandidate.patch?.target_node}</span>
                        <strong>{String(repairCandidate.patch?.old_value)}</strong>
                        <span>→</span>
                        <strong>{String(repairCandidate.patch?.new_value)}</strong>
                      </div>
                      <button className="primary-button" onClick={acceptRepair} disabled={repairLoading}>
                        {repairLoading ? "Applying…" : "Accept repair"}
                      </button>
                    </>
                  )}
                  {repairCandidate && !repairCandidate.repaired && (
                    <span className="provenance-muted">{repairCandidate.patch ? repairCandidate.patch.description : "No safe repair candidate was found for the current workflow."}</span>
                  )}
                </div>
              </div>
            )}

            {tab === "deploy" && (
              <DeployView
                projectId={projectId}
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
              <button className="icon-button" onClick={() => setSelected("")} aria-label="Clear selection"><X size={16}/></button>
            </div>

            {selectedNode && (
              <>
                <div className="inspector-status"><span className={`status-dot status-${selectedNode.data.status}`}/>{selectedNode.data.status === "warning" ? "Needs attention" : "Verified"}</div>
                <div className="inspector-card">
                  <div className="inspector-row"><span>Type</span><strong>{nodeTypeLabel(selectedNode.data.meta)}</strong></div>
                  <div className="inspector-row"><span>Access</span><strong>{selectedNode.data.meta.split("·")[1]}</strong></div>
                  <div className="inspector-row"><span>Purpose</span><strong>{selectedNode.data.detail}</strong></div>
                </div>

                {selectedIRNode?.type === "tool" && (
                  <div className="inspector-card tool-config-card">
                    <div className="inspector-row">
                      <span>Execution mode</span>
                      <select
                        className="tool-mode-select"
                        value={String(selectedIRNode.config?.mode ?? "sandbox")}
                        onChange={(event) => handleNodeModeChange(event.target.value as "mock" | "sandbox" | "live")}
                      >
                        <option value="mock">mock</option>
                        <option value="sandbox">sandbox</option>
                        <option value="live">live</option>
                      </select>
                    </div>
                    <div className="tool-config-note">
                      {String(selectedIRNode.config?.tool_ref ?? "tool")} · writes remain policy-gated
                    </div>
                  </div>
                )}

                <div className="inspector-section">
                  <div className="inspector-section-title">Why does this exist?</div>
                  <ProvenancePanel projectId={projectId} nodeId={selectedNode.id} />
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
                  <RunHistory projectId={projectId} refreshKey={runRefreshKey} onSelect={setSelectedRun} />
                </div>
              </>
            )}

            <div className="inspector-footer">
              <button className="secondary-button full" onClick={openConfigureNode} disabled={!selectedIRNode}><Settings2 size={15}/> Configure node</button>
            </div>
          </aside>
        </div>

        <div className={`bottom-runbar ${running ? "is-running" : ""}`}>
          <div className="runbar-left">
            <span className="runbar-icon"><Sparkles size={14}/></span>
            <div><strong>{running ? "Running system" : pendingApproval || pendingRunId ? "Human approval required" : lastRun?.status === "running" ? "Run in progress" : lastRun?.status === "passed" ? "Run completed" : lastRun?.status === "failed" ? "Run failed" : built ? "System ready" : "Build required"}</strong><span>{running ? "Executing generated graph…" : pendingApproval ? `Paused at ${pendingApproval.node_id} before an external action.` : pendingRunId ? "The workflow is paused before the write-capable step." : lastRun?.status === "running" ? "Durable execution is active and the trace will update automatically." : lastRun?.error ?? (built ? "All required context and policies are present." : "No system yet. Start from a demo or describe one with New system.")}</span></div>
          </div>
          <div className="runbar-stats">
            <span><CircleAlert size={14}/> {blockerCount} {blockerCount === 1 ? "blocker" : "blockers"}</span>
            <span><ShieldCheck size={14}/> {policyCount} {policyCount === 1 ? "policy" : "policies"}</span>
            <span><LockKeyhole size={14}/> {approvalGateCount} approval {approvalGateCount === 1 ? "gate" : "gates"}</span>
            {pendingApproval ? (
              <>
                <button className="secondary-button approval-action" onClick={rejectDurablePending} disabled={running || approvalLoading}>Reject</button>
                <button className="primary-button approval-action" onClick={approveDurablePending} disabled={running || approvalLoading}><Check size={14}/> Approve</button>
              </>
            ) : pendingRunId ? (
              <button className="primary-button approval-action" onClick={approvePendingRun} disabled={running}><Check size={14}/> Approve & continue</button>
            ) : null}
          </div>
        </div>
        <ContextDialog
          projectId={projectId}
          open={contextOpen}
          onClose={() => setContextOpen(false)}
          onAdded={() => getContext(projectId).then((value) => setContextGraph(value.graph)).catch(() => {})}
        />
        <RunDetailDialog projectId={projectId} run={selectedRun} onClose={() => setSelectedRun(null)} />
        <NodeDialog
          open={nodeDialogOpen}
          mode={nodeDialogMode}
          node={selectedIRNode as any}
          loading={nodeMutationLoading}
          error={buildError}
          onClose={() => { if (!nodeMutationLoading) setNodeDialogOpen(false); }}
          onSave={handleNodeSave}
        />
        <IRDialog
          open={irOpen}
          workflow={workflow}
          loading={irLoading}
          error={buildError}
          onClose={() => { if (!irLoading) setIrOpen(false); }}
          onSave={handleIRSave}
        />
        {controlPanel && (
          <ControlPanel
            kind={controlPanel}
            config={config}
            tools={contextGraph?.tools ?? []}
            workflow={workflow}
            projects={projects}
            currentProjectId={projectId}
            onOpenProject={(id) => { setControlPanel(null); if (id !== projectId) setProjectId(id); }}
            onNewSystem={() => { setControlPanel(null); setDemoGoal(undefined); setDemoInput({}); setBuildOpen(true); }}
            onClose={() => setControlPanel(null)}
          />
        )}
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
          initialGoal={demoGoal}
        />
      </main>
    </div>
  );
}

export default App;
