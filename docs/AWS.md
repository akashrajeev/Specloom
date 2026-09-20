# Specloom AWS Deployment Guide

This is the operational guide for running Specloom with AWS-backed persistence, authentication, Bedrock, and durable execution.

## 1. Canonical infrastructure

The canonical production SAM template is:

~~~text
infra/aws/template.yaml
~~~

Use:

~~~bash
./infra/aws/deploy.sh
~~~

The compatibility wrapper:

~~~bash
./scripts/deploy-aws.sh
~~~

delegates to the same canonical stack.

Do not deploy the older root template.yaml when following the production path. It is a smaller legacy API stack and is not the canonical control plane.

## 2. What the SAM stack provisions

The SAM template currently provisions:

| Resource | Purpose |
|---|---|
| API Gateway | Public HTTP entrypoint |
| Lambda | Hosts the FastAPI application through Mangum |
| Cognito User Pool | Authentication |
| Cognito User Pool Client | Browser/client authentication |
| ProjectsTable | Project state, current workflow, versions, context metadata, runs |
| ApprovalsTable | Durable approval state/callback information |
| SourcesBucket | Uploaded source documents and generated artifacts |
| EventBridge Rule | Scheduled workflow invocation |
| DurableStateMachineRole | IAM role used by generated Standard Step Functions workflows |

The application also has permissions for Bedrock model invocation, SageMaker endpoint invocation, Step Functions APIs, S3, and DynamoDB.

## 3. Important runtime detail

The SAM template does not define one permanent Step Functions state machine per possible workflow.

Instead:

1. Specloom receives or builds a Workflow IR.
2. DurableWorkflowManager compiles that IR to a Step Functions definition.
3. AWS validates the generated definition.
4. Specloom creates or updates a Standard state machine for the project.
5. The workflow execution starts with the supplied runtime input.
6. Human approval callback tokens can be persisted in DynamoDB and resumed later.

This keeps the runtime graph derived from the canonical Workflow IR.

## 4. Prerequisites

Install and authenticate the AWS CLI and AWS SAM CLI.

Verify credentials:

~~~bash
aws sts get-caller-identity
~~~

Before a Bedrock build/runtime, also ensure the selected model is available to the account in the chosen region.

The repository's Lambda runtime is Python 3.11.

## 5. Configure the region

The checked-in samconfig.toml defaults to:

~~~text
ap-south-1
~~~

The deployment scripts also default AWS_REGION to ap-south-1 when it is not already set.

To change region for a deployment, set AWS_REGION and make sure the SAM deployment configuration matches the intended region.

## 6. Build and deploy

From the repository root:

~~~bash
./infra/aws/deploy.sh
~~~

The script:

1. builds infra/aws/template.yaml;
2. uses SAM's generated .aws-sam build;
3. deploys using the checked-in SAM configuration;
4. avoids interactive change-set confirmation;
5. prints CloudFormation outputs.

Equivalent explicit commands:

~~~bash
sam build --template-file infra/aws/template.yaml
sam deploy   --config-file samconfig.toml   --template-file .aws-sam/build/template.yaml   --no-confirm-changeset   --no-fail-on-empty-changeset
~~~

## 7. Inspect deployment outputs

~~~bash
aws cloudformation describe-stacks   --stack-name specloom   --query 'Stacks[0].Outputs'   --output table
~~~

Important outputs include:

- ApiUrl;
- ProjectsTableName;
- ApprovalsTableName;
- SourcesBucketName;
- DurableStateMachineRoleArn;
- CognitoUserPoolId;
- CognitoClientId;
- CognitoIssuer.

## 8. Frontend configuration

After deployment, configure the frontend with the ApiUrl output:

~~~text
VITE_API_BASE_URL=<ApiUrl>
~~~

Then:

~~~bash
cd frontend
npm install
npm run build
~~~

For Amplify, use the repository's infra/aws/amplify.yml build specification.

For another static host, publish frontend/dist.

## 9. AWS application modes

The SAM parameters expose the main application switches.

### AuthMode

Allowed:

~~~text
off
cognito
~~~

The SAM default is cognito.

### ArchitectMode

Allowed:

~~~text
showcase
bedrock
~~~

The production-oriented default is bedrock.

### ReviewMode

Allowed:

~~~text
none
bedrock
~~~

### ContextMode

Allowed:

~~~text
deterministic
bedrock
~~~

### RuntimeMode

Allowed:

~~~text
local
sagemaker
bedrock
stepfunctions
~~~

The SAM default is stepfunctions.

### Bedrock model

BedrockModelId selects the model ID used by the architect/runtime configuration.

AllowedBedrockModels defines the model allowlist used by the application.

## 10. Environment variables used by the AWS deployment

The application reads the following categories of values:

~~~text
SPECL00M_STORAGE_MODE=aws
SPECL00M_DDB_TABLE=<ProjectsTable>
SPECL00M_S3_BUCKET=<SourcesBucket>

