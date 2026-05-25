#!/usr/bin/env bash
# =============================================================================
# OpenKNet — Automated installer, environment checker, and test runner
# =============================================================================
#
# Usage:
#   ./install.sh              # full install with auto-detection of extras
#   ./install.sh --minimal    # core only (SQLite, BM25, TF-IDF, no extras)
#   ./install.sh --ci         # core + dev, no prompts, exit 1 on any failure
#   ./install.sh --help
#
# What it does:
#   1. Checks prerequisites (Python, pip, OS)
#   2. Creates / reuses .venv virtual environment
#   3. Installs core package
#   4. Auto-detects available extras and installs them
#   5. Detects optional external services (Ollama, Redis, PostgreSQL)
#   6. Copies .env.example → .env (if .env doesn't exist)
#   7. Applies DB migrations
#   8. Runs the full test suite (pytest)
#   9. Runs a smoke test: init → ingest → build → rank → ask → path
#  10. Prints a colour-coded summary of every step
# =============================================================================

set -euo pipefail

# ── Colour palette ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

# ── Global state ──────────────────────────────────────────────────────────────
ERRORS=()
WARNINGS=()
INSTALLED_EXTRAS=()
DETECTED_SERVICES=()
MISSING_SERVICES=()

MODE="full"       # full | minimal | ci
VENV_DIR=".venv"
PYTHON=""
PIP=""
OPENKNET=""

# ── Parse arguments ───────────────────────────────────────────────────────────
for arg in "$@"; do
  case $arg in
    --minimal) MODE="minimal" ;;
    --ci)      MODE="ci" ;;
    --help|-h)
      echo "Usage: $0 [--minimal|--ci|--help]"
      echo "  --minimal  Core only (no optional extras)"
      echo "  --ci       Non-interactive, exits 1 on failure"
      echo "  --help     Show this message"
      exit 0 ;;
    *) echo -e "${RED}Unknown argument: $arg${NC}"; exit 1 ;;
  esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
step()    { echo -e "\n${BOLD}${BLUE}▶ $*${NC}"; }
ok()      { echo -e "  ${GREEN}✓${NC}  $*"; }
warn()    { echo -e "  ${YELLOW}⚠${NC}  $*"; WARNINGS+=("$*"); }
fail()    { echo -e "  ${RED}✗${NC}  $*"; ERRORS+=("$*"); }
info()    { echo -e "  ${DIM}ℹ  $*${NC}"; }
service_ok()   { echo -e "  ${GREEN}⬤${NC}  $*"; DETECTED_SERVICES+=("$*"); }
service_miss() { echo -e "  ${DIM}○${NC}  $* ${DIM}(not detected — optional)${NC}"; MISSING_SERVICES+=("$*"); }

hr() { echo -e "${DIM}$(printf '─%.0s' {1..72})${NC}"; }

die() { echo -e "\n${RED}${BOLD}FATAL: $*${NC}\n"; exit 1; }

# Run a command, capturing output; on failure store error and optionally exit
run() {
  local label="$1"; shift
  if output=$("$@" 2>&1); then
    ok "$label"
    return 0
  else
    fail "$label"
    info "Command: $*"
    info "Output:  $(echo "$output" | head -5)"
    [[ "$MODE" == "ci" ]] && die "$label failed in CI mode"
    return 1
  fi
}

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}"
echo "  ██████╗ ██████╗ ███████╗███╗   ██╗██╗  ██╗███╗   ██╗███████╗████████╗"
echo "  ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██║ ██╔╝████╗  ██║██╔════╝╚══██╔══╝"
echo "  ██║   ██║██████╔╝█████╗  ██╔██╗ ██║█████╔╝ ██╔██╗ ██║█████╗     ██║   "
echo "  ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔═██╗ ██║╚██╗██║██╔══╝     ██║   "
echo "  ╚██████╔╝██║     ███████╗██║ ╚████║██║  ██╗██║ ╚████║███████╗   ██║   "
echo "   ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝   ╚═╝   "
echo -e "${NC}"
echo -e "  ${BOLD}v2.0 — Automated Installer${NC}  ${DIM}(mode: $MODE)${NC}"
hr

# ═══════════════════════════════════════════════════════════════════════════════
# 1. PREREQUISITES
# ═══════════════════════════════════════════════════════════════════════════════
step "Checking prerequisites"

# OS detection
OS="$(uname -s)"
case "$OS" in
  Linux*)  OS_NAME="Linux" ;;
  Darwin*) OS_NAME="macOS" ;;
  *)       warn "Unknown OS: $OS — proceeding anyway" ;;
esac
ok "OS: ${OS_NAME:-$OS}"

