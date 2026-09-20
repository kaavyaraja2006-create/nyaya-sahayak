#!/usr/bin/env bash
# Needs Node 22.13+, Python 3 with Playwright + Chromium (browser tests only).
set -e
cd "$(dirname "$0")"
python3 build.py
node frontend/tests/core.test.js
node --disable-warning=ExperimentalWarning --test backend/tests/api.test.js backend/tests/workflow.test.js
python3 frontend/tests/e2e.py                       # standalone file mode
NS_MODE=server python3 frontend/tests/e2e.py        # against the real backend
python3 frontend/tests/e2e_standalone_court.py      # court workflow in the standalone build
python3 frontend/tests/e2e_workflow.py              # OTP, hearings, public tracking, marketplace, chat (server)
