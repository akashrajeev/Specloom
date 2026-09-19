export type SimulationEvent = {
  sequence: number;
  node_id: string;
  node_type: string;
  status: "started" | "completed" | "waiting" | "failed" | "skipped";
  message: string;
  duration_ms: number;
};

export type SimulationResult = {
  project_id: string;
  run_id?: string;
  workflow_id: string;
  status: "passed" | "failed" | "waiting" | "completed" | "running";
  events: SimulationEvent[];
  output: Record<string, unknown> | null;
  failed_node: string | null;
  error: string | null;
  side_effects: Array<Record<string, unknown>>;
  metrics: Record<string, unknown>;
};

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function getExampleWorkflow() {
  return request<{ workflow: Record<string, unknown>; validation_errors: string[] }>(
    "/api/v1/workflow/example",
  );
}

export function simulateWorkflow(projectId: string, workflow: Record<string, unknown>, approved = false) {
  return request<SimulationResult>(`/api/v1/projects/${projectId}/simulate`, {
    method: "POST",
    body: JSON.stringify({
      workflow,
      input_data: { approved },
    }),
  });
}

export function evaluateWorkflow(projectId: string, workflow: Record<string, unknown>) {
  return request<Record<string, unknown>>(`/api/v1/projects/${projectId}/evaluate`, {
    method: "POST",
    body: JSON.stringify(workflow),
  });
}


export type ContextGraph = {
  sources: Array<{ id: string; kind: string; name: string; uri?: string | null }>;
  requirements: Array<{ id: string; statement: string; priority: string }>;
  constraints: Array<{ id: string; statement: string; severity: string }>;
  tools: Array<{ id: string; name: string; capabilities: string[]; permissions: string[] }>;
  examples: Array<{ id: string; input: unknown; expected: unknown }>;
  entities: Array<{ id: string; type: string; name: string }>;
};

export function getContext(projectId: string) {
  return request<{ project_id: string; graph: ContextGraph }>(
    `/api/v1/projects/${projectId}/context`,
  );
}

export type BuildGap = {
  id: string;
  severity: string;
  category: string;
  question: string;
  related_requirement?: string | null;
};

export type BuildResult = {
  project_id: string;
  architect_mode: string;
  ready: boolean;
  gaps: BuildGap[];
  workflow?: Record<string, unknown>;
  execution_plan?: {
    workflow_id: string;
    ordered_nodes: Array<Record<string, unknown>>;
  };
};

export type ProvenanceItem = {
  id: string;
  statement: string;
  priority?: string;
  severity?: string;
  provenance?: Array<{
    source_id: string;
    locator?: string | null;
    quote?: string | null;
    confidence?: number | null;
  }>;
};

export type NodeProvenance = {
  node: Record<string, unknown>;
  requirements: ProvenanceItem[];
  constraints: ProvenanceItem[];
  sources: Array<{
    id: string;
    kind: string;
    name: string;
    uri?: string | null;
  }>;
  policies: Array<Record<string, unknown>>;
  tests: Array<Record<string, unknown>>;
  dependencies: {
    upstream: string[];
    downstream: string[];
  };
};

export type RunRecord = {
  run_id: string;
  kind: "simulation" | "runtime";
  created_at: string;
  workflow_id: string;
  status: "passed" | "failed" | "waiting" | "completed" | "running";
  events: Array<SimulationEvent | {
    sequence: number;
    node_id: string;
    node_type: string;
    status: string;
    message: string;
  }>;
  output?: Record<string, unknown> | null;
  failed_node?: string | null;
  error?: string | null;
  side_effects?: Array<Record<string, unknown>>;
  metrics?: Record<string, unknown>;
};

export function buildWorkflow(projectId: string, goal: string, gapAnswers: Record<string, string> = {}) {
  return request<BuildResult>(`/api/v1/projects/${projectId}/build`, {
    method: "POST",
    body: JSON.stringify({ goal, gap_answers: gapAnswers }),
  });
}

export function getNodeProvenance(projectId: string, nodeId: string) {
  return request<NodeProvenance>(
    `/api/v1/projects/${projectId}/provenance?node_id=${encodeURIComponent(nodeId)}`,
  );
}

export function getRuns(projectId: string, limit = 12) {
  return request<{ project_id: string; runs: RunRecord[] }>(
    `/api/v1/projects/${projectId}/runs?limit=${limit}`,
  );
}


export function getRun(projectId: string, runId: string) {
  return request<{ project_id: string; run: RunRecord }>(
    `/api/v1/projects/${projectId}/runs/${encodeURIComponent(runId)}`,
  );
}

export async function approveRun(projectId: string, runId: string) {
  const result = await request<{
    project_id: string;
    run_id: string;
    parent_run_id: string;
    workflow_id: string;
    status: "completed" | "waiting" | "running";
    output?: Record<string, unknown> | null;
    events: Array<{
      sequence: number;
      node_id: string;
      node_type: string;
      status: string;
      message: string;
    }>;
    error?: string | null;
  }>(`/api/v1/projects/${projectId}/runs/${runId}/approve`, { method: "POST" });

  return {
    project_id: result.project_id,
    workflow_id: result.workflow_id,
    status: result.status === "completed" ? "passed" : "waiting",
    events: result.events.map((event) => ({
      sequence: event.sequence,
      node_id: event.node_id,
      node_type: event.node_type,
      status: event.status as SimulationEvent["status"],
      message: event.message,
      duration_ms: 0,
    })),
    output: result.output ?? null,
    failed_node: null,
    error: result.error ?? null,
    side_effects: [],
    metrics: {},
  } satisfies SimulationResult;
}

