#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORK_DIR="${TMPDIR:-/tmp}/webu-smoke"

run_case() {
    local case_name="$1"
    local extras="$2"
    local venv_dir="$WORK_DIR/$case_name"

    echo "=== CASE $case_name ==="
    rm -rf "$venv_dir"
    python3 -m venv "$venv_dir"
    "$venv_dir/bin/python" -m pip install --upgrade pip setuptools wheel
    if [[ -n "$extras" ]]; then
        "$venv_dir/bin/python" -m pip install -e "$ROOT_DIR[$extras]"
    else
        "$venv_dir/bin/python" -m pip install -e "$ROOT_DIR"
    fi
    "$venv_dir/bin/python" "$ROOT_DIR/debugs/smoke_install_extras.py" "$case_name"
}

mkdir -p "$WORK_DIR"

run_case base ""
run_case parsing "parsing"
run_case browser "browser"
run_case captcha "captcha"
run_case google-api "google-api"
run_case google-api-panel "google-api,google-api-panel"
run_case google-hub "google-hub"
run_case google-hub-panel "google-hub,google-hub-panel"
run_case google-docker "google-docker"
run_case google-docker-panel "google-docker,google-docker-panel"
run_case proxy-api "proxy-api"
run_case warp-api "warp-api"
run_case ipv6 "ipv6"

echo "ALL PASS"