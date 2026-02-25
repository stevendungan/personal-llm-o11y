#!/usr/bin/env bash
set -euo pipefail

# Colors for output (matches install-hook.sh)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$HOME/.claude/state"
STATE_FILES=("langfuse_hook.log" "langfuse_state.json" "pending_traces.jsonl")

AUTO_YES=false
KEEP_STATE=false

usage() {
    echo "Usage: $0 [--yes] [--keep-state]"
    echo ""
    echo "Wipe all Docker volumes and local state files, then restart services."
    echo ""
    echo "Flags:"
    echo "  --yes          Skip confirmation prompt"
    echo "  --keep-state   Only wipe Docker volumes, keep local state files"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes) AUTO_YES=true; shift ;;
        --keep-state) KEEP_STATE=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo -e "${RED}Unknown flag: $1${NC}"; usage; exit 1 ;;
    esac
done

echo "====================================="
echo "  Langfuse Data Flush"
echo "====================================="
echo ""

# --- Show current disk usage ---
echo -e "${YELLOW}Docker volume usage:${NC}"
docker system df -v 2>/dev/null | grep -A 100 "^VOLUME" | head -20 || echo "  (Docker not running or no volumes)"
echo ""

if [ "$KEEP_STATE" = false ]; then
    echo -e "${YELLOW}Local state files:${NC}"
    for f in "${STATE_FILES[@]}"; do
        filepath="$STATE_DIR/$f"
        if [ -f "$filepath" ]; then
            size=$(stat -f%z "$filepath" 2>/dev/null || stat -c%s "$filepath" 2>/dev/null || echo "?")
            echo "  $filepath  ($size bytes)"
        else
            echo "  $filepath  (not found)"
        fi
    done
    echo ""
fi

# --- Confirm ---
if [ "$AUTO_YES" = false ]; then
    echo -e "${RED}This will destroy all Langfuse data (traces, projects, users).${NC}"
    if [ "$KEEP_STATE" = true ]; then
        echo "Local state files will be kept."
    else
        echo "Local state files will also be removed."
    fi
    echo ""
    read -rp "Continue? [y/N] " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
    echo ""
fi

# --- Tear down ---
echo -e "${YELLOW}Stopping services and removing volumes...${NC}"
cd "$REPO_ROOT"
docker compose down -v
echo -e "${GREEN}✓ Docker volumes removed${NC}"

# --- Remove state files ---
if [ "$KEEP_STATE" = false ]; then
    echo ""
    echo -e "${YELLOW}Removing local state files...${NC}"
    for f in "${STATE_FILES[@]}"; do
        filepath="$STATE_DIR/$f"
        if [ -f "$filepath" ]; then
            rm "$filepath"
            echo -e "${GREEN}✓ Removed $filepath${NC}"
        fi
    done
fi

# --- Restart ---
echo ""
echo -e "${YELLOW}Restarting services...${NC}"
cd "$REPO_ROOT"
docker compose up -d
echo ""

echo -e "${YELLOW}Waiting for health checks...${NC}"
for i in $(seq 1 30); do
    if docker compose ps --format json 2>/dev/null | python3 -c "
import sys, json
lines = sys.stdin.read().strip().split('\n')
services = [json.loads(l) for l in lines if l]
unhealthy = [s['Service'] for s in services if s.get('Health','') not in ('healthy','')]
sys.exit(0 if not unhealthy else 1)
" 2>/dev/null; then
        echo -e "${GREEN}✓ All services healthy${NC}"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo -e "${YELLOW}⚠ Timed out waiting for health checks. Run 'docker compose ps' to inspect.${NC}"
        break
    fi
    sleep 2
done

echo ""
echo "====================================="
echo -e "${GREEN}  Flush complete${NC}"
echo "====================================="
echo ""
echo "Next steps:"
echo "  1. Open http://localhost:3050 and log in"
echo "  2. Start a Claude Code conversation to generate new traces"
echo ""
