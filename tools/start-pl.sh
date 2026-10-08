#!/bin/sh
set -eu
case "${HOST_JOBS_DIR:-}" in
  /*) ;;
  *) echo 'HOST_JOBS_DIR must be an absolute existing host directory' >&2; exit 64 ;;
esac
# Compose binds /jobs with create_host_path=false: a missing host directory
# fails before this entrypoint runs. The host path is passed to sibling graders.
exec "$@"
