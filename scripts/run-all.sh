#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ $EUID -ne 0 ]]; then
  echo 'Run: sudo bash scripts/run-all.sh' >&2
  exit 1
fi
for profile in baseline delay bandwidth loss geloss; do
  /usr/bin/python3 topology.py --profile "$profile" --test
done