SPECL00M_AUTH_MODE=cognito
SPECL00M_COGNITO_ISSUER=<CognitoIssuer>
SPECL00M_COGNITO_CLIENT_ID=<CognitoClientId>

SPECL00M_ARCHITECT_MODE=bedrock
SPECL00M_CONTEXT_MODE=bedrock
SPECL00M_RUNTIME_MODE=stepfunctions
SPECL00M_BEDROCK_MODEL_ID=<model>
SPECL00M_ALLOWED_BEDROCK_MODELS=<model-list>
~~~

The SAM template injects the AWS resource-specific values into the Lambda environment.

## 11. Cognito workspace model

The FastAPI AuthenticationMiddleware supports Cognito JWT verification.

Authenticated requests need:

- a valid bearer token;
- a matching Cognito issuer;
- a matching client/audience when configured;
- a Specloom workspace identity.

A workspace can be supplied by a workspace claim or a Cognito group with the expected Specloom workspace naming convention.

The context store uses the current workspace to prevent one workspace from accessing another workspace's project state.

## 12. Durable approvals

The durable approval table stores callback data needed to resume a Step Functions execution.

Approval records include:

- approval ID;
- project ID;
- node ID;
- execution ARN;
- Step Functions task token;
- input data;
- status;
- expiration metadata.

The frontend can list pending approvals and approve/reject them through the API.

## 13. EventBridge scheduling

The current SAM stack creates one scheduled EventBridge rule.

Its target invokes the Specloom Lambda and provides:

~~~json
{
  "source": "aws.events",
  "detail": {
    "project_id": "researchhunter",
    "input_data": {}
  }
}
~~~

For production use, adapt the project ID/input to the required workflow and schedule expression.

The ScheduleExpression SAM parameter defaults to rate(1 day).

## 14. Bedrock architecture path

The Bedrock architect lives under backend/agents/bedrock_architect.py.

Its responsibility is to turn:

~~~text
goal + Context Graph
        ↓
Workflow IR
~~~

The result is then checked by deterministic validation before being accepted.

The Bedrock runtime runner under backend/runtime/bedrock_runner.py executes agent nodes using Strands + Bedrock and only attaches capabilities allowed by the compiled workflow.

## 15. AgentCore

infra/agentcore contains an AgentCore entrypoint/scaffold.

It accepts a payload containing:

~~~json
{
  "workflow": {},
  "input_data": {}
}
~~~

The entrypoint validates Workflow IR and invokes the runtime executor with a Bedrock-backed agent runner.

The current canonical SAM deployment does not require deploying this scaffold to use the main control plane.

## 16. SageMaker runtime

backend/runtime/sagemaker_runner.py provides a separate runtime adapter.

When RuntimeMode is sagemaker, configure:

~~~text
SPECL00M_SAGEMAKER_ENDPOINT_NAME=<endpoint-name>
~~~

The Lambda role in the SAM template has permission to invoke SageMaker endpoints.

## 17. Source and artifact storage

AwsProjectRepository stores project metadata in DynamoDB and source/artifact content in S3.

S3 keys follow the project-oriented layout:

~~~text
projects/{project_id}/sources/...
projects/{project_id}/artifacts/...
projects/{project_id}/snapshots/...
~~~

The source bucket has public-access blocking enabled and server-side encryption configured.

## 18. Deployment verification checklist

After deployment, verify:

~~~bash
aws cloudformation describe-stacks --stack-name specloom
~~~

Then:

~~~bash
curl <ApiUrl>/health
~~~

Next verify:

1. frontend points at ApiUrl;
2. authenticated API calls receive valid Cognito tokens;
3. a small build succeeds;
4. the project state appears in DynamoDB;
5. a source upload appears in S3;
6. Workflow IR passes validation;
7. a runtime invocation succeeds;
8. durable approval records appear for workflows with approval nodes;
9. Step Functions execution history is accessible for durable runs.

## 19. Cost and lifecycle considerations

The repository uses pay-per-request DynamoDB tables and an S3-backed artifact/source store. Real usage of Bedrock, Lambda, API Gateway, Step Functions, S3, DynamoDB, Cognito, and optional SageMaker can incur AWS charges.

Delete the CloudFormation stack when you no longer need the test environment:

~~~bash
aws cloudformation delete-stack --stack-name specloom
~~~

Review retained resources and buckets before deletion if the environment contains data that must be preserved.

## 20. Production caveats

The repository provides a deployable AWS control plane, but the repository cannot prove a successful deployment into your AWS account.

Before presenting the system as cloud-live, verify in the target account:

- CloudFormation stack reaches CREATE_COMPLETE/UPDATE_COMPLETE;
- Cognito authentication works;
- Bedrock model invocation works;
- DynamoDB writes/readbacks work;
- S3 source/artifact operations work;
- generated Step Functions definitions pass AWS validation;
- actual runtime execution and human approval resume correctly.