export function addTextContext(projectId: string, name: string, content: string) {
  return request<Record<string, unknown>>(`/api/v1/projects/${projectId}/context/text`, {
    method: "POST",
    body: JSON.stringify({ name, content }),
  });
}

export function addUrlContext(projectId: string, url: string, name?: string) {
  return request<Record<string, unknown>>(`/api/v1/projects/${projectId}/context/url`, {
    method: "POST",
    body: JSON.stringify({ url, name }),
  });
}

export async function addFileContext(projectId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/v1/projects/${projectId}/context/file`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    throw new Error((await response.text()) || `Upload failed: ${response.status}`);
  }
  return response.json() as Promise<Record<string, unknown>>;
}

export async function runWorkflow(projectId: string, workflow: Record<string, unknown>, inputData: Record<string, unknown> = {}) {
  const result = await request<{
    project_id: string;
    run_id: string;
    workflow_id: string;
    status: "completed" | "waiting";
    output?: Record<string, unknown> | null;
    events: Array<{
      sequence: number;
      node_id: string;
      node_type: string;
      status: string;
      message: string;
    }>;
    error?: string | null;
  }>(`/api/v1/projects/${projectId}/run`, {
    method: "POST",
    body: JSON.stringify({ workflow, input_data: inputData }),
  });

  return {
    project_id: result.project_id,
    run_id: result.run_id,
    workflow_id: result.workflow_id,
    status: result.status === "waiting" ? "waiting" : result.status === "running" ? "running" : "completed",
    events: result.events.map((event) => ({
      sequence: event.sequence,
      node_id: event.node_id,
      node_type: event.node_type,
      status: event.status as SimulationEvent["status"],
      message: event.message,
      duration_ms: 0,
    })),
    output: result.output ?? null,
    failed_node: null,
    error: result.error ?? null,
    side_effects: [],
    metrics: {},
  } satisfies SimulationResult;
}

export function getConfig() {
  return request<{
    architect_mode: string;
    runtime_mode: string;
    storage_mode: string;
    context_mode: string;
  }>("/api/v1/config");
}

export function getProject(projectId: string) {
  return request<{
    project_id: string;
    context: ContextGraph;
    workflow: Record<string, unknown> | null;
    workflow_versions: number;
  }>(`/api/v1/projects/${projectId}`);
}

export type WorkflowVersion = {
  version: number;
  workflow_id: string;
  name: string;
  description?: string | null;
  active: boolean;
};

export function getVersions(projectId: string) {
  return request<{
    project_id: string;
    active_workflow_id: string | null;
    versions: WorkflowVersion[];
  }>(`/api/v1/projects/${projectId}/versions`);
}

export function activateVersion(projectId: string, version: number) {
  return request<{
    project_id: string;
    version: number;
    workflow: Record<string, unknown>;
  }>(`/api/v1/projects/${projectId}/versions/${version}/activate`, {
    method: "POST",
  });
}

export function getDeployStatus() {
  return request<{
    deployment: "live" | "ready" | "local";
    public_url: string | null;
    persistence_ready: boolean;
    runtime_ready: boolean;
    agentcore_runtime_arn: string | null;
    runtime_mode: string;
    storage_mode: string;
    region: string | null;
  }>("/api/v1/deploy/status");
}

export function getDeployCheck(projectId: string) {
  return request<{
    project_id: string;
    ready: boolean;
    checks: Array<{
      id: string;
      label: string;
      status: "pass" | "warn" | "fail";
      detail?: string;
    }>;
  }>(`/api/v1/projects/${projectId}/deploy/check`);
}

export function updateNodeMode(projectId: string, nodeId: string, mode: "mock" | "sandbox" | "live") {
  return request<{
    project_id: string;
    version: number;
    workflow: Record<string, unknown>;
  }>(`/api/v1/projects/${projectId}/nodes/${encodeURIComponent(nodeId)}/mode`, {
    method: "PATCH",
    body: JSON.stringify({ mode }),
  });
}

export type RepairCandidate = {
  repaired: boolean;
  patch?: {
    description: string;
    target_node: string;
    path: string;
    old_value: unknown;
    new_value: unknown;
    rationale: string;
  } | null;
  workflow?: Record<string, unknown> | null;
};

export function repairWorkflow(projectId: string, workflow: Record<string, unknown>) {
  return request<RepairCandidate>(`/api/v1/projects/${projectId}/repair`, {
    method: "POST",
    body: JSON.stringify(workflow),
  });
}

export function applyRepair(
  projectId: string,
  workflow: Record<string, unknown>,
  patch: NonNullable<RepairCandidate["patch"]>,
) {
  return request<{
    project_id: string;
    version: number;
    workflow: Record<string, unknown>;
    applied: boolean;
  }>(`/api/v1/projects/${projectId}/repair/apply`, {
    method: "POST",
    body: JSON.stringify({
      workflow,
      target_node: patch.target_node,
      path: patch.path,
      new_value: patch.new_value,
    }),
  });
}


export function addGitHubContext(projectId: string, url: string, name?: string) {
  return request<Record<string, unknown>>(`/api/v1/projects/${projectId}/context/github`, {
    method: "POST",
    body: JSON.stringify({ url, name }),
  });
}
