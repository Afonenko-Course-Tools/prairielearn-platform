#!/bin/bash
set -euo pipefail
# cwd — native workspaceOptions.home; PL восстанавливает его до запуска image.
python3 "$(dirname -- "$0")/sp-git-workspace-init.py"
if [[ "$#" -eq 0 ]]; then
  set -- /entrypoint.sh
fi
exec "$@"
