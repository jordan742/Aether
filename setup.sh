#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  Aether Fund One — Deployment Script (Linux / macOS)
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

CYAN='\033[0;36m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'

log()  { echo -e "${CYAN}[setup]${NC} $*"; }
ok()   { echo -e "${GREEN}[  OK  ]${NC} $*"; }
warn() { echo -e "${YELLOW}[ WARN ]${NC} $*"; }
die()  { echo -e "${RED}[ERROR ]${NC} $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "\n${BOLD}${CYAN}╔══════════════════════════════════════════╗"
echo    "║   AETHER FUND ONE — SYSTEM SETUP v3.0   ║"
echo -e "╚══════════════════════════════════════════╝${NC}\n"

# ── 1. Python version check ────────────────────────────────────────────────────
log "Checking Python version…"
PYTHON=$(command -v python3 || command -v python || die "Python not found.")
PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [[ "$PY_MAJOR" -lt 3 || ("$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 12) ]]; then
    die "Python 3.12+ required. Found $PY_VER."
fi
ok "Python $PY_VER"

# ── 2. Virtual environment ─────────────────────────────────────────────────────
if [[ ! -d ".venv" ]]; then
    log "Creating virtual environment (.venv)…"
    "$PYTHON" -m venv .venv
    ok "Virtual environment created."
else
    ok "Virtual environment already exists."
fi

# Activate
source .venv/bin/activate
PIP=".venv/bin/pip"

# ── 3. Install dependencies ────────────────────────────────────────────────────
log "Installing dependencies from requirements.txt…"
"$PIP" install --upgrade pip --quiet
"$PIP" install \
    streamlit \
    "alpaca-py>=0.26.0" \
    "yfinance>=0.2.40" \
    pandas \
    plotly \
    "opencv-python-headless>=4.10.0" \
    "cryptography>=42.0.0" \
    "ultralytics>=8.2.0" \
    "onnxruntime>=1.18.0" \
    "sentinelsat>=1.2.1" \
    "python-dotenv>=1.0.0" \
    "httpx>=0.27.0" \
    "shapely>=2.0.0" \
    "numpy>=1.26.0" \
    "Pillow>=10.0.0" \
    --quiet
ok "Dependencies installed."

# ── 4. Generate .env file ──────────────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
    log "Generating .env from .env.example…"
    cp .env.example .env

    # Auto-generate Fernet key
    FERNET_KEY=$(.venv/bin/python -c \
        "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    # Replace the placeholder in .env
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|TELEMETRY_FERNET_KEY=|TELEMETRY_FERNET_KEY=${FERNET_KEY}|" .env
    else
        sed -i "s|TELEMETRY_FERNET_KEY=|TELEMETRY_FERNET_KEY=${FERNET_KEY}|" .env
    fi
    ok ".env created with auto-generated Fernet key."
    warn "Edit .env to add your ALPACA_API_KEY and ALPACA_SECRET_KEY before trading."
else
    ok ".env already exists — skipping generation."
fi

# ── 5. Create shared + logs directories ────────────────────────────────────────
mkdir -p shared logs
ok "Directories: shared/ logs/ ready."

# ── 6. Launch run_system.py + Streamlit dashboard ─────────────────────────────
log "Launching Aether Fund One…"
echo ""
echo -e "${BOLD}  Orion  →  on_orbit_sim.py  (logs/on_orbit_sim.log)"
echo -e "  Midas  →  trader.py          (logs/trader.log)"
echo -e "  Health →  shared/system_health.log"
echo -e "  UI     →  http://localhost:8501${NC}"
echo ""

# Start the process manager in the background
.venv/bin/python run_system.py &
RUN_PID=$!
echo -e "${GREEN}[  OK  ]${NC} run_system.py started (PID $RUN_PID)"

# Give agents 3 seconds to initialise before opening the dashboard
sleep 3

# Launch Streamlit (foreground — exits when user presses Ctrl-C)
trap "kill $RUN_PID 2>/dev/null; echo -e '\n${CYAN}[setup]${NC} System shutdown.'" EXIT
.venv/bin/streamlit run dashboard/dashboard.py \
    --server.port 8501 \
    --server.headless true \
    --theme.base dark \
    --theme.backgroundColor "#0E1117" \
    --theme.primaryColor "#00D4FF" \
    --theme.textColor "#C9D1D9"
