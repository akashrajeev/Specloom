#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

sam build --template-file infra/aws/template.yaml
sam deploy --guided --template-file .aws-sam/build/template.yaml
