#!/usr/bin/env bash
# Needs Node 22.13+, Python 3 with Playwright + Chromium (browser tests only).
set -e
python3 build.py engine && python3 build.py core && python3 build.py app
node tests/core.test.js
(cd backend && node --disable-warning=ExperimentalWarning --test tests/api.test.js)
python3 tests/e2e.py                      # standalone file mode
NS_MODE=server python3 tests/e2e.py       # against the real backend
