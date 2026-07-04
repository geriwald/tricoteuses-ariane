#!/usr/bin/env bash
# Ariane demo launcher — B2 (replay) + B1 (weaver) + B4 (UI) on one host.
#
# Everything machine-specific comes from the environment (or a .env you source
# first), so this stays public-safe:
#
#   ARIANE_RECORD   capture bundle to replay          (required)
#   B1_PYTHON       python with the GPU whisper stack  (default: the repo .venv,
#                   which is NOT enough for live STT — set this to a venv that
#                   has torch + faster-whisper, e.g. ~/code/whisper-live/.venv)
#   BRICK_PYTHON    python for B2/B4 (numpy only)      (default: repo .venv)
#   BIND            0.0.0.0 to reach the demo over Tailscale (default 127.0.0.1)
#   PROOFREAD       1 to enable the LLM relecture stage (needs `claude` on PATH)
#
# Usage:  [ set -a; . .env; set +a ]  then  ./demo/run.sh
# Stop:   Ctrl-C (kills the whole process group).
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
: "${ARIANE_RECORD:?set ARIANE_RECORD to a capture bundle (see .env.sample)}"
BRICK_PYTHON="${BRICK_PYTHON:-$repo/.venv/bin/python}"
B1_PYTHON="${B1_PYTHON:-$BRICK_PYTHON}"
BIND="${BIND:-127.0.0.1}"

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "B2 replay  : $ARIANE_RECORD  (bind $BIND:8000)"
"$BRICK_PYTHON" "$repo/b2-replay/server.py" \
    --record "$ARIANE_RECORD" --bind "$BIND" --port 8000 &
pids+=($!)
sleep 2  # let B2 bind before B1 starts polling its routes

pf=()
[ "${PROOFREAD:-}" = "1" ] && pf=(--proofread)
echo "B1 weaver  : STT off B2's video  (bind $BIND:8100, proofread=${PROOFREAD:-0})"
"$B1_PYTHON" "$repo/b1-weaver/weaver_live.py" \
    --source "http://127.0.0.1:8000/video" \
    --agenda "http://127.0.0.1:8000/local/derouleur/derouleur.json" \
    --actors "http://127.0.0.1:8000/referential/acteurs.json" \
    --organes "http://127.0.0.1:8000/referential/organes.json" \
    --bind "$BIND" --port 8100 --follow "${pf[@]}" &
pids+=($!)

echo "B4 UI      : http://$BIND:8080"
"$BRICK_PYTHON" "$repo/b4-ui/serve.py" --bind "$BIND" --port 8080 &
pids+=($!)

wait
