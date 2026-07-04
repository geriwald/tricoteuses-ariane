#!/bin/sh
set -e

BUNDLE="${BUNDLE_PATH:-/app/data/2026-07-02-matin}"
PORT_DEMO="${PORT_DEMO:-8100}"
PORT_SERVE="${PORT_SERVE:-8080}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"

echo "==> Ariane Demo — starting demo_replay on :$PORT_DEMO (bundle: $BUNDLE)"
python b4-ui/demo_replay.py --bundle "$BUNDLE" --port "$PORT_DEMO" &

echo "==> Waiting for demo_replay to listen..."
for i in $(seq 1 30); do
  if python -c "import socket;s=socket.socket();s.settimeout(1);s.connect(('$BACKEND_HOST',$PORT_DEMO));s.close()" 2>/dev/null; then
    echo "==> demo_replay ready (attempt $i)"
    break
  fi
  sleep 1
done

echo "==> Starting serve on :$PORT_SERVE (proxies /thread /video.mp4 → $BACKEND_HOST:$PORT_DEMO)"
exec python b4-ui/serve.py --port "$PORT_SERVE" \
                           --backend-host "$BACKEND_HOST" \
                           --backend-port "$PORT_DEMO"
