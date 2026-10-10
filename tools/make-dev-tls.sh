#!/bin/sh
# Compatible local TLS entrypoint; repeating it reuses the CA and healthy leaf.
set -eu
case "${1:-}" in /*) target=$1 ;; *) echo 'Use an absolute private output directory' >&2; exit 64 ;; esac
shift
exec python3 "$(dirname "$0")/dev-tls.py" ensure --directory "$target" "$@"
