#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

export AWS_REGION="${AWS_REGION:-ap-south-1}"

sam build --template-file infra/aws/template.yaml
sam deploy \
  --config-file samconfig.toml \
  --template-file .aws-sam/build/template.yaml \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset

echo
echo "Specloom AWS deployment complete."
aws cloudformation describe-stacks --stack-name specloom --query 'Stacks[0].Outputs' --output table
