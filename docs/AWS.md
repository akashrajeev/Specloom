# Specloom AWS Path

## Local mode

Specloom defaults to the deterministic Showcase Architect, so the product can be developed without AWS credentials.

Set:

SPECL00M_ARCHITECT_MODE=showcase

## Bedrock mode

Install the AWS dependencies:

pip install -r backend/requirements-aws.txt

Configure:

SPECL00M_ARCHITECT_MODE=bedrock
SPECL00M_BEDROCK_MODEL_ID=amazon.nova-lite-v1:0
AWS_REGION=us-west-2

The Bedrock architect uses the Strands Agents SDK with a Bedrock model. Its response is parsed into Workflow IR and validated before it is accepted by the control plane.

## AgentCore runtime

The intended production runtime is Amazon Bedrock AgentCore Runtime. The current AWS Python deployment flow supports Strands-based agents and provides an AgentCore entrypoint; the AgentCore CLI can package and deploy the runtime.

Current official setup references:
- Strands Python SDK package: strands-agents
- AgentCore Python SDK package: bedrock-agentcore
- AgentCore CLI package: @aws/agentcore

Before deployment, configure AWS credentials, IAM permissions, model access, and a supported region.

## Architecture

Browser → API Gateway → FastAPI control plane → Specloom compiler → AgentCore Runtime → Bedrock.

Persistent context and project state will move to S3 and DynamoDB as the durable control plane is implemented.


## Ship It deployment

The repository now includes a deployable SAM control plane at `infra/aws/template.yaml`.

It provisions API Gateway, Lambda, DynamoDB, S3, EventBridge scheduling, and CloudWatch logging. The Lambda entrypoint routes HTTP traffic to FastAPI and scheduled EventBridge events into the stored workflow runtime.

For the Agents/AI path, set:

```
SPECL00M_RUNTIME_MODE=sagemaker
SPECL00M_SAGEMAKER_ENDPOINT_NAME=<endpoint>
```

SageMaker AI supports real-time inference endpoints that can be invoked with the SageMaker Runtime SDK. Current AWS documentation also describes OpenAI-compatible real-time endpoint paths for supported serving containers.

Deployment commands:

```bash
sam build --template-file infra/aws/template.yaml
sam deploy --guided --template-file .aws-sam/build/template.yaml
```
