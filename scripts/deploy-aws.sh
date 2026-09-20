#!/usr/bin/env bash
set -euo pipefail

export AWS_REGION="${AWS_REGION:-ap-south-1}"

sam build --template-file template.yaml
sam deploy --config-env default --no-fail-on-empty-changeset

echo
echo "Specloom AWS deployment complete."
aws cloudformation describe-stacks --stack-name specloom --query 'Stacks[0].Outputs' --output table
