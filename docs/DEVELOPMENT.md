# Specloom Development

## Local run

Backend:

```bash
cd Specloom
python -m pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_BASE_URL` when the backend is not on localhost.

## Current vertical slice

The working slice is:

1. Context can be ingested through the API.
2. A build request returns validated Workflow IR.
3. Workflow IR compiles into an execution plan.
4. The simulator executes the showcase graph without external side effects.
5. Evaluation runs the workflow's tests.
6. The repairer can apply bounded IR repairs.
7. The frontend visualizes the system and triggers real simulation through the API.

## Next implementation targets

- real Bedrock-backed Context Analyst
- real Bedrock-backed Architect
- contextual retrieval
- generated tests from requirements
- repair loop API
- persistent project state
- AWS deployment adapters
