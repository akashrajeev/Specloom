# AWS continuous deployment

Specloom uses GitHub Actions for controlled production deployment of the AWS SAM backend.

## Release flow

A change follows this path:

`feature branch` → `pull request` → CI verification → `main` → AWS deployment

The deployment workflow runs the backend test suite, builds the React frontend, validates the SAM template, assumes a dedicated AWS deployment role through GitHub OIDC, deploys `infra/aws/template.yaml`, and calls the deployed `/health` endpoint.

AWS authentication uses short-lived OIDC credentials rather than a long-lived AWS access key. AWS OIDC is used so the workflow receives short-lived credentials instead of storing long-lived access keys.

## One-time AWS setup

Create a GitHub OIDC identity provider in IAM for:

`https://token.actions.githubusercontent.com`

with audience:

`sts.amazonaws.com`

Create a dedicated IAM role for GitHub Actions and restrict its trust policy to this repository and the `production` GitHub environment.

The trust relationship should target:

`repo:akashrajeev/Specloom:environment:production`

Then add the role ARN as the GitHub Actions secret:

`AWS_DEPLOY_ROLE_ARN`

The deployment workflow will fail at the AWS credential step until this secret exists.

For the permissions policy, grant the deployment role only the AWS APIs required to manage the resources in `infra/aws/template.yaml` and to upload SAM deployment artifacts. Do not store an AWS access key or secret key in the repository.

## Frontend hosting

The React frontend is configured for AWS Amplify Hosting in `infra/aws/amplify.yml`. Amplify Hosting supports Git-connected continuous deployment for React applications and uses the repository build settings file when present.

Connect the `main` branch to Amplify Hosting and set:

`VITE_API_BASE_URL=<the ApiUrl output from the Specloom CloudFormation stack>`

Amplify documents environment variables for Git-connected applications in the Hosting console. citeturn397396search12

After this one-time connection, pushes to `main` update the frontend automatically while the GitHub Actions deployment workflow updates the backend.

## What the agent can do

An agent can change application code, tests, infrastructure templates, documentation, and workflow files in the repository. Once the changes are committed to `main`, GitHub Actions is the deployment control plane: it verifies the change and deploys the AWS stack automatically.

The agent should not receive permanent AWS credentials. AWS OIDC keeps deployment authorization in the CI environment.
