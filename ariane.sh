#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

CMD="${1:-help}"

case "$CMD" in
  --launch|launch)
    echo "==> Building & starting Ariane Demo stack..."
    docker compose up -d --build
    echo ""
    echo "  Services:"
    echo "    demo_replay (SSE + video) → http://127.0.0.1:8100  (internal)"
    echo "    B4 UI (serve + proxy)    → http://127.0.0.1:8080  <- entry point"
    echo ""
    echo "  Open http://127.0.0.1:8080/demo.html"
    echo ""
    echo "  To expose publicly via Tailscale Funnel:"
    echo "    tailscale funnel 8080"
    echo "  Then open https://<machine>.ts.net/demo.html"
    echo ""
    echo "  Logs:  ./ariane.sh --logs"
    echo "  Stop:  ./ariane.sh --stop"
    ;;

  --stop|stop)
    echo "==> Stopping Ariane Demo stack..."
    docker compose down
    echo "  (tailscale funnel 8080 still active if running — stop it with: tailscale funnel off)"
    ;;

  --status|status)
    docker compose ps
    ;;

  --logs|logs)
    shift || true
    docker compose logs -f "$@"
    ;;

  --build|build)
    docker compose build "$@"
    ;;

  --restart|restart)
    docker compose down
    docker compose up -d
    ;;

  --funnel|funnel)
    echo "  tailscale funnel 8080"
    echo ""
    echo "  Exposes http://127.0.0.1:8080 and serves it on https://<machine>.ts.net/"
    echo "  Requires Tailscale to be installed and logged in."
    echo ""
    echo "  Then open https://<machine>.ts.net/demo.html"
    ;;

  --help|help|*)
    echo "Ariane Demo — offline causal replay of a sitting (docker)"
    echo ""
    echo "Usage:  $0 <command>"
    echo ""
    echo "  --launch        Build & start the demo container (docker compose up -d)"
    echo "  --stop          Stop the demo container (docker compose down)"
    echo "  --status        Show container status (docker compose ps)"
    echo "  --logs [svc]    Follow logs (optional: filter by service name)"
    echo "  --build         Rebuild image without restarting"
    echo "  --restart       Stop, then start again"
    echo "  --funnel        Show the Tailscale Funnel command"
    echo "  --help          This message"
    echo ""
    echo "Quick start:"
    echo "  ./ariane.sh --launch"
    echo "  tailscale funnel 8080"
    echo "  # open https://<machine>.ts.net/demo.html"
    echo ""
    echo "To change the bundle, set BUNDLE_PATH in docker-compose.override.yml"
    echo "  or edit docker-compose.yml before launching."
    ;;
esac
