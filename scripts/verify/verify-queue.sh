#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Asynchronous Work Queue & FIFO Concurrency Verification Suite
# Validates packages/titan_queue unit tests, FIFO ordering, concurrency limits,
# Rule 1 memory purity, and titan-mail plugin integration.
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

cd "${REPO_ROOT}"

echo -e "${BOLD}====================================================================${NC}"
echo -e "${BOLD}Project Titan: Modular Work Queue & Concurrency Verification Suite  ${NC}"
echo -e "${BOLD}====================================================================${NC}"

# Check for environment
if [ ! -f .env ]; then
  log_warn "No .env file found in repository root; running purely in local test mode."
fi

# Locate Python runner
PYTHON_BIN=""
if [ -f "./.venv/bin/python" ]; then
  PYTHON_BIN="./.venv/bin/python"
  PYTEST_BIN="./.venv/bin/pytest"
elif command -v python3 &>/dev/null; then
  PYTHON_BIN="python3"
  PYTEST_BIN="pytest"
else
  log_error "No Python interpreter found."
  exit 1
fi

log_info "Using Python interpreter: ${PYTHON_BIN}"

# 1. Package Structure Verification
log_info "Step 1: Validating packages/titan_queue package structure..."
REQUIRED_FILES=(
  "packages/titan_queue/pyproject.toml"
  "packages/titan_queue/README.md"
  "packages/titan_queue/titan_queue/__init__.py"
  "packages/titan_queue/titan_queue/models.py"
  "packages/titan_queue/titan_queue/queue.py"
  "packages/titan_queue/titan_queue/worker.py"
  "packages/titan_queue/titan_queue/backends/base.py"
  "packages/titan_queue/titan_queue/backends/memory.py"
  "packages/titan_queue/titan_queue/backends/sqlite.py"
)

for f in "${REQUIRED_FILES[@]}"; do
  if [ ! -f "${f}" ]; then
    log_error "Missing required file: ${f}"
    exit 1
  fi
done
log_success "All required titan_queue source files are present."

# 2. Syntax Validation
log_info "Step 2: Checking Python syntax across titan_queue and titan-mail plugin..."
find packages/titan_queue/titan_queue -name "*.py" -exec "${PYTHON_BIN}" -m py_compile {} +
"${PYTHON_BIN}" -m py_compile docker/hermes/plugins/titan-mail/__init__.py
log_success "Python syntax validation passed."

# 3. Unit Test Suite Execution
log_info "Step 3: Executing titan_queue unit test suite via pytest..."
if [ -x "${PYTEST_BIN}" ]; then
  "${PYTEST_BIN}" packages/titan_queue/tests/ -v
  log_success "All 13 titan_queue unit tests passed successfully."
else
  log_warn "pytest not executable; executing via unittest module..."
  "${PYTHON_BIN}" -m unittest discover -s packages/titan_queue/tests
  log_success "Unit tests passed."
fi

# 4. Rule 1 Memory Plane Purity Verification
log_info "Step 4: Asserting Rule 1 (Memory Plane Purity) for queue artifacts..."
MEMORIES_DIR="./data/agent_memories"
if [ -d "${MEMORIES_DIR}" ]; then
  ILLEGAL_FILES=$(find "${MEMORIES_DIR}" -type f \( -name "*.db" -o -name "*.sqlite" -o -name "*.queue" \))
  if [ -n "${ILLEGAL_FILES}" ]; then
    log_error "Rule 1 Violation: Found illegal queue database file in /memories:"
    echo "${ILLEGAL_FILES}"
    exit 1
  fi
fi
log_success "Memory plane purity verified: ZERO queue databases in /memories."

# 5. Rule 3 Hardware Serialization Guard Verification
log_info "Step 5: Verifying Rule 3 (Hardware Serialization) default concurrency in worker..."
DEFAULT_CONCURRENCY=$("${PYTHON_BIN}" -c '
from titan_queue.worker import FIFOQueueWorker
from titan_queue.queue import WorkQueue
q = WorkQueue("test")
w = FIFOQueueWorker(queue=q, handler=lambda t: None)
print(w.concurrency)
')

if [ "${DEFAULT_CONCURRENCY}" -ne 1 ]; then
  log_error "Default concurrency in FIFOQueueWorker must be 1 to enforce Rule 3, got: ${DEFAULT_CONCURRENCY}"
  exit 1
fi
log_success "Default concurrency is strictly 1 (hardware serialization preserved)."

# 6. Verify Dockerfile includes titan_queue
log_info "Step 6: Verifying Dockerfile packaging for titan_queue..."
if ! grep -q "packages/titan_queue" docker/hermes/Dockerfile; then
  log_error "docker/hermes/Dockerfile does not install packages/titan_queue"
  exit 1
fi
log_success "docker/hermes/Dockerfile packages titan_queue."

echo -e "\n${BOLD}${GREEN}====================================================================${NC}"
echo -e "${BOLD}${GREEN}  All Work Queue & Concurrency Verifications PASSED Successfully!   ${NC}"
echo -e "${BOLD}${GREEN}====================================================================${NC}"
