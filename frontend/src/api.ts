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
  workflow_id: string;
  status: "passed" | "failed" | "waiting";
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


export type BuildResult = {
  project_id: string;
  architect_mode: string;
  workflow: Record<string, unknown>;
  execution_plan: {
    workflow_id: string;
    ordered_nodes: Array<Record<string, unknown>>;
  };
};

export function buildWorkflow(projectId: string, goal: string) {
  return request<BuildResult>(`/api/v1/projects/${projectId}/build`, {
    method: "POST",
    body: JSON.stringify({ goal }),
  });
}
