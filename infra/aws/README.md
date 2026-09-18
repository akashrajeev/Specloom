# Durable AWS control plane

Production persistence is split by responsibility:

- DynamoDB: project metadata, current Workflow IR, workflow versions, and normalized context graph.
- S3: uploaded source documents and larger artifacts.
- AgentCore Runtime: execution.
- Bedrock: architect and agent reasoning.

Configure:

SPECL00M_STORAGE_MODE=aws
SPECL00M_DDB_TABLE=specloom-projects
SPECL00M_S3_BUCKET=specloom-project-sources

The application keeps the repository behind ProjectRepository, so local development remains deterministic.

Before deployment, create the DynamoDB table with partition key `project_id` and grant the runtime role read/write access to that table plus the S3 bucket.