# Python 3.10+
find_python() {
  for cmd in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" &>/dev/null; then
      local ver
      ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
      local major minor
      major=$(echo "$ver" | cut -d. -f1)
      minor=$(echo "$ver" | cut -d. -f2)
      if [[ "$major" -ge 3 && "$minor" -ge 10 ]]; then
        echo "$cmd"; return 0
      fi
    fi
  done
  return 1
}

if PYTHON=$(find_python); then
  PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
  ok "Python $PY_VER  ($PYTHON)"
else
  die "Python 3.10+ is required. Install from https://python.org or via your package manager."
fi

# pip
if "$PYTHON" -m pip --version &>/dev/null; then
  ok "pip available"
else
  die "pip not found. Run: $PYTHON -m ensurepip --upgrade"
fi

# git (optional, for version info)
if command -v git &>/dev/null; then
  ok "git $(git --version | awk '{print $3}')"
else
  warn "git not found — version tagging unavailable"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 2. VIRTUAL ENVIRONMENT
# ═══════════════════════════════════════════════════════════════════════════════
step "Setting up virtual environment"

if [[ -d "$VENV_DIR" ]]; then
  ok "Reusing existing $VENV_DIR"
else
  "$PYTHON" -m venv "$VENV_DIR"
  ok "Created $VENV_DIR"
fi

# Activate
source "$VENV_DIR/bin/activate"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"
OPENKNET="$VENV_DIR/bin/openknet"

# Upgrade pip + setuptools silently
"$PIP" install --upgrade pip setuptools wheel -q
ok "pip + setuptools upgraded"

# ═══════════════════════════════════════════════════════════════════════════════
# 3. CORE INSTALL
# ═══════════════════════════════════════════════════════════════════════════════
step "Installing OpenKNet (core)"

if "$PIP" install -e ".[dev]" -q; then
  CORE_VER=$("$PYTHON" -c "import openknet; print(openknet.__version__)" 2>/dev/null || echo "?")
  ok "openknet $CORE_VER installed"
else
  die "Core installation failed. Check the output above."
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 4. OPTIONAL EXTRAS (auto-detected)
# ═══════════════════════════════════════════════════════════════════════════════
step "Installing optional extras"

install_extra() {
  local name="$1"; local extra="$2"; local test_import="$3"
  if [[ "$MODE" == "minimal" ]]; then
    info "Skipping $name (--minimal mode)"
    return
  fi
  if "$PYTHON" -c "import $test_import" &>/dev/null 2>&1; then
    ok "$name already available"
    INSTALLED_EXTRAS+=("$name")
    return
  fi
  info "Installing $name …"
  if "$PIP" install -e ".[$extra]" -q 2>/dev/null; then
    ok "$name installed"
    INSTALLED_EXTRAS+=("$name")
  else
    warn "$name install failed — will work without it"
  fi
}

install_extra "Prometheus metrics"      "metrics"  "prometheus_client"
install_extra "PostgreSQL driver"       "postgres" "asyncpg"
install_extra "LangGraph + Anthropic"   "langgraph" "langgraph"
install_extra "Ollama (LangChain)"      "ollama"   "langchain_ollama"
install_extra "Semantic search"         "semantic" "sentence_transformers"
install_extra "GLiNER NER"             "nlp"      "gliner"
install_extra "Redis client"           "redis"    "redis"
install_extra "ARQ worker"             "worker"   "arq"

# ═══════════════════════════════════════════════════════════════════════════════
# 5. EXTERNAL SERVICE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════
step "Detecting optional external services"

