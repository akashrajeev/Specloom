#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export AWS_REGION="${AWS_REGION:-ap-south-1}"

"${ROOT}/infra/aws/deploy.sh"
