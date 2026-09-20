# Specloom Frontend

The frontend is the engineering workspace for Specloom.

It is a React 19 + Vite + TypeScript application and renders the canonical Workflow IR returned by the FastAPI control plane.

## Run locally

From the repository root:

~~~bash
cd frontend
npm install
npm run dev
~~~

The Vite development server normally runs at:

~~~text
http://localhost:5173
~~~

The backend should be running at port 8000:

~~~bash
uvicorn backend.main:app --reload --port 8000
~~~

## API configuration

Set VITE_API_BASE_URL when the backend is not at http://localhost:8000.

Example:

~~~text
VITE_API_BASE_URL=https://your-api.example.com
~~~

## Production build

~~~bash
npm run build
~~~

The build runs TypeScript checking followed by Vite bundling.

The output is:

~~~text
frontend/dist/
~~~

## UI architecture

~~~text
App.tsx
 ├── BuildDialog
 ├── ContextDialog
 ├── React Flow system canvas
 ├── ProvenancePanel
 ├── RunHistory
 ├── RunDetailDialog
 └── DeployView
~~~

The browser does not implement the compiler or runtime. It calls the FastAPI API through frontend/src/api.ts.

## Main UI behavior

### Build

New System opens the same build interface for arbitrary problems and demo starters.

### Context

Users can inspect normalized sources and add text, URLs, or files.

### System

The canonical Workflow IR is converted to a visual React Flow graph.

### Tests

The UI shows workflow evaluation and exposes simulation and repair actions.

### Deploy

The UI displays deployment configuration and readiness information returned by the backend.

### Run

Run now sends the current Workflow IR and runtime input to the normal runtime endpoint.

### Approvals

When a runtime execution pauses for a human decision, the workspace exposes approval actions and refreshes execution state.

## Design rules

- Do not create a UI-only workflow schema.
- Keep API types in sync with backend responses.
- Keep external effects in the backend.
- Keep loading/error states explicit.
- Prefer product terminology such as "problem", "system", "workflow", "runtime", and "approval" instead of "demo mode" or "mock product".