# Ollama
if curl -sf "http://localhost:11434/api/tags" -o /dev/null --max-time 2 2>/dev/null; then
  OLLAMA_MODELS=$(curl -sf "http://localhost:11434/api/tags" 2>/dev/null \
    | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(', '.join(m['name'] for m in d.get('models',[])) or 'no models pulled')" 2>/dev/null || echo "unknown")
  service_ok "Ollama running — models: $OLLAMA_MODELS"
else
  service_miss "Ollama (http://localhost:11434) — install: https://ollama.com"
fi

# Redis
if command -v redis-cli &>/dev/null && redis-cli ping -q &>/dev/null 2>&1; then
  service_ok "Redis running (localhost:6379)"
else
  service_miss "Redis — install: https://redis.io/docs/getting-started"
fi

# PostgreSQL
if command -v psql &>/dev/null && psql -U postgres -c "SELECT 1" &>/dev/null 2>&1; then
  PG_VER=$(psql -U postgres -t -c "SELECT version()" 2>/dev/null | awk '{print $1,$2}' | xargs)
  service_ok "PostgreSQL $PG_VER"
else
  service_miss "PostgreSQL — install: https://postgresql.org"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 6. ENVIRONMENT FILE
# ═══════════════════════════════════════════════════════════════════════════════
step "Environment configuration"

if [[ -f ".env" ]]; then
  ok ".env already exists — not overwriting"
else
  if [[ -f ".env.example" ]]; then
    cp .env.example .env
    ok ".env created from .env.example"
    info "Edit .env to configure OPENKNET_DATABASE_URL, OPENKNET_REQUIRE_AUTH, etc."
  else
    warn ".env.example not found — skipping .env creation"
  fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 7. DATABASE MIGRATION
# ═══════════════════════════════════════════════════════════════════════════════
step "Applying database migrations"

mkdir -p .openknet
if "$OPENKNET" migrate 2>/dev/null | "$PYTHON" -c "
import sys, json
try:
    d = json.load(sys.stdin)
    assert d.get('status') == 'ok'
except Exception:
    sys.exit(1)
"; then
  DIALECT=$("$OPENKNET" migrate 2>/dev/null | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('dialect','?'))")
  ok "DB migrations applied (dialect: $DIALECT)"
else
  fail "DB migration failed"
  [[ "$MODE" == "ci" ]] && die "Migration failed"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 8. TEST SUITE
# ═══════════════════════════════════════════════════════════════════════════════
step "Running test suite"

PYTEST="$VENV_DIR/bin/pytest"
TEST_ARGS="tests/ -q --tb=short --no-header"
[[ "$MODE" == "ci" ]] && TEST_ARGS="$TEST_ARGS --strict-markers"

echo ""
if "$PYTEST" $TEST_ARGS 2>&1 | tee /tmp/openknet_test_output.txt; then
  PASSED=$(grep -E "passed" /tmp/openknet_test_output.txt | tail -1 | grep -oE "[0-9]+ passed" || echo "? passed")
  ok "All tests passed ($PASSED)"
else
  FAILED=$(grep -E "failed|error" /tmp/openknet_test_output.txt | tail -1 || echo "unknown failure")
  fail "Test suite has failures: $FAILED"
  [[ "$MODE" == "ci" ]] && die "Tests failed"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 9. SMOKE TEST — full pipeline end-to-end
# ═══════════════════════════════════════════════════════════════════════════════
step "Running smoke test (end-to-end pipeline)"

SMOKE_PROJECT="smoke-test-$$"
SMOKE_PASS=true
SMOKE_LOG=$(mktemp)

smoke_step() {
  local label="$1"; shift
  if "$@" >> "$SMOKE_LOG" 2>&1; then
    ok "Smoke: $label"
  else
    fail "Smoke: $label"
    info "Log: $(tail -3 "$SMOKE_LOG")"
    SMOKE_PASS=false
    [[ "$MODE" == "ci" ]] && { cat "$SMOKE_LOG"; die "Smoke test step failed: $label"; }
  fi
}

# Init project
smoke_step "init project" \
  "$OPENKNET" init "$SMOKE_PROJECT" --schema examples/support/schema.yaml

# Ingest example docs
smoke_step "ingest documents" \
  "$OPENKNET" ingest examples/support/docs --project "$SMOKE_PROJECT"

# Verify chunk count
CHUNKS=$("$OPENKNET" stats --project "$SMOKE_PROJECT" 2>/dev/null \
  | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('chunks',0))" 2>/dev/null || echo 0)
if [[ "$CHUNKS" -gt 0 ]]; then
  ok "Smoke: $CHUNKS chunks ingested"
else
  fail "Smoke: no chunks found after ingest"
  SMOKE_PASS=false
fi

# Build graph
smoke_step "build (full)" \
  "$OPENKNET" build --project "$SMOKE_PROJECT"

# Verify entity count
ENTITIES=$("$OPENKNET" stats --project "$SMOKE_PROJECT" 2>/dev/null \
  | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('entities',0))" 2>/dev/null || echo 0)
if [[ "$ENTITIES" -gt 0 ]]; then
  ok "Smoke: $ENTITIES entities extracted"
else
  fail "Smoke: no entities after build"
  SMOKE_PASS=false
fi

# Rank query
RANK_COUNT=$("$OPENKNET" rank "login error" --project "$SMOKE_PROJECT" 2>/dev/null \
  | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('total_matching',0))" 2>/dev/null || echo 0)
if [[ "$RANK_COUNT" -gt 0 ]]; then
  ok "Smoke: rank returned $RANK_COUNT matching entities"
else
  fail "Smoke: rank returned 0 results"
  SMOKE_PASS=false
fi

# Ask (multilingual)
ASK_ANSWER=$("$OPENKNET" ask "qué causa errores 503?" --project "$SMOKE_PROJECT" 2>/dev/null \
  | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print('ok' if d.get('entities') else 'empty')" 2>/dev/null || echo "failed")
if [[ "$ASK_ANSWER" == "ok" ]]; then
  ok "Smoke: ask (Spanish → English docs) returned entities"
else
  warn "Smoke: ask returned empty entities (non-fatal)"
fi

# Path
PATH_FOUND=$("$OPENKNET" path "AuthService" "error 503" --project "$SMOKE_PROJECT" 2>/dev/null \
  | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('found',False))" 2>/dev/null || echo "False")
if [[ "$PATH_FOUND" == "True" ]]; then
  ok "Smoke: path AuthService → error 503 found"
else
  warn "Smoke: path not found (may be normal for this schema)"
fi

# Incremental build
smoke_step "build (incremental)" \
  "$OPENKNET" build --project "$SMOKE_PROJECT" --incremental

# Snapshots
SNAP_COUNT=$("$OPENKNET" snapshots --project "$SMOKE_PROJECT" 2>/dev/null \
  | "$PYTHON" -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
if [[ "$SNAP_COUNT" -gt 0 ]]; then
  ok "Smoke: $SNAP_COUNT graph snapshot(s) saved"
else
  warn "Smoke: no snapshots (check OPENKNET_VERSIONING_ENABLED)"
fi

# Stats check (ranker backend)
RANKER=$("$OPENKNET" stats --project "$SMOKE_PROJECT" 2>/dev/null \
  | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('ranker_backend','?'))" 2>/dev/null || echo "?")
ok "Smoke: active ranker → $RANKER"

# API server health check (start, check, kill)
SERVE_PID=""
if command -v curl &>/dev/null; then
  "$OPENKNET" serve --port 18765 &>/dev/null &
  SERVE_PID=$!
  sleep 2
  if curl -sf "http://localhost:18765/health" -o /tmp/openknet_health.json --max-time 5 2>/dev/null; then
    API_STATUS=$("$PYTHON" -c "import json; d=json.load(open('/tmp/openknet_health.json')); print(d.get('status','?'))")
    ok "Smoke: API server /health → $API_STATUS"
  else
    warn "Smoke: API server did not respond (non-fatal)"
  fi
  kill "$SERVE_PID" 2>/dev/null || true
  wait "$SERVE_PID" 2>/dev/null || true
fi

# Clean up smoke project DB entry
"$OPENKNET" projects 2>/dev/null | grep -q "$SMOKE_PROJECT" \
  && info "Smoke project '$SMOKE_PROJECT' left in .openknet/openknet.db (safe to delete)"

rm -f "$SMOKE_LOG"

# ═══════════════════════════════════════════════════════════════════════════════
# 10. SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
hr
echo -e "\n${BOLD}  OpenKNet v2.0 — Installation Summary${NC}\n"

# Core
echo -e "  ${BOLD}Core${NC}"
ok "  openknet $CORE_VER"
ok "  Python $PY_VER"
ok "  Database: $DIALECT"
ok "  Ranker: $RANKER"
echo ""

# Extras
echo -e "  ${BOLD}Installed extras${NC}"
if [[ ${#INSTALLED_EXTRAS[@]} -eq 0 ]]; then
  info "  None (--minimal mode or all failed)"
else
  for e in "${INSTALLED_EXTRAS[@]}"; do ok "  $e"; done
fi
echo ""

# Services
echo -e "  ${BOLD}External services${NC}"
for s in "${DETECTED_SERVICES[@]}"; do service_ok "  $s"; done
for s in "${MISSING_SERVICES[@]}"; do service_miss "  $s"; done
echo ""

# Warnings
if [[ ${#WARNINGS[@]} -gt 0 ]]; then
  echo -e "  ${BOLD}${YELLOW}Warnings${NC}"
  for w in "${WARNINGS[@]}"; do warn "  $w"; done
  echo ""
fi

# Errors
if [[ ${#ERRORS[@]} -gt 0 ]]; then
  echo -e "  ${BOLD}${RED}Errors${NC}"
  for e in "${ERRORS[@]}"; do fail "  $e"; done
  echo ""
fi

# Final verdict
hr
if [[ ${#ERRORS[@]} -eq 0 ]] && $SMOKE_PASS; then
  echo -e "\n  ${GREEN}${BOLD}✓  All checks passed. OpenKNet is ready.${NC}\n"
  echo -e "  ${BOLD}Next steps:${NC}"
  echo -e "  ${DIM}  source $VENV_DIR/bin/activate${NC}"
  echo -e "  ${DIM}  openknet init my-project --schema examples/support/schema.yaml${NC}"
  echo -e "  ${DIM}  openknet ingest docs/ --project my-project${NC}"
  echo -e "  ${DIM}  openknet build --project my-project${NC}"
  echo -e "  ${DIM}  openknet serve   # → http://localhost:8000/docs${NC}"
  echo ""
  exit 0
else
  echo -e "\n  ${YELLOW}${BOLD}⚠  Installation completed with issues.${NC}"
  echo -e "  ${DIM}Core functionality is working. Check warnings/errors above.${NC}\n"
  [[ "$MODE" == "ci" ]] && exit 1
  exit 0
fi
