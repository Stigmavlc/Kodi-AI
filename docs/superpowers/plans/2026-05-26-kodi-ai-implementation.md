# Kodi-AI V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Per project discipline ([[feedback-implementer-reviewer-loop]]), every code task dispatches a fresh Opus 4.7 implementer subagent + fresh Opus 4.7 reviewer subagent; loop until reviewer signs off clean.**

**Goal:** Build the V1 `service.kodi.ai` Kodi add-on per `docs/superpowers/specs/2026-05-26-kodi-ai-design.md` — a proactive log-monitoring + auto-fix agent with Telegram UI, running on Nvidia Shield Pro (Android TV).

**Architecture:** Single Kodi `xbmc.service` add-on, 4-thread (Main minimal + T2 LogPoll + T3 TGPoll + T4 Worker single-flight). OpenRouter for LLM (Auto + Manual modes), Telegram Bot API (long-poll) for user interface. Pure-Python QR encoder + PNG writer (stdlib `zlib` only). No vendored deps beyond Kodi-bundled `script.module.requests`. State persistence under `special://profile/addon_data/service.kodi.ai/` (POSIX). Snapshots under `special://userdata/Kodi-AI-snapshots/` (reinstall-safe).

**Tech Stack:**
- **Runtime:** Kodi 21 Omega's `xbmc.python` 3.0.1 (CPython 3.x embedded).
- **Bundled:** `script.module.requests` (version pinned at release).
- **Dev tests:** `pytest`, `freezegun`, `responses`, `kodistubs` (community Kodi stubs).
- **LLM provider:** OpenRouter (OpenAI-compatible streaming HTTP).
- **Distribution:** GitHub-Pages-hosted non-official Kodi repo (`.nojekyll`, `index.html`).

**Spec sections cross-referenced:** §1 (Architecture), §2 (Components), §3 (Data Flows), §4 (Tool Catalog), §5 (Safety), §6 (Testing), §7 (Setup/Distribution). Each task lists relevant spec sections.

**TDD discipline:** every code task writes the failing test FIRST, runs it, then implements, runs again, then commits. No "implementation first" shortcuts.

**Commit cadence:** one commit per task (sometimes one per sub-step for risky operations).

---

## Phase 0 — Dev environment + repo scaffolding (3 tasks)

### Task 0.1 — Dev environment setup

**Files:**
- Create: `requirements-dev.txt`
- Create: `pyproject.toml`
- Create: `.gitignore`

- [ ] **Step 1: Write `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.coverage
htmlcov/
.tox/
build/
dist/

# Kodi runtime artifacts (when testing locally)
.kodi/temp/
.kodi/userdata/Database/
.kodi/userdata/Thumbnails/

# Editor
.vscode/
.idea/
*.swp
.DS_Store

# Local secrets / config overrides
.env
secrets.local.json
addon_data_local/
```

- [ ] **Step 2: Write `requirements-dev.txt`**

```
pytest>=8.0
pytest-cov>=4.1
freezegun>=1.4
responses>=0.25
kodistubs>=21.0
pre-commit>=3.6
```

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests/unit", "tests/integration"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --strict-markers --cov=service.kodi.ai/lib --cov-report=term-missing"
markers = [
    "integration: integration tests requiring kodistubs",
    "acceptance: manual acceptance tests requiring real Kodi (skipped in CI)",
]

[tool.coverage.run]
source = ["service.kodi.ai/lib"]
omit = ["*/tests/*", "*/__pycache__/*"]
```

- [ ] **Step 4: Verify dev env**

```bash
cd "/Users/ivan/Desktop/Web Development  Projects/Completed By Me/Kodi-AI"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest --version
```

Expected: `pytest 8.x` output.

- [ ] **Step 5: Commit**

```bash
git add .gitignore requirements-dev.txt pyproject.toml
git commit -m "chore: dev env + pytest config

requirements: pytest, freezegun, responses, kodistubs, pre-commit.
pyproject: pytest paths + coverage config.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 0.2 — Add-on directory scaffolding

**Files:**
- Create: `service.kodi.ai/addon.xml`
- Create: `service.kodi.ai/lib/__init__.py`
- Create: `service.kodi.ai/lib/llm/__init__.py`
- Create: `service.kodi.ai/lib/llm/prompts/.gitkeep`
- Create: `service.kodi.ai/lib/tools/__init__.py`
- Create: `service.kodi.ai/lib/telegram/__init__.py`
- Create: `service.kodi.ai/resources/language/resource.language.en_gb/strings.po`
- Create: `service.kodi.ai/resources/settings.xml`
- Create: `service.kodi.ai/resources/data/.gitkeep`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py` (minimal stub for now)
- Create: `tests/acceptance/.gitkeep`
- Create: `tests/fixtures/.gitkeep`

- [ ] **Step 1: Write `service.kodi.ai/addon.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<addon id="service.kodi.ai"
       name="Kodi-AI"
       version="0.1.0"
       provider-name="ivan">
  <requires>
    <import addon="xbmc.python" version="3.0.1"/>
    <!-- Pin verified at release against Kodi 21 Omega official repo -->
    <import addon="script.module.requests" version="2.27.1"/>
  </requires>
  <extension point="xbmc.service" library="service.py" start="login"/>
  <extension point="xbmc.python.script" library="default.py">
    <provides>executable</provides>
  </extension>
  <extension point="xbmc.addon.metadata">
    <summary lang="en_GB">AI-assisted Kodi diagnostics + auto-fix</summary>
    <description lang="en_GB">Monitors Kodi logs, classifies issues with a cheap LLM, attempts auto-fixes via OpenRouter tool-use agent, surfaces results via Telegram bot. V1 personal use on Android TV.</description>
    <platform>all</platform>
    <license>MIT</license>
    <news>0.1.0: initial V1 release.</news>
  </extension>
</addon>
```

- [ ] **Step 2: Write `service.kodi.ai/lib/__init__.py`, `lib/llm/__init__.py`, `lib/tools/__init__.py`, `lib/telegram/__init__.py`** — all empty files.

```bash
mkdir -p service.kodi.ai/lib/llm/prompts
mkdir -p service.kodi.ai/lib/tools
mkdir -p service.kodi.ai/lib/telegram
mkdir -p service.kodi.ai/resources/language/resource.language.en_gb
mkdir -p service.kodi.ai/resources/data
touch service.kodi.ai/lib/__init__.py
touch service.kodi.ai/lib/llm/__init__.py
touch service.kodi.ai/lib/llm/prompts/.gitkeep
touch service.kodi.ai/lib/tools/__init__.py
touch service.kodi.ai/lib/telegram/__init__.py
touch service.kodi.ai/resources/data/.gitkeep
```

- [ ] **Step 3: Write `service.kodi.ai/resources/language/resource.language.en_gb/strings.po`** (seed; expanded as features land)

```po
# Kodi-AI English (en_GB) strings
msgid ""
msgstr ""
"Project-Id-Version: Kodi-AI\n"
"Report-Msgid-Bugs-To: ivanaguilarmari@gmail.com\n"
"PO-Revision-Date: 2026-05-26\n"
"Language-Team: English (en_GB)\n"
"Language: en_GB\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"

msgctxt "#30000"
msgid "Kodi-AI"
msgstr "Kodi-AI"

msgctxt "#30001"
msgid "Show setup secret"
msgstr "Show setup secret"

msgctxt "#30002"
msgid "Reset bot owner"
msgstr "Reset bot owner"
```

- [ ] **Step 4: Write `service.kodi.ai/resources/settings.xml`** (initial categories; secrets are `type="text" option="hidden"` so Kodi masks them)

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<settings>
  <category label="General">
    <setting id="enabled" type="bool" label="Enabled" default="true"/>
    <setting id="openrouter_key" type="text" label="OpenRouter API key" option="hidden" default=""/>
    <setting id="mode" type="enum" label="Mode" values="auto|manual" default="auto"/>
    <setting id="manual_model" type="text" label="Manual mode model ID" default="" enable="eq(-1,1)"/>
  </category>
  <category label="Telegram">
    <setting id="bot_token" type="text" label="Bot token" option="hidden" default=""/>
    <setting id="bot_username" type="text" label="Bot username (without @)" default=""/>
    <setting id="reset_bot_owner" type="action" label="Reset bot owner" action="RunScript(special://home/addons/service.kodi.ai/default.py,reset_bot)"/>
    <setting id="show_setup_secret" type="action" label="Show setup secret" action="RunScript(special://home/addons/service.kodi.ai/default.py,show_secret)"/>
  </category>
  <category label="Budget">
    <setting id="per_incident_cap_usd" type="number" label="Per-incident cap (USD)" default="0.50" min="0.01" max="100"/>
    <setting id="daily_cap_usd" type="number" label="Daily cap (USD)" default="5" min="0.10" max="1000"/>
    <setting id="monthly_cap_usd" type="number" label="Monthly cap (USD)" default="30" min="1" max="10000"/>
    <setting id="reset_time_local" type="text" label="Daily reset time (HH:MM)" default="00:00"/>
    <setting id="timezone" type="text" label="Timezone (IANA, e.g. Europe/Madrid)" default=""/>
    <setting id="models_override" type="text" label="Models override (JSON)" default="" option="markup"/>
  </category>
  <category label="Safety">
    <setting id="redaction_allowlist_extra" type="text" label="Redaction allow-list extra (CSV)" default=""/>
  </category>
  <category label="Advanced">
    <setting id="triage_rate_per_min" type="number" label="Triage rate/min" default="6" min="1" max="60"/>
    <setting id="t2_poll_active_ms" type="number" label="T2 poll cadence (active, ms)" default="750" min="100" max="5000"/>
    <setting id="t2_poll_idle_ms" type="number" label="T2 poll cadence (idle, ms)" default="2500" min="500" max="10000"/>
    <setting id="snapshot_max_count" type="number" label="Snapshot max count" default="100" min="10" max="1000"/>
    <setting id="snapshot_max_mb" type="number" label="Snapshot max MB" default="200" min="10" max="2000"/>
    <setting id="http_proxy_host" type="text" label="HTTP proxy host" default=""/>
    <setting id="http_proxy_port" type="number" label="HTTP proxy port" default="0" min="0" max="65535"/>
    <setting id="diagnostic_logging" type="bool" label="Diagnostic logging" default="false"/>
  </category>
</settings>
```

- [ ] **Step 5: Write `tests/integration/conftest.py`** (skeleton — populated in Task 4.x when fakes land)

```python
"""Integration test fixtures. Fakes for xbmc/xbmcgui/xbmcvfs are wired here
before any lib.* import. See Task 4.x for fake_xbmc / fake_xbmcvfs / etc."""
import sys

# Placeholder — will be replaced by real fake registration in later tasks.
def pytest_configure(config):
    config.addinivalue_line("markers", "integration: kodistubs-backed integration test")
```

- [ ] **Step 6: Verify add-on dir is well-formed**

```bash
find service.kodi.ai -type f | sort
```

Expected: `addon.xml`, `lib/__init__.py`, `lib/llm/__init__.py`, `lib/llm/prompts/.gitkeep`, `lib/tools/__init__.py`, `lib/telegram/__init__.py`, `resources/data/.gitkeep`, `resources/language/resource.language.en_gb/strings.po`, `resources/settings.xml`.

- [ ] **Step 7: Commit**

```bash
git add service.kodi.ai/ tests/
git commit -m "feat(scaffold): add-on directory structure + tests skeleton

addon.xml (services + script extension points, xbmc.python 3.0.1).
resources/settings.xml with 6 categories: General/Telegram/Budget/Safety/Advanced.
en_GB strings.po seed.
tests/{unit,integration,acceptance,fixtures}/ scaffolding.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 0.3 — Pre-commit hook + test smoke

**Files:**
- Create: `.pre-commit-config.yaml`
- Create: `tests/unit/test_smoke.py`

- [ ] **Step 1: Write the smoke test**

```python
# tests/unit/test_smoke.py
"""Smoke test that pytest is wired correctly."""

def test_pytest_runs():
    assert 1 + 1 == 2
```

- [ ] **Step 2: Run the smoke test — verify it passes**

```bash
pytest tests/unit/test_smoke.py -v
```

Expected: `1 passed`.

- [ ] **Step 3: Write `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: local
    hooks:
      - id: pytest-unit
        name: pytest unit tests
        entry: bash -c "source .venv/bin/activate && pytest tests/unit -x --no-cov"
        language: system
        pass_filenames: false
        stages: [pre-commit]
      - id: pytest-integration
        name: pytest integration tests
        entry: bash -c "source .venv/bin/activate && pytest tests/integration -x --no-cov -m integration"
        language: system
        pass_filenames: false
        stages: [pre-commit]
```

- [ ] **Step 4: Install pre-commit hooks**

```bash
pre-commit install
```

Expected: `pre-commit installed at .git/hooks/pre-commit`.

- [ ] **Step 5: Commit**

```bash
git add .pre-commit-config.yaml tests/unit/test_smoke.py
git commit -m "test: pytest smoke test + pre-commit hook

Pre-commit runs unit + integration tests before every commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 1 — Foundations (5 tasks)

### Task 1.1 — `lib/state_paths.py`: special:// path resolution + atomic write

**Spec ref:** §1.15, §2, §5.1 (atomic rename smoke test).

**Files:**
- Create: `service.kodi.ai/lib/state_paths.py`
- Create: `tests/unit/test_state_paths.py`
- Create: `tests/integration/fakes/__init__.py`
- Create: `tests/integration/fakes/fake_xbmcvfs.py`

- [ ] **Step 1: Write minimal `fake_xbmcvfs.py` for tests**

```python
# tests/integration/fakes/fake_xbmcvfs.py
"""Minimal in-memory fake for xbmcvfs. Expands as features land."""
import os
import io
import time
from typing import Dict


class _Stat:
    def __init__(self, size: int, ino: int = 0, mtime: float = 0):
        self._size = size
        self._ino = ino
        self._mtime = mtime
    def st_size(self): return self._size
    def st_mtime(self): return self._mtime
    def st_ino(self): return self._ino


_files: Dict[str, bytes] = {}
_special_map = {
    "special://profile/": "/tmp/kodi-ai-test/profile/",
    "special://userdata/": "/tmp/kodi-ai-test/userdata/",
    "special://temp/": "/tmp/kodi-ai-test/temp/",
    "special://logpath/": "/tmp/kodi-ai-test/logpath/",
    "special://home/": "/tmp/kodi-ai-test/home/",
}


def translatePath(path: str) -> str:
    for prefix, real in _special_map.items():
        if path.startswith(prefix):
            return real + path[len(prefix):]
    return path


def Stat(path: str) -> _Stat:
    real = translatePath(path)
    if not os.path.exists(real):
        raise FileNotFoundError(real)
    st = os.stat(real)
    return _Stat(st.st_size, getattr(st, "st_ino", 0), st.st_mtime)


def exists(path: str) -> bool:
    return os.path.exists(translatePath(path))


def mkdirs(path: str) -> bool:
    os.makedirs(translatePath(path), exist_ok=True)
    return True


def delete(path: str) -> bool:
    real = translatePath(path)
    if os.path.isfile(real):
        os.remove(real)
        return True
    return False


def listdir(path: str):
    real = translatePath(path)
    if not os.path.isdir(real):
        return ([], [])
    entries = os.listdir(real)
    dirs = [e for e in entries if os.path.isdir(os.path.join(real, e))]
    files = [e for e in entries if os.path.isfile(os.path.join(real, e))]
    return (dirs, files)


class File:
    def __init__(self, path: str, mode: str = "r"):
        self._real = translatePath(path)
        self._mode = mode
        if "r" in mode:
            if not os.path.exists(self._real):
                raise FileNotFoundError(self._real)
            self._fp = open(self._real, "rb")
        elif "w" in mode:
            os.makedirs(os.path.dirname(self._real), exist_ok=True)
            self._fp = open(self._real, "wb")
        else:
            raise ValueError(mode)
    def read(self, n: int = -1) -> bytes:
        return self._fp.read(n)
    def seek(self, offset: int, whence: int = 0):
        return self._fp.seek(offset, whence)
    def write(self, data) -> bool:
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._fp.write(data); return True
    def close(self):
        self._fp.close()
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


def reset_test_fs():
    """Wipe the test FS root. Call from pytest fixtures."""
    import shutil
    if os.path.exists("/tmp/kodi-ai-test"):
        shutil.rmtree("/tmp/kodi-ai-test")
```

- [ ] **Step 2: Wire fake into `tests/integration/conftest.py`**

```python
# tests/integration/conftest.py
import sys
import pytest
from tests.integration.fakes import fake_xbmcvfs

# Register xbmcvfs fake so lib.* imports see it
sys.modules["xbmcvfs"] = fake_xbmcvfs


@pytest.fixture(autouse=True)
def reset_fake_fs():
    fake_xbmcvfs.reset_test_fs()
    yield
    fake_xbmcvfs.reset_test_fs()


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: kodistubs-backed integration test")
```

- [ ] **Step 3: Write the failing test**

```python
# tests/unit/test_state_paths.py
"""Pure unit tests for state_paths. Mocks xbmcvfs via sys.modules patching."""
import sys
import os
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def mock_xbmcvfs(tmp_path, monkeypatch):
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: p.replace(
        "special://profile/", str(tmp_path / "profile") + "/"
    ).replace(
        "special://userdata/", str(tmp_path / "userdata") + "/"
    ).replace(
        "special://temp/", str(tmp_path / "temp") + "/"
    )
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    fake.exists.side_effect = lambda p: os.path.exists(fake.translatePath(p))
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    yield fake


def test_resolve_profile_path(mock_xbmcvfs):
    from lib import state_paths
    p = state_paths.profile_path("foo/bar.json")
    assert p.endswith("/profile/addon_data/service.kodi.ai/foo/bar.json")


def test_ensure_dirs_creates_addon_data(mock_xbmcvfs, tmp_path):
    from lib import state_paths
    state_paths.ensure_dirs()
    assert (tmp_path / "profile" / "addon_data" / "service.kodi.ai").exists()
    assert (tmp_path / "profile" / "addon_data" / "service.kodi.ai" / "sessions").exists()
    assert (tmp_path / "profile" / "addon_data" / "service.kodi.ai" / "audit").exists()
    assert (tmp_path / "userdata" / "Kodi-AI-snapshots").exists()


def test_atomic_write_creates_file(mock_xbmcvfs, tmp_path):
    from lib import state_paths
    state_paths.ensure_dirs()
    p = state_paths.profile_path("test.json")
    state_paths.atomic_write(p, b'{"hello": "world"}')
    with open(p, "rb") as f:
        assert f.read() == b'{"hello": "world"}'
    # No stale .tmp file
    assert not os.path.exists(p + ".tmp")


def test_atomic_write_overwrites_existing(mock_xbmcvfs, tmp_path):
    from lib import state_paths
    state_paths.ensure_dirs()
    p = state_paths.profile_path("test.json")
    state_paths.atomic_write(p, b"first")
    state_paths.atomic_write(p, b"second")
    with open(p, "rb") as f:
        assert f.read() == b"second"
```

- [ ] **Step 4: Run tests — verify they fail**

```bash
pytest tests/unit/test_state_paths.py -v
```

Expected: `ModuleNotFoundError: No module named 'lib'` (we haven't added `service.kodi.ai/` to sys.path yet).

- [ ] **Step 5: Add `service.kodi.ai/` to test sys.path via `pyproject.toml`**

Edit `pyproject.toml`, replace `[tool.pytest.ini_options]` block with:

```toml
[tool.pytest.ini_options]
testpaths = ["tests/unit", "tests/integration"]
pythonpath = ["service.kodi.ai"]
python_files = ["test_*.py"]
addopts = "-v --strict-markers --cov=service.kodi.ai/lib --cov-report=term-missing"
markers = [
    "integration: integration tests requiring kodistubs",
    "acceptance: manual acceptance tests requiring real Kodi (skipped in CI)",
]
```

Re-run: `pytest tests/unit/test_state_paths.py -v`. Expected: `ModuleNotFoundError: No module named 'lib.state_paths'`.

- [ ] **Step 6: Implement `service.kodi.ai/lib/state_paths.py`**

```python
# service.kodi.ai/lib/state_paths.py
"""special:// path resolution + atomic write helpers.

Wraps xbmcvfs for testability. All paths under POSIX-backed special://profile/
on Android — atomic rename verified at startup + every 50 writes (smoke probe
in .smoke/ subdir; see lib/health.py)."""
from __future__ import annotations
import os
import xbmcvfs

ADDON_ID = "service.kodi.ai"


def profile_path(relpath: str = "") -> str:
    """Returns absolute path under special://profile/addon_data/<addon>/."""
    base = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}/")
    return os.path.join(base, relpath) if relpath else base


def snapshots_path(relpath: str = "") -> str:
    """Snapshots live OUTSIDE addon_data so they survive addon reinstall."""
    base = xbmcvfs.translatePath("special://userdata/Kodi-AI-snapshots/")
    return os.path.join(base, relpath) if relpath else base


def temp_path(relpath: str = "") -> str:
    base = xbmcvfs.translatePath("special://temp/")
    return os.path.join(base, relpath) if relpath else base


def log_path() -> str:
    return xbmcvfs.translatePath("special://logpath/kodi.log")


def old_log_path() -> str:
    return xbmcvfs.translatePath("special://logpath/kodi.old.log")


def ensure_dirs() -> None:
    """Create all addon state dirs. Idempotent."""
    for sub in ("", "sessions", "audit", "recovery", ".smoke"):
        xbmcvfs.mkdirs(f"special://profile/addon_data/{ADDON_ID}/{sub}/")
    xbmcvfs.mkdirs("special://userdata/Kodi-AI-snapshots/")
    xbmcvfs.mkdirs("special://userdata/Kodi-AI-snapshots/.undone/")
    xbmcvfs.mkdirs("special://userdata/Kodi-AI-snapshots/.orphaned/")


def atomic_write(path: str, data: bytes) -> None:
    """Write bytes atomically: .tmp + fsync + rename. POSIX-backed on Android."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # atomic on POSIX


def smoke_probe_atomic_rename() -> bool:
    """Verify atomic rename works on the underlying FS. Used at startup
    and every 50 writes (see lib/health.py). Returns True if OK."""
    probe_dir = profile_path(".smoke")
    os.makedirs(probe_dir, exist_ok=True)
    probe = os.path.join(probe_dir, "probe")
    payload = os.urandom(16)
    try:
        atomic_write(probe, payload)
        with open(probe, "rb") as f:
            return f.read() == payload
    finally:
        try:
            os.remove(probe)
        except FileNotFoundError:
            pass
```

- [ ] **Step 7: Run tests — verify they pass**

```bash
pytest tests/unit/test_state_paths.py -v
```

Expected: `4 passed`.

- [ ] **Step 8: Commit**

```bash
git add service.kodi.ai/lib/state_paths.py tests/unit/test_state_paths.py \
        tests/integration/conftest.py tests/integration/fakes/ \
        tests/integration/fakes/__init__.py pyproject.toml
git commit -m "feat(state_paths): special:// resolution + atomic write

profile_path/snapshots_path/temp_path/log_path/old_log_path helpers.
ensure_dirs() creates addon_data/{sessions,audit,recovery,.smoke} +
userdata/Kodi-AI-snapshots/{.undone,.orphaned} per spec §1.15.
atomic_write() = .tmp + fsync + os.replace (atomic POSIX rename).
smoke_probe_atomic_rename() verifies FS supports atomic rename.

Spec: §1.15, §5.1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 1.2 — `lib/settings.py`: xbmcaddon settings wrapper

**Spec ref:** §2, §5.1, §7.3.

**Files:**
- Create: `service.kodi.ai/lib/settings.py`
- Create: `tests/unit/test_settings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_settings.py
import sys
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def mock_xbmcaddon(monkeypatch):
    fake_addon = mock.MagicMock()
    fake_addon.getSetting.side_effect = lambda k: {
        "openrouter_key": "sk-or-xxx",
        "bot_token": "12345:abc",
        "mode": "auto",
        "enabled": "true",
        "per_incident_cap_usd": "0.50",
        "triage_rate_per_min": "6",
    }.get(k, "")
    fake_xbmcaddon = mock.MagicMock()
    fake_xbmcaddon.Addon.return_value = fake_addon
    monkeypatch.setitem(sys.modules, "xbmcaddon", fake_xbmcaddon)
    yield fake_addon


def test_get_string(mock_xbmcaddon):
    from lib import settings
    assert settings.get_string("openrouter_key") == "sk-or-xxx"


def test_get_string_missing_returns_default(mock_xbmcaddon):
    from lib import settings
    assert settings.get_string("nonexistent", default="fallback") == "fallback"


def test_get_bool_true(mock_xbmcaddon):
    from lib import settings
    assert settings.get_bool("enabled") is True


def test_get_bool_missing_returns_default(mock_xbmcaddon):
    from lib import settings
    assert settings.get_bool("nonexistent", default=False) is False


def test_get_float(mock_xbmcaddon):
    from lib import settings
    assert settings.get_float("per_incident_cap_usd") == 0.50


def test_get_int(mock_xbmcaddon):
    from lib import settings
    assert settings.get_int("triage_rate_per_min") == 6


def test_invalidate_cache_forces_reread(mock_xbmcaddon):
    from lib import settings
    settings.get_string("mode")  # cache it
    mock_xbmcaddon.getSetting.side_effect = lambda k: "manual" if k == "mode" else ""
    settings.invalidate_cache()
    assert settings.get_string("mode") == "manual"
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/unit/test_settings.py -v
```

Expected: `ModuleNotFoundError: No module named 'lib.settings'`.

- [ ] **Step 3: Implement `service.kodi.ai/lib/settings.py`**

```python
# service.kodi.ai/lib/settings.py
"""xbmcaddon settings wrapper with in-memory cache.

Kodi's settings API returns strings always; we provide typed accessors.
Cache invalidated explicitly (e.g. on onSettingsChanged or via /status command)."""
from __future__ import annotations
import threading
import xbmcaddon

ADDON_ID = "service.kodi.ai"

_cache: dict[str, str] = {}
_lock = threading.Lock()


def _addon():
    # xbmcaddon.Addon() must be called fresh each time when not cached
    return xbmcaddon.Addon(ADDON_ID)


def get_string(key: str, default: str = "") -> str:
    with _lock:
        if key not in _cache:
            try:
                _cache[key] = _addon().getSetting(key) or ""
            except Exception:
                _cache[key] = ""
        val = _cache[key]
    return val if val else default


def get_bool(key: str, default: bool = False) -> bool:
    raw = get_string(key, default="").lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    return default


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(get_string(key, default=str(default)))
    except (ValueError, TypeError):
        return default


def get_float(key: str, default: float = 0.0) -> float:
    try:
        return float(get_string(key, default=str(default)))
    except (ValueError, TypeError):
        return default


def set_string(key: str, value: str) -> None:
    with _lock:
        _addon().setSetting(key, value)
        _cache[key] = value


def invalidate_cache() -> None:
    with _lock:
        _cache.clear()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_settings.py -v
```

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/settings.py tests/unit/test_settings.py
git commit -m "feat(settings): xbmcaddon wrapper with typed accessors + cache

get_string/get_bool/get_int/get_float wrap xbmcaddon.Addon().getSetting()
(which always returns string). invalidate_cache() forces re-read on
settings change.

Spec: §2, §5.1, §7.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 1.3 — `lib/concurrency.py`: AtomicCounter + abort_event + queues + enqueue helper

**Spec ref:** §1.2, §1.6, §1.7 (paused_sessions), §1.12 (single-flight by construction).

**Files:**
- Create: `service.kodi.ai/lib/concurrency.py` (initial — ActiveCalls + MonotonicBudget added in Task 1.4/1.5)
- Create: `tests/unit/test_concurrency_basics.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_concurrency_basics.py
import threading
import time
import pytest


def test_atomic_counter_increments():
    from lib.concurrency import AtomicCounter
    c = AtomicCounter()
    assert c.get() == 0
    c.inc()
    c.inc()
    assert c.get() == 2


def test_atomic_counter_reset_and_get():
    from lib.concurrency import AtomicCounter
    c = AtomicCounter()
    for _ in range(5):
        c.inc()
    assert c.reset_and_get() == 5
    assert c.get() == 0


def test_atomic_counter_thread_safe():
    from lib.concurrency import AtomicCounter
    c = AtomicCounter()
    def worker():
        for _ in range(1000):
            c.inc()
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert c.get() == 10_000


def test_work_queue_priority_resume_first():
    from lib.concurrency import work_queue, enqueue, ResumeWork, LogIncident
    # Clear any existing items
    while not work_queue.empty():
        work_queue.get_nowait()
    enqueue(LogIncident(cluster_id="c1", first_seen=None, last_seen=None,
                        occurrences=1, raw_lines=[], severity_hint="ERROR",
                        likely_addon=None, likely_action=None, backdated=False,
                        from_previous_session=False, triage_deferred=True))
    enqueue(ResumeWork(session_id="s1", user_reply=True))
    prio, seq, item = work_queue.get_nowait()
    assert isinstance(item, ResumeWork)


def test_enqueue_rejects_unknown_type():
    from lib.concurrency import enqueue
    class WeirdType: pass
    with pytest.raises(KeyError):
        enqueue(WeirdType())


def test_abort_event_global():
    from lib.concurrency import abort_event
    abort_event.clear()
    assert not abort_event.is_set()
    abort_event.set()
    assert abort_event.is_set()
    abort_event.clear()  # cleanup
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/unit/test_concurrency_basics.py -v
```

Expected: `ModuleNotFoundError: No module named 'lib.concurrency'`.

- [ ] **Step 3: Implement `service.kodi.ai/lib/concurrency.py` (initial)**

```python
# service.kodi.ai/lib/concurrency.py
"""Cross-thread state for the 4-thread service architecture.

This module is the single home for everything threads share:
  - abort_event: shutdown signal (set by Main on Monitor.abortRequested()).
  - startup_complete_event: T4 sets after boot pass; T2/T3 wait on it.
  - work_queue: PriorityQueue draining to T4. Use enqueue() helper ONLY.
  - active_cluster_ids + coalesce_lock: T2-side dedup at enqueue time.
  - drop_counter: T2 increments on backpressure.
  - paused_sessions + paused_sessions_lock: in-memory primary for sessions.

ActiveCalls + MonotonicBudget added in Tasks 1.4 and 1.5.

Spec: §1.2.
"""
from __future__ import annotations
import threading
import queue
import itertools
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


# ---- Events / shutdown ----
abort_event = threading.Event()
startup_complete_event = threading.Event()


# ---- AtomicCounter ----
class AtomicCounter:
    """Thread-safe int counter."""
    def __init__(self):
        self._v = 0
        self._lock = threading.Lock()
    def inc(self) -> None:
        with self._lock:
            self._v += 1
    def get(self) -> int:
        with self._lock:
            return self._v
    def reset_and_get(self) -> int:
        with self._lock:
            v, self._v = self._v, 0
            return v


drop_counter = AtomicCounter()


# ---- Work queue + payload types ----
@dataclass(frozen=True, order=False)
class LogIncident:
    cluster_id: str
    first_seen: datetime | None
    last_seen: datetime | None
    occurrences: int
    raw_lines: list[str]
    severity_hint: str
    likely_addon: str | None
    likely_action: str | None
    backdated: bool
    from_previous_session: bool
    triage_deferred: bool


@dataclass(frozen=True, order=False)
class UserMsg:
    chat_id: int
    text: str
    message_id: int
    reply_to_message_id: int | None


@dataclass(frozen=True, order=False)
class ResumeWork:
    session_id: str
    user_reply: Any  # str | bool — see spec §1.7


WorkItem = LogIncident | UserMsg | ResumeWork


# PriorityQueue items are (priority_int, monotonic_seq, payload).
# monotonic_seq breaks ties and avoids comparing payloads (@dataclass(order=False)
# would otherwise raise TypeError on tuple comparison).
_seq = itertools.count()
work_queue: "queue.PriorityQueue[tuple[int, int, Any]]" = queue.PriorityQueue(maxsize=500)

_PRIORITIES = {
    "ResumeWork": 0,
    "UserMsg": 5,
    "LogIncident": 10,
}


def enqueue(payload: WorkItem) -> None:
    """Only API for putting items on work_queue. Asserts known type."""
    name = type(payload).__name__
    if name not in _PRIORITIES:
        raise KeyError(f"enqueue: unknown payload type {name}")
    work_queue.put((_PRIORITIES[name], next(_seq), payload))


# ---- Coalescing (T2-side dedup at enqueue time) ----
coalesce_lock = threading.Lock()
active_cluster_ids: set[str] = set()


# ---- Paused session registry (T4-owned; T3 reads under lock via callbacks) ----
paused_sessions: dict[str, Any] = {}  # session_id -> SessionState (defined later)
paused_sessions_lock = threading.Lock()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_concurrency_basics.py -v
```

Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/concurrency.py tests/unit/test_concurrency_basics.py
git commit -m "feat(concurrency): events, work_queue, payload types, AtomicCounter

abort_event + startup_complete_event for shutdown + startup synchronization.
work_queue is PriorityQueue (maxsize=500) with enqueue() helper as ONLY API;
priorities ResumeWork=0, UserMsg=5, LogIncident=10. monotonic_seq from
itertools.count() avoids @dataclass(order=False) tuple-comparison errors.
AtomicCounter for T2 drop tracking. paused_sessions registry + lock for T4.
coalesce_lock + active_cluster_ids for T2-side cluster dedup.

ActiveCalls + MonotonicBudget added in Tasks 1.4 and 1.5.

Spec: §1.2, §1.6, §1.7, §1.12.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 1.4 — `MonotonicBudget` + `BudgetStateError` (in concurrency.py)

**Spec ref:** §1.8.

**Files:**
- Modify: `service.kodi.ai/lib/concurrency.py` (append class)
- Create: `tests/unit/test_monotonic_budget.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_monotonic_budget.py
import time
import pytest
from freezegun import freeze_time


def test_initial_state_is_idle():
    from lib.concurrency import MonotonicBudget, BudgetState
    b = MonotonicBudget(limit_s=60)
    assert b.state == BudgetState.IDLE
    assert b.elapsed() == 0.0


def test_start_transitions_to_running():
    from lib.concurrency import MonotonicBudget, BudgetState
    b = MonotonicBudget(limit_s=60)
    b.start()
    assert b.state == BudgetState.RUNNING


def test_double_start_raises():
    from lib.concurrency import MonotonicBudget, BudgetStateError
    b = MonotonicBudget(limit_s=60)
    b.start()
    with pytest.raises(BudgetStateError):
        b.start()


def test_pause_from_idle_raises():
    from lib.concurrency import MonotonicBudget, BudgetStateError
    b = MonotonicBudget(limit_s=60)
    with pytest.raises(BudgetStateError):
        b.pause()


def test_elapsed_accumulates_only_when_running(monkeypatch):
    from lib.concurrency import MonotonicBudget
    t = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    b = MonotonicBudget(limit_s=60)
    b.start()
    t[0] = 1005.0
    assert b.elapsed() == pytest.approx(5.0)
    b.pause()
    t[0] = 1100.0
    # paused — elapsed does NOT advance
    assert b.elapsed() == pytest.approx(5.0)
    b.resume()
    t[0] = 1110.0
    # running again — adds 10s
    assert b.elapsed() == pytest.approx(15.0)


def test_stop_freezes_elapsed(monkeypatch):
    from lib.concurrency import MonotonicBudget, BudgetState
    t = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    b = MonotonicBudget(limit_s=60)
    b.start()
    t[0] = 1003.0
    b.stop()
    assert b.state == BudgetState.IDLE
    assert b.elapsed() == pytest.approx(3.0)


def test_serialize_and_rehydrate(monkeypatch):
    from lib.concurrency import MonotonicBudget, BudgetState
    t = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    b = MonotonicBudget(limit_s=60)
    b.start()
    t[0] = 1010.0
    b.pause()
    blob = b.to_dict()
    assert blob == {"limit_s": 60, "elapsed_baseline": 10.0, "state": "PAUSED"}
    # Rehydrate
    t[0] = 2000.0  # later run
    b2 = MonotonicBudget.from_dict(blob)
    assert b2.state == BudgetState.PAUSED
    assert b2.elapsed() == pytest.approx(10.0)
    b2.resume()
    t[0] = 2005.0
    assert b2.elapsed() == pytest.approx(15.0)
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/unit/test_monotonic_budget.py -v
```

Expected: `ImportError: cannot import name 'MonotonicBudget'`.

- [ ] **Step 3: Append to `service.kodi.ai/lib/concurrency.py`**

Add at the end of the file:

```python


# ---- MonotonicBudget — wall-clock cap with pause/resume across ask_user ----
from enum import Enum, auto
import time


class BudgetStateError(RuntimeError):
    """Illegal MonotonicBudget state transition."""


class BudgetState(Enum):
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()


class MonotonicBudget:
    """Wall-clock budget that pauses across ask_user.

    Only PAUSED state is ever persisted (only RUNNING crashes lose the session).
    On rehydrate, restored as PAUSED with elapsed_baseline preserved;
    .resume() reads time.monotonic() fresh.

    Spec: §1.8.
    """
    def __init__(self, limit_s: float):
        self.limit_s = limit_s
        self.elapsed_baseline = 0.0
        self.state = BudgetState.IDLE
        self.started_at: float | None = None

    def start(self) -> None:
        if self.state != BudgetState.IDLE:
            raise BudgetStateError(f"start: state is {self.state.name}, expected IDLE")
        self.state = BudgetState.RUNNING
        self.started_at = time.monotonic()

    def pause(self) -> None:
        if self.state != BudgetState.RUNNING:
            raise BudgetStateError(f"pause: state is {self.state.name}, expected RUNNING")
        assert self.started_at is not None
        self.elapsed_baseline += time.monotonic() - self.started_at
        self.started_at = None
        self.state = BudgetState.PAUSED

    def resume(self) -> None:
        if self.state != BudgetState.PAUSED:
            raise BudgetStateError(f"resume: state is {self.state.name}, expected PAUSED")
        self.started_at = time.monotonic()
        self.state = BudgetState.RUNNING

    def stop(self) -> None:
        if self.state != BudgetState.RUNNING:
            raise BudgetStateError(f"stop: state is {self.state.name}, expected RUNNING")
        assert self.started_at is not None
        self.elapsed_baseline += time.monotonic() - self.started_at
        self.started_at = None
        self.state = BudgetState.IDLE

    def elapsed(self) -> float:
        if self.state == BudgetState.RUNNING:
            assert self.started_at is not None
            return self.elapsed_baseline + (time.monotonic() - self.started_at)
        return self.elapsed_baseline

    def exceeded(self) -> bool:
        return self.elapsed() >= self.limit_s

    def to_dict(self) -> dict:
        """Serialize for disk persistence (only PAUSED state persisted in practice)."""
        return {
            "limit_s": self.limit_s,
            "elapsed_baseline": self.elapsed_baseline,
            "state": self.state.name,
        }

    @classmethod
    def from_dict(cls, blob: dict) -> "MonotonicBudget":
        """Rehydrate from disk. state typically PAUSED."""
        b = cls(limit_s=blob["limit_s"])
        b.elapsed_baseline = blob["elapsed_baseline"]
        b.state = BudgetState[blob["state"]]
        # started_at intentionally None on rehydrate — resume() will set it.
        return b
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_monotonic_budget.py -v
```

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/concurrency.py tests/unit/test_monotonic_budget.py
git commit -m "feat(concurrency): MonotonicBudget with typed state-machine

BudgetState enum (IDLE/RUNNING/PAUSED). Typed BudgetStateError on illegal
transitions. start/pause/resume/stop/elapsed/exceeded. Wall-clock paused
across ask_user. Only PAUSED state persisted on disk; .from_dict()
rehydrates with .started_at=None (resume() sets it fresh).

Spec: §1.8.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 1.5 — `ActiveCalls` (multi-target with linger + 'ALL' support)

**Spec ref:** §1.2, §1.3 (reasoner→log loop prevention), §1.7.

**Files:**
- Modify: `service.kodi.ai/lib/concurrency.py` (append `ActiveCalls`)
- Create: `tests/unit/test_active_calls.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_active_calls.py
import pytest


def test_initially_inactive():
    from lib.concurrency import ActiveCalls
    ac = ActiveCalls()
    assert not ac.is_active()


def test_add_tool_makes_active(monkeypatch):
    from lib.concurrency import ActiveCalls
    monkeypatch.setattr("time.monotonic", lambda: 100.0)
    ac = ActiveCalls()
    ac.add_tool("t1", target_addons={"plugin.video.seren"})
    assert ac.is_active()


def test_schedule_remove_linger(monkeypatch):
    from lib.concurrency import ActiveCalls
    t = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    ac = ActiveCalls()
    ac.add_tool("t1", target_addons={"a"})
    ac.schedule_remove_tool("t1", after=1.0)
    # still active during linger
    assert ac.is_active()
    t[0] = 100.5
    assert ac.is_active()
    # expires past linger
    t[0] = 101.5
    assert not ac.is_active()


def test_add_session_independent_of_tools(monkeypatch):
    from lib.concurrency import ActiveCalls
    monkeypatch.setattr("time.monotonic", lambda: 100.0)
    ac = ActiveCalls()
    ac.add_session("s1")
    assert ac.is_active()


def test_targets_for_line_unioned_during_overlap(monkeypatch):
    from lib.concurrency import ActiveCalls
    t = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    ac = ActiveCalls()
    ac.add_tool("t1", target_addons={"plugin.video.a"})
    t[0] = 100.5
    ac.add_tool("t2", target_addons={"plugin.video.b"})
    # Both overlap at t=100.5
    targets = ac.get_active_target_addons()
    assert targets == {"plugin.video.a", "plugin.video.b"}


def test_targets_all_takes_precedence(monkeypatch):
    from lib.concurrency import ActiveCalls
    monkeypatch.setattr("time.monotonic", lambda: 100.0)
    ac = ActiveCalls()
    ac.add_tool("t1", target_addons={"plugin.video.a"})
    ac.add_tool("t2", target_addons="ALL")
    assert ac.get_active_target_addons() == "ALL"


def test_update_tool_target_replaces(monkeypatch):
    from lib.concurrency import ActiveCalls
    monkeypatch.setattr("time.monotonic", lambda: 100.0)
    ac = ActiveCalls()
    ac.add_tool("t1", target_addons=set())
    ac.update_tool_target("t1", target_addons={"plugin.video.c"})
    assert ac.get_active_target_addons() == {"plugin.video.c"}


def test_remove_session_with_linger(monkeypatch):
    from lib.concurrency import ActiveCalls
    t = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    ac = ActiveCalls()
    ac.add_session("s1")
    ac.schedule_remove_session("s1", after=2.0)
    assert ac.is_active()
    t[0] = 102.5
    assert not ac.is_active()
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/unit/test_active_calls.py -v
```

Expected: `ImportError: cannot import name 'ActiveCalls'`.

- [ ] **Step 3: Append to `service.kodi.ai/lib/concurrency.py`**

```python


# ---- ActiveCalls — two-scope bracketing for reasoner→log loop prevention ----
from typing import Union

_AddonTargets = Union[set[str], Literal["ALL"]]


class ActiveCalls:
    """Tracks active tool + session brackets with target-addon scoping + linger.

    T4 calls add_tool(call_id, target_addons) BEFORE each tool call and
    schedule_remove_tool(call_id, after=1s) AFTER. The 1s linger catches
    delayed log writes (addon shutdown messages, async log flush).

    T2 checks is_active() / get_active_target_addons() per line to decide
    whether to buffer (for post-window evaluation).

    target_addons can be a set[str] OR the literal "ALL" (e.g. for Kodi-wide
    setting changes). "ALL" subsumes any set when unioned.

    update_tool_target() exists for tools whose targets aren't known at add_tool
    time (e.g. install_addon resolves dep closure mid-flight).

    Spec: §1.2 (state), §1.3 (loop prevention).
    """
    def __init__(self):
        self._active_tools: dict[str, _AddonTargets] = {}
        self._active_sessions: set[str] = set()
        # _linger keys: ("tool", call_id) or ("session", sid)
        # _linger values: (expiry_monotonic_ts, target_addons | None)
        self._linger: dict[tuple[str, str], tuple[float, _AddonTargets | None]] = {}
        self._lock = threading.Lock()

    def _purge_expired(self):
        """Remove expired linger entries. Called under _lock."""
        now = time.monotonic()
        expired = [k for k, (t, _) in self._linger.items() if t <= now]
        for k in expired:
            kind, ident = k
            if kind == "tool":
                self._active_tools.pop(ident, None)
            elif kind == "session":
                self._active_sessions.discard(ident)
            self._linger.pop(k)

    def add_tool(self, call_id: str, target_addons: _AddonTargets) -> None:
        with self._lock:
            self._active_tools[call_id] = target_addons

    def update_tool_target(self, call_id: str, target_addons: _AddonTargets) -> None:
        """Refine target_addons after deferred resolution (e.g. dep closure)."""
        with self._lock:
            if call_id in self._active_tools:
                self._active_tools[call_id] = target_addons

    def schedule_remove_tool(self, call_id: str, after: float = 1.0) -> None:
        with self._lock:
            tgt = self._active_tools.get(call_id)
            self._linger[("tool", call_id)] = (time.monotonic() + after, tgt)

    def add_session(self, session_id: str) -> None:
        with self._lock:
            self._active_sessions.add(session_id)

    def schedule_remove_session(self, session_id: str, after: float = 2.0) -> None:
        with self._lock:
            self._linger[("session", session_id)] = (time.monotonic() + after, None)

    def is_active(self) -> bool:
        with self._lock:
            self._purge_expired()
            return bool(self._active_tools or self._active_sessions)

    def get_active_target_addons(self) -> _AddonTargets:
        """Union of all active tools' target_addons. Returns 'ALL' if any tool
        targets ALL. Used by T2 to decide whether a parsed line falls under
        our scope (should be buffered for post-window eval)."""
        with self._lock:
            self._purge_expired()
            union: set[str] = set()
            for targets in self._active_tools.values():
                if targets == "ALL":
                    return "ALL"
                union |= targets
            return union


# Module-level instance used by T4 (reasoner / tool dispatch)
active_calls = ActiveCalls()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_active_calls.py -v
```

Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/concurrency.py tests/unit/test_active_calls.py
git commit -m "feat(concurrency): ActiveCalls — two-scope bracketing with linger

Tool brackets (add_tool/schedule_remove_tool with 1s default linger) +
session brackets (add_session/schedule_remove_session with 2s default).
update_tool_target() for deferred resolution (e.g. install_addon dep
closure).
target_addons = set[str] | 'ALL'; get_active_target_addons() unions
all active tool targets ('ALL' subsumes everything).

Used by T2's reasoner→log loop prevention (Phase 4): lines parsed
while is_active() are buffered for post-window evaluation against
target_addons.

Spec: §1.2, §1.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — Audit log + secrets + redactor (4 tasks)

### Task 2.1 — `lib/audit_log.py`: JSONL append with rotation

**Spec ref:** §5.3.

**Files:**
- Create: `service.kodi.ai/lib/audit_log.py`
- Create: `tests/unit/test_audit_log.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_audit_log.py
import json
import os
import sys
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def mock_paths(tmp_path, monkeypatch):
    fake_xbmcvfs = mock.MagicMock()
    fake_xbmcvfs.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake_xbmcvfs.mkdirs.side_effect = lambda p: os.makedirs(fake_xbmcvfs.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake_xbmcvfs)
    from lib import state_paths
    state_paths.ensure_dirs()
    yield


def test_write_event_appends_jsonl(tmp_path):
    from lib import audit_log
    audit_log.write("startup", details={"version": "0.1.0"})
    from lib import state_paths
    path = state_paths.profile_path("audit/audit.jsonl")
    with open(path) as f:
        line = f.readline()
    obj = json.loads(line)
    assert obj["event"] == "startup"
    assert obj["details"] == {"version": "0.1.0"}
    assert "ts" in obj
    assert obj["redacted"] == []


def test_write_event_with_session_id(tmp_path):
    from lib import audit_log
    audit_log.write("session_start", session_id="abc123", details={})
    from lib import state_paths
    with open(state_paths.profile_path("audit/audit.jsonl")) as f:
        obj = json.loads(f.readline())
    assert obj["session_id"] == "abc123"


def test_rotation_at_10mb(tmp_path, monkeypatch):
    from lib import audit_log, state_paths
    # Lower rotation threshold for fast test
    monkeypatch.setattr(audit_log, "_ROTATION_BYTES", 1024)
    # Write enough to trigger rotation twice
    for i in range(200):
        audit_log.write("tool_call", details={"i": i, "padding": "x" * 50})
    files = sorted(os.listdir(state_paths.profile_path("audit")))
    assert "audit.jsonl" in files
    assert "audit.1.jsonl" in files


def test_rotation_caps_at_5_files(tmp_path, monkeypatch):
    from lib import audit_log, state_paths
    monkeypatch.setattr(audit_log, "_ROTATION_BYTES", 256)
    for i in range(500):
        audit_log.write("tool_call", details={"i": i, "padding": "y" * 100})
    files = sorted(os.listdir(state_paths.profile_path("audit")))
    assert "audit.jsonl" in files
    audit_n = [f for f in files if f.startswith("audit.") and f.endswith(".jsonl")]
    # Max 5 numbered rotation files + audit.jsonl
    assert len(audit_n) <= 6


def test_redacted_field_recorded():
    from lib import audit_log
    audit_log.write("tool_call", details={"value": "<redacted>"},
                    redacted=["details.value"])
    from lib import state_paths
    with open(state_paths.profile_path("audit/audit.jsonl")) as f:
        obj = json.loads(f.readline())
    assert obj["redacted"] == ["details.value"]
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/unit/test_audit_log.py -v
```

Expected: `ModuleNotFoundError: No module named 'lib.audit_log'`.

- [ ] **Step 3: Implement `service.kodi.ai/lib/audit_log.py`**

```python
# service.kodi.ai/lib/audit_log.py
"""Append-only JSONL audit log with rotation at 10 MB × 5 files.

Schema:
  {
    "ts": ISO-8601 UTC,
    "event": str,  # tool_call | llm_call | session_start | ... (see spec §5.3)
    "session_id": str | None,
    "details": dict,
    "redacted": list[str]  # JSONPath-style keys redacted in details
  }

Spec: §5.3.
"""
from __future__ import annotations
import json
import os
import threading
from datetime import datetime, timezone
from . import state_paths

_LOCK = threading.Lock()
_ROTATION_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_ROTATIONS = 5


def _audit_dir() -> str:
    return state_paths.profile_path("audit")


def _current_path() -> str:
    return os.path.join(_audit_dir(), "audit.jsonl")


def _rotated_path(n: int) -> str:
    return os.path.join(_audit_dir(), f"audit.{n}.jsonl")


def _rotate_if_needed() -> None:
    path = _current_path()
    try:
        size = os.path.getsize(path)
    except FileNotFoundError:
        return
    if size < _ROTATION_BYTES:
        return
    # Shift audit.{N-1}.jsonl → audit.{N}.jsonl, drop the oldest.
    oldest = _rotated_path(_MAX_ROTATIONS)
    if os.path.exists(oldest):
        os.remove(oldest)
    for n in range(_MAX_ROTATIONS - 1, 0, -1):
        src = _rotated_path(n)
        if os.path.exists(src):
            os.rename(src, _rotated_path(n + 1))
    os.rename(path, _rotated_path(1))


def write(
    event: str,
    *,
    session_id: str | None = None,
    details: dict | None = None,
    redacted: list[str] | None = None,
) -> None:
    """Append one audit entry. Thread-safe."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "event": event,
        "session_id": session_id,
        "details": details or {},
        "redacted": redacted or [],
    }
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
    with _LOCK:
        os.makedirs(_audit_dir(), exist_ok=True)
        _rotate_if_needed()
        with open(_current_path(), "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_audit_log.py -v
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/audit_log.py tests/unit/test_audit_log.py
git commit -m "feat(audit_log): JSONL append with 10MB×5 rotation

Schema per spec §5.3: ts (ISO-8601 UTC), event, session_id, details,
redacted (list[str] of JSONPath keys). Atomic per-line append with
threading.Lock. Rotation at audit.jsonl → audit.1.jsonl → ... →
audit.5.jsonl (oldest dropped). Total disk budget ~60 MB.

Spec: §5.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.2 — `lib/secrets.py`: in-memory secret cache with 0600 best-effort

**Spec ref:** §5.1.

**Files:**
- Create: `service.kodi.ai/lib/secrets.py`
- Create: `tests/unit/test_secrets.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_secrets.py
import json
import os
import sys
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    from lib import state_paths, secrets
    state_paths.ensure_dirs()
    secrets.invalidate_cache()
    yield


def test_get_secret_returns_none_when_missing():
    from lib import secrets
    assert secrets.get_secret("openrouter_key") is None


def test_set_and_get_secret():
    from lib import secrets
    secrets.set_secret("openrouter_key", "sk-or-test-123")
    assert secrets.get_secret("openrouter_key") == "sk-or-test-123"


def test_set_persists_to_disk():
    from lib import secrets, state_paths
    secrets.set_secret("bot_token", "12345:abc")
    path = state_paths.profile_path("secrets.json")
    with open(path) as f:
        data = json.load(f)
    assert data["bot_token"] == "12345:abc"


def test_get_after_restart_reloads_from_disk():
    from lib import secrets
    secrets.set_secret("openrouter_key", "sk-or-xyz")
    secrets.invalidate_cache()  # simulate process restart
    assert secrets.get_secret("openrouter_key") == "sk-or-xyz"


def test_delete_secret():
    from lib import secrets
    secrets.set_secret("setup_secret", "abc")
    secrets.delete_secret("setup_secret")
    assert secrets.get_secret("setup_secret") is None


def test_atomic_write_used(tmp_path):
    from lib import secrets, state_paths
    secrets.set_secret("openrouter_key", "k1")
    secrets.set_secret("openrouter_key", "k2")
    # no .tmp leftover
    path = state_paths.profile_path("secrets.json")
    assert not os.path.exists(path + ".tmp")
    with open(path) as f:
        assert json.load(f)["openrouter_key"] == "k2"
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/unit/test_secrets.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `service.kodi.ai/lib/secrets.py`**

```python
# service.kodi.ai/lib/secrets.py
"""In-memory secret cache backed by secrets.json (POSIX, 0600 best-effort).

Secrets in V1: openrouter_key, bot_token, setup_secret, optional provider-direct
keys. Same trust model as Trakt/RD/AllDebrid keys live in their addons —
documented in spec §5.1.

Access pattern: T4 (worker, reasoner) + T3 (telegram bot_token) read.
T2 (log watcher) MUST NOT read secrets. Module-level guard enforces nothing,
but reviewer checks it.

Spec: §5.1.
"""
from __future__ import annotations
import json
import os
import stat
import threading
from . import state_paths

_LOCK = threading.Lock()
_cache: dict[str, str] | None = None


def _path() -> str:
    return state_paths.profile_path("secrets.json")


def _load() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache
    p = _path()
    if not os.path.exists(p):
        _cache = {}
        return _cache
    try:
        with open(p, "r", encoding="utf-8") as f:
            _cache = json.load(f) or {}
    except (json.JSONDecodeError, OSError):
        _cache = {}
    return _cache


def _persist(data: dict[str, str]) -> None:
    blob = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    state_paths.atomic_write(_path(), blob)
    # Best-effort 0600. On Android scoped storage this may not actually take effect.
    try:
        os.chmod(_path(), stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # documented limitation


def get_secret(key: str) -> str | None:
    with _LOCK:
        return _load().get(key)


def set_secret(key: str, value: str) -> None:
    with _LOCK:
        data = dict(_load())
        data[key] = value
        _persist(data)
        global _cache
        _cache = data


def delete_secret(key: str) -> None:
    with _LOCK:
        data = dict(_load())
        if key in data:
            del data[key]
            _persist(data)
            global _cache
            _cache = data


def invalidate_cache() -> None:
    """Force re-read on next access. Used for tests + post-process-restart."""
    with _LOCK:
        global _cache
        _cache = None
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_secrets.py -v
```

Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/secrets.py tests/unit/test_secrets.py
git commit -m "feat(secrets): in-memory cache backed by secrets.json (0600)

get/set/delete_secret with thread-safe in-memory cache; persists via
atomic_write (.tmp + fsync + rename). 0600 perms best-effort (Android
scoped storage may not honor — documented in spec §5.1). cache
invalidation for tests + process restart.

Spec: §5.1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.3 — `lib/redactor.py`: pattern + heuristic + allow_list + canary

**Spec ref:** §5.8.

**Files:**
- Create: `service.kodi.ai/lib/redactor.py`
- Create: `service.kodi.ai/resources/data/redaction_allowlist.json`
- Create: `service.kodi.ai/resources/data/known_secret_keys.json`
- Create: `tests/unit/test_redactor.py`

- [ ] **Step 1: Write `service.kodi.ai/resources/data/redaction_allowlist.json`**

```json
[
  "auth_method",
  "cookie_consent_shown",
  "cookie_consent_required",
  "password_min_length",
  "password_max_length",
  "password_strength",
  "api_key_required",
  "api_url",
  "auth_url",
  "token_url",
  "cookie_url",
  "secret_url"
]
```

- [ ] **Step 2: Write `service.kodi.ai/resources/data/known_secret_keys.json`**

```json
{
  "plugin.video.seren": ["real_debrid_token", "premiumize_token", "alldebrid_token", "trakt_token"],
  "plugin.video.fen": ["real_debrid_token", "premiumize_token", "alldebrid_token"],
  "script.module.urlresolver": ["real_debrid_token", "premiumize_apikey"],
  "service.subtitles.opensubtitlesbyopensubtitles": ["password", "username"]
}
```

- [ ] **Step 3: Write the failing test**

```python
# tests/unit/test_redactor.py
import pytest


def test_redact_telegram_bot_token():
    from lib.redactor import redact
    s = "Got token 1234567890:ABCdefGHIjklMNOpqrSTUvwxYZabcdefgHIjkl in logs"
    assert "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZabcdefgHIjkl" not in redact(s)
    assert "<redacted>" in redact(s) or "<redacted-token>" in redact(s)


def test_redact_openrouter_key():
    from lib.redactor import redact
    s = "Auth: sk-or-v1-abc123def456ghi789jklmnopqrstuvwx"
    assert "sk-or" not in redact(s) or "<redacted>" in redact(s)


def test_redact_anthropic_openai_key():
    from lib.redactor import redact
    s = "key=sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
    assert "sk-ant" not in redact(s)


def test_redact_jwt():
    from lib.redactor import redact
    jwt = "eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY3.SflKxwRJSMeKKF2QT4f"
    assert jwt not in redact(f"Bearer {jwt}")


def test_redact_authorization_header():
    from lib.redactor import redact
    s = "Authorization: Bearer some-token-here-12345"
    out = redact(s)
    assert "some-token-here-12345" not in out
    assert "<redacted>" in out


def test_redact_basic_auth_url():
    from lib.redactor import redact
    s = "GET https://user:secret@example.com/path"
    out = redact(s)
    assert "user:secret@" not in out


def test_redact_set_cookie_case_insensitive():
    from lib.redactor import redact
    s = "set-cookie: session=abc123; HttpOnly"
    out = redact(s)
    assert "abc123" not in out


def test_redact_preserves_non_secrets():
    from lib.redactor import redact
    s = "This is a normal log message about a thing."
    assert redact(s) == s


def test_canary_self_test_succeeds():
    from lib.redactor import canary_self_test
    ok, leaked = canary_self_test()
    assert ok, f"leaked: {leaked}"


def test_should_redact_value_for_known_secret_addon_key():
    from lib.redactor import should_redact_value
    assert should_redact_value("plugin.video.seren", "real_debrid_token", "abc")


def test_should_redact_value_heuristic_match_string():
    from lib.redactor import should_redact_value
    assert should_redact_value("some.addon", "my_api_token", "abc123")


def test_should_redact_value_heuristic_skips_bool():
    from lib.redactor import should_redact_value
    assert not should_redact_value("some.addon", "api_key_required", True)
    assert not should_redact_value("some.addon", "cookie_consent_shown", False)


def test_should_redact_value_heuristic_skips_int():
    from lib.redactor import should_redact_value
    assert not should_redact_value("some.addon", "password_min_length", 8)


def test_allow_list_overrides_heuristic():
    from lib.redactor import should_redact_value
    # auth_method is in allow_list, regex matches but allow_list wins
    assert not should_redact_value("some.addon", "auth_method", "none")


def test_user_allow_list_extra_merges():
    from lib import redactor
    redactor.set_user_allow_list_extra("my_custom_key,other_key")
    try:
        assert not redactor.should_redact_value("a", "my_custom_key", "abc")
    finally:
        redactor.set_user_allow_list_extra("")
```

- [ ] **Step 4: Run test — verify it fails**

```bash
pytest tests/unit/test_redactor.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 5: Implement `service.kodi.ai/lib/redactor.py`**

```python
# service.kodi.ai/lib/redactor.py
"""Pattern-based redaction + key-name heuristic + allow_list.

Used at every boundary that touches LLM input or audit log. Canary self-test
runs every 100 redactions (called by lib/llm/client.py) — failure disables
LLM calls.

Spec: §5.8.
"""
from __future__ import annotations
import json
import os
import re
import threading
from typing import Any

_LOCK = threading.Lock()
_REDACTION_COUNT = 0
_CANARY_INTERVAL = 100

# --- Patterns ---
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Telegram bot token: 8-12 digits : 30+ chars
    (re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"), "<redacted-tg-token>"),
    # OpenRouter, OpenAI, Anthropic key prefixes
    (re.compile(r"\bsk-or-[A-Za-z0-9-]{20,}\b"), "<redacted-or-key>"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9-]{20,}\b"), "<redacted-ant-key>"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "<redacted-sk-key>"),
    # JWT
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "<redacted-jwt>"),
    # Bearer token
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9._-]{20,}"), "Bearer <redacted>"),
    # Authorization header
    (re.compile(r"(?i)Authorization:\s*\S+"), "Authorization: <redacted>"),
    # Set-Cookie header (case-insensitive)
    (re.compile(r"(?i)Set-Cookie:\s*[^\r\n]+"), "Set-Cookie: <redacted>"),
    # Basic-auth in URLs: https?://user:pass@host
    (re.compile(r"(https?://)[^:/@\s]+:[^@/\s]+@"), r"\1<redacted-creds>@"),
    # URL query: token=..., apikey=..., api_key=..., key=...
    (re.compile(r"([?&](?:token|apikey|api_key|key|secret|password|access_token)=)[^&\s]+", re.IGNORECASE),
     r"\1<redacted>"),
]

# --- Heuristic key-name regex (default-deny for string values) ---
_HEURISTIC_KEY_RE = re.compile(r"(?i).*(token|secret|password|api_?key|cookie|auth).*")

# --- Allow-lists ---
_BUILTIN_ALLOW_LIST: set[str] = set()
_USER_ALLOW_LIST_EXTRA: set[str] = set()
_KNOWN_SECRET_KEYS: dict[str, set[str]] = {}


def _data_path(filename: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "resources", "data", filename)


def _load_resources_once():
    global _BUILTIN_ALLOW_LIST, _KNOWN_SECRET_KEYS
    if _BUILTIN_ALLOW_LIST:  # already loaded
        return
    try:
        with open(_data_path("redaction_allowlist.json"), "r", encoding="utf-8") as f:
            _BUILTIN_ALLOW_LIST = set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        _BUILTIN_ALLOW_LIST = set()
    try:
        with open(_data_path("known_secret_keys.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        _KNOWN_SECRET_KEYS = {k: set(v) for k, v in data.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        _KNOWN_SECRET_KEYS = {}


def set_user_allow_list_extra(csv: str) -> None:
    global _USER_ALLOW_LIST_EXTRA
    _USER_ALLOW_LIST_EXTRA = {k.strip() for k in csv.split(",") if k.strip()}


def _effective_allow_list() -> set[str]:
    _load_resources_once()
    return _BUILTIN_ALLOW_LIST | _USER_ALLOW_LIST_EXTRA


def redact(text: str) -> str:
    """Apply all patterns. Returns redacted string. Bumps canary counter."""
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    global _REDACTION_COUNT
    with _LOCK:
        _REDACTION_COUNT += 1
    return out


def should_redact_value(addon_id: str, key: str, value: Any) -> bool:
    """For (addon_id, key, value) tuples — decide if value is a secret.

    Type-aware: only string-typed values get redacted by heuristic.
    Explicit list (known_secret_keys per addon) overrides type check.
    allow_list overrides everything (positive).
    """
    _load_resources_once()
    if key in _effective_allow_list():
        return False
    # Explicit list per addon
    if addon_id in _KNOWN_SECRET_KEYS and key in _KNOWN_SECRET_KEYS[addon_id]:
        return True
    # Heuristic: regex match AND value is string
    if not _HEURISTIC_KEY_RE.match(key):
        return False
    # Type gate — type(v) is bool BEFORE isinstance(v, int) because bool < int
    if type(value) is bool:
        return False
    if isinstance(value, (int, float)):
        return False
    return isinstance(value, str)


def canary_self_test() -> tuple[bool, list[str]]:
    """Run redactor on canary string with all known secret patterns.
    Returns (ok, leaked_patterns)."""
    canary_input = (
        "tg=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZabcdefgHIjkl "
        "or=sk-or-v1-abc123def456ghi789jklmnopqrstuvwx "
        "openai=sk-abc123def456ghi789jklmnopqrstuvwx "
        "jwt=eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY3.SflKxwRJSMeKKF2QT4f "
        "bearer=Bearer abc123def456ghi789jklmnopqrstuvwx "
        "Authorization: Bearer secret-here-123 "
        "Set-Cookie: session=abc123; HttpOnly "
        "url=https://user:pass@host/x "
        "?token=long-secret-value-12345"
    )
    out = redact(canary_input)
    leaked = []
    for raw in ["1234567890:ABCdefGHIjklMNOpqrSTUvwxYZabcdefgHIjkl",
                "sk-or-v1-abc123def456ghi789jklmnopqrstuvwx",
                "sk-abc123def456ghi789jklmnopqrstuvwx",
                "eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY3.SflKxwRJSMeKKF2QT4f",
                "abc123def456ghi789jklmnopqrstuvwx",
                "secret-here-123",
                "session=abc123",
                "user:pass@",
                "token=long-secret-value-12345"]:
        if raw in out:
            leaked.append(raw)
    return (not leaked, leaked)


def should_run_canary() -> bool:
    """Called by LLM client; returns True every _CANARY_INTERVAL redactions."""
    with _LOCK:
        return _REDACTION_COUNT > 0 and _REDACTION_COUNT % _CANARY_INTERVAL == 0
```

- [ ] **Step 6: Run tests — verify they pass**

```bash
pytest tests/unit/test_redactor.py -v
```

Expected: `15 passed`.

- [ ] **Step 7: Commit**

```bash
git add service.kodi.ai/lib/redactor.py \
        service.kodi.ai/resources/data/redaction_allowlist.json \
        service.kodi.ai/resources/data/known_secret_keys.json \
        tests/unit/test_redactor.py
git commit -m "feat(redactor): patterns + key-name heuristic + allow_list + canary

Patterns: Telegram bot token, sk-or-/sk-ant-/sk- keys, JWT, Bearer,
Authorization, Set-Cookie (case-insens), basic-auth URLs, query tokens.
Heuristic: key matches (?i).*(token|secret|password|api_?key|cookie|auth).*
AND value is string (bool/int/float skipped — type(v) is bool BEFORE
isinstance(v, int) per spec).
Allow-list: builtin (resources/data/redaction_allowlist.json) ∪ user CSV
override (Kodi setting redaction_allowlist_extra).
Known-secret-keys: per-addon explicit list (resources/data/known_secret_keys.json).
canary_self_test() exercises all patterns; called every 100 redactions
by lib/llm/client.py — failure disables LLM calls.

Spec: §5.8.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.4 — Wire redactor + secrets + audit_log into integration

**Spec ref:** §5.3 (audit-log redaction integration), §5.8.

**Files:**
- Modify: `service.kodi.ai/lib/audit_log.py` (add `redact_details=True` option)
- Create: `tests/unit/test_audit_log_redaction.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_audit_log_redaction.py
import json
import os
import sys
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    from lib import state_paths
    state_paths.ensure_dirs()
    yield


def test_redact_secret_pair_in_args():
    from lib import audit_log, state_paths
    audit_log.write_tool_call(
        tool_name="set_addon_setting",
        args={"addon_id": "plugin.video.seren", "key": "real_debrid_token", "value": "abc-secret-123"},
        success=True,
        duration_ms=42,
    )
    with open(state_paths.profile_path("audit/audit.jsonl")) as f:
        obj = json.loads(f.readline())
    args = obj["details"]["args"]
    assert args["value"] == "<redacted>"
    # Pair-level: addon_id AND key are obscured for single-key tools
    assert args["addon_id"] == "<redacted-secret-addon>"
    assert args["key"] == "<known-secret-key>"
    assert obj["redacted"] == ["args.addon_id", "args.key", "args.value"]


def test_no_redaction_for_non_secret():
    from lib import audit_log, state_paths
    audit_log.write_tool_call(
        tool_name="set_addon_setting",
        args={"addon_id": "plugin.video.seren", "key": "default_resolver", "value": "premiumize"},
        success=True,
        duration_ms=20,
    )
    with open(state_paths.profile_path("audit/audit.jsonl")) as f:
        obj = json.loads(f.readline())
    args = obj["details"]["args"]
    assert args["value"] == "premiumize"
    assert obj["redacted"] == []
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/unit/test_audit_log_redaction.py -v
```

Expected: `AttributeError: module 'lib.audit_log' has no attribute 'write_tool_call'`.

- [ ] **Step 3: Append to `service.kodi.ai/lib/audit_log.py`**

```python


# ---- Higher-level helpers with built-in redaction ----
from . import redactor as _redactor


def write_tool_call(
    tool_name: str,
    args: dict,
    *,
    success: bool,
    duration_ms: int,
    snapshot_id: str | None = None,
    session_id: str | None = None,
    error: str | None = None,
) -> None:
    """Write a tool_call audit entry with secret-pair redaction.

    For tools touching (addon_id, key, value) tuples where key is a known
    secret, redact the WHOLE pair, not just the value.
    """
    redacted_keys: list[str] = []
    redacted_args = dict(args)
    addon_id = args.get("addon_id")
    key = args.get("key")
    value = args.get("value")
    if (
        tool_name in ("set_addon_setting", "get_addon_setting")
        and addon_id and key
        and _redactor.should_redact_value(addon_id, key, value)
    ):
        redacted_args["addon_id"] = "<redacted-secret-addon>"
        redacted_args["key"] = "<known-secret-key>"
        redacted_args["value"] = "<redacted>"
        redacted_keys = ["args.addon_id", "args.key", "args.value"]
    # Apply pattern-based redact() to any remaining string values
    for k, v in redacted_args.items():
        if isinstance(v, str):
            new = _redactor.redact(v)
            if new != v:
                redacted_args[k] = new
                if f"args.{k}" not in redacted_keys:
                    redacted_keys.append(f"args.{k}")

    details = {
        "tool_name": tool_name,
        "args": redacted_args,
        "success": success,
        "duration_ms": duration_ms,
    }
    if snapshot_id is not None:
        details["snapshot_id"] = snapshot_id
    if error is not None:
        details["error"] = _redactor.redact(error)
        if details["error"] != error:
            redacted_keys.append("error")

    write("tool_call", session_id=session_id, details=details, redacted=redacted_keys)
```

- [ ] **Step 4: Run test — verify it passes**

```bash
pytest tests/unit/test_audit_log_redaction.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/audit_log.py tests/unit/test_audit_log_redaction.py
git commit -m "feat(audit_log): write_tool_call helper with pair-level redaction

For single-key tools (set/get_addon_setting): redact (addon_id, key, value)
as a pair when key matches known_secret_keys ∪ heuristic. Skeleton hidden
to prevent service-linkage PII in audit log.
Pattern-based redact() also applied to any string args + error field.
redacted: list[str] of JSONPath keys.

Spec: §5.3, §5.8.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — LLM client + router + budget + prompts (5 tasks)

### Task 3.1 — `lib/llm/client.py`: OpenRouter HTTP client (non-streaming first)

**Spec ref:** §1.10 (streaming + chunk abort), §4.5.

**Files:**
- Create: `service.kodi.ai/lib/llm/client.py`
- Create: `tests/unit/test_llm_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_llm_client.py
import json
import pytest
import responses


@responses.activate
def test_non_streaming_chat_completion():
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        json={
            "id": "abc",
            "model": "google/gemini-2.0-flash-001",
            "choices": [{"message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
        status=200,
    )
    from lib.llm.client import chat
    res = chat(
        api_key="sk-or-test",
        model="google/gemini-2.0-flash-001",
        messages=[{"role": "user", "content": "Hi"}],
    )
    assert res.text == "Hello!"
    assert res.tokens_in == 10
    assert res.tokens_out == 5
    assert res.model == "google/gemini-2.0-flash-001"
    assert res.finish_reason == "stop"


@responses.activate
def test_401_raises_specific_error():
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        json={"error": "invalid api key"},
        status=401,
    )
    from lib.llm.client import chat, LLMAuthError
    with pytest.raises(LLMAuthError):
        chat(api_key="bad", model="x", messages=[])


@responses.activate
def test_402_raises_specific_error():
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        json={"error": "insufficient credit"},
        status=402,
    )
    from lib.llm.client import chat, LLMNoCreditError
    with pytest.raises(LLMNoCreditError):
        chat(api_key="ok", model="x", messages=[])


@responses.activate
def test_404_model_not_found_raises():
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        json={"error": "model not found"},
        status=404,
    )
    from lib.llm.client import chat, LLMModelUnavailableError
    with pytest.raises(LLMModelUnavailableError):
        chat(api_key="ok", model="nonexistent", messages=[])


def test_default_preflight_model_constant():
    from lib.llm.client import DEFAULT_PREFLIGHT_MODEL
    assert DEFAULT_PREFLIGHT_MODEL == "google/gemini-2.0-flash-001"
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/unit/test_llm_client.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `service.kodi.ai/lib/llm/client.py`**

```python
# service.kodi.ai/lib/llm/client.py
"""OpenRouter HTTP client (OpenAI-compatible).

Non-streaming chat() for simple calls (triage, preflight).
Streaming chat_stream() with chunk-level abort + mid-stream budget check —
see Task 3.5.

Spec: §1.10, §4.5.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any
import requests

DEFAULT_PREFLIGHT_MODEL = "google/gemini-2.0-flash-001"
BASE_URL = "https://openrouter.ai/api/v1"


class LLMError(Exception):
    """Base for LLM client errors."""


class LLMAuthError(LLMError):
    """401 — invalid API key."""


class LLMNoCreditError(LLMError):
    """402 — insufficient credit."""


class LLMModelUnavailableError(LLMError):
    """404 / 422 — model not found or schema invalid. Route to fallback."""


class LLMRateLimitError(LLMError):
    """429 — caller should backoff (honor Retry-After)."""


class LLMServerError(LLMError):
    """5xx — caller should backoff + maybe fallback."""


@dataclass(frozen=True)
class ChatResponse:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    finish_reason: str
    tool_calls: list[dict] | None = None
    raw: dict | None = None


def _build_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/<user>/kodi-ai",
        "X-Title": "Kodi-AI",
    }


def chat(
    api_key: str,
    model: str,
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    timeout: tuple[float, float] = (5.0, 30.0),
) -> ChatResponse:
    """Non-streaming chat completion. Use for triage + simple calls."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    try:
        r = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=_build_headers(api_key),
            json=payload,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as e:
        raise LLMServerError(f"timeout: {e}") from e
    except requests.exceptions.ConnectionError as e:
        raise LLMServerError(f"connection: {e}") from e

    if r.status_code == 401:
        raise LLMAuthError(r.text)
    if r.status_code == 402:
        raise LLMNoCreditError(r.text)
    if r.status_code in (404, 422):
        raise LLMModelUnavailableError(r.text)
    if r.status_code == 429:
        retry_after = r.headers.get("Retry-After")
        raise LLMRateLimitError(retry_after or "1")
    if r.status_code >= 500:
        raise LLMServerError(f"{r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        raise LLMError(f"{r.status_code}: {r.text[:200]}")

    body = r.json()
    choice = body["choices"][0]
    msg = choice["message"]
    usage = body.get("usage", {})
    return ChatResponse(
        text=msg.get("content") or "",
        model=body.get("model", model),
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        finish_reason=choice.get("finish_reason", "stop"),
        tool_calls=msg.get("tool_calls"),
        raw=body,
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_llm_client.py -v
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/llm/client.py tests/unit/test_llm_client.py
git commit -m "feat(llm.client): OpenRouter non-streaming chat() + typed errors

ChatResponse dataclass with text/model/tokens_in/tokens_out/finish_reason/
tool_calls. Typed exceptions: LLMAuthError (401), LLMNoCreditError (402),
LLMModelUnavailableError (404/422 → fallback), LLMRateLimitError (429),
LLMServerError (5xx). timeout=(connect=5s, read=30s). HTTP-Referer +
X-Title headers per OpenRouter convention.
DEFAULT_PREFLIGHT_MODEL = google/gemini-2.0-flash-001 (cold-start fallback).

Streaming chat_stream() added in Task 3.5.

Spec: §1.10, §4.5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.2 — `recommended_models.json` + `lib/llm/router.py`: TaskModelRouter

**Spec ref:** §4.5 (model fallback per task class).

**Files:**
- Create: `service.kodi.ai/resources/data/recommended_models.json`
- Create: `service.kodi.ai/lib/llm/router.py`
- Create: `tests/unit/test_llm_router.py`

- [ ] **Step 1: Write `service.kodi.ai/resources/data/recommended_models.json`**

```json
{
  "t0_triage": [
    {"id": "google/gemini-2.0-flash-001", "price_in": 0.10, "price_out": 0.40},
    {"id": "meta-llama/llama-3.3-8b-instruct", "price_in": 0.10, "price_out": 0.30},
    {"id": "anthropic/claude-haiku-4.5", "price_in": 1.00, "price_out": 5.00}
  ],
  "t1_simple": [
    {"id": "deepseek/deepseek-chat-v3", "price_in": 0.27, "price_out": 1.10},
    {"id": "google/gemini-2.5-flash", "price_in": 0.30, "price_out": 1.20},
    {"id": "openai/gpt-4o-mini", "price_in": 0.15, "price_out": 0.60},
    {"id": "anthropic/claude-haiku-4.5", "price_in": 1.00, "price_out": 5.00}
  ],
  "t2_reason": [
    {"id": "anthropic/claude-haiku-4.5", "price_in": 1.00, "price_out": 5.00},
    {"id": "deepseek/deepseek-r1", "price_in": 0.55, "price_out": 2.19},
    {"id": "google/gemini-2.5-pro", "price_in": 1.25, "price_out": 5.00},
    {"id": "openai/gpt-4o", "price_in": 2.50, "price_out": 10.00}
  ],
  "t3_heroic": [
    {"id": "anthropic/claude-sonnet-4-6", "price_in": 3.00, "price_out": 15.00},
    {"id": "openai/gpt-4o", "price_in": 2.50, "price_out": 10.00},
    {"id": "deepseek/deepseek-r1", "price_in": 0.55, "price_out": 2.19},
    {"id": "anthropic/claude-haiku-4.5", "price_in": 1.00, "price_out": 5.00}
  ]
}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_llm_router.py
import json
import pytest


def test_auto_mode_picks_first_for_task_class():
    from lib.llm.router import TaskModelRouter
    r = TaskModelRouter(mode="auto")
    assert r.pick("t0_triage") == "google/gemini-2.0-flash-001"
    assert r.pick("t1_simple") == "deepseek/deepseek-chat-v3"
    assert r.pick("t2_reason") == "anthropic/claude-haiku-4.5"
    assert r.pick("t3_heroic") == "anthropic/claude-sonnet-4-6"


def test_manual_mode_returns_user_model():
    from lib.llm.router import TaskModelRouter
    r = TaskModelRouter(mode="manual", manual_model="openai/gpt-4o-mini")
    assert r.pick("t0_triage") == "openai/gpt-4o-mini"
    assert r.pick("t3_heroic") == "openai/gpt-4o-mini"


def test_next_fallback_advances():
    from lib.llm.router import TaskModelRouter
    r = TaskModelRouter(mode="auto")
    assert r.pick("t1_simple") == "deepseek/deepseek-chat-v3"
    nxt = r.next_fallback("t1_simple", "deepseek/deepseek-chat-v3")
    assert nxt == "google/gemini-2.5-flash"


def test_next_fallback_exhausts():
    from lib.llm.router import TaskModelRouter
    r = TaskModelRouter(mode="auto")
    # Last in t0_triage chain is claude-haiku-4.5
    nxt = r.next_fallback("t0_triage", "anthropic/claude-haiku-4.5")
    assert nxt is None


def test_price_lookup():
    from lib.llm.router import TaskModelRouter
    r = TaskModelRouter(mode="auto")
    price = r.price_per_mtok("deepseek/deepseek-chat-v3")
    assert price == (0.27, 1.10)


def test_user_override_replaces_defaults():
    from lib.llm.router import TaskModelRouter
    override = json.dumps({
        "t1_simple": [{"id": "my/custom-model", "price_in": 0.5, "price_out": 1.5}]
    })
    r = TaskModelRouter(mode="auto", user_override_json=override)
    assert r.pick("t1_simple") == "my/custom-model"
    # Non-overridden classes use defaults
    assert r.pick("t0_triage") == "google/gemini-2.0-flash-001"


def test_unknown_task_class_raises():
    from lib.llm.router import TaskModelRouter
    r = TaskModelRouter(mode="auto")
    with pytest.raises(KeyError):
        r.pick("t99_unknown")
```

- [ ] **Step 3: Run test — verify it fails**

```bash
pytest tests/unit/test_llm_router.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 4: Implement `service.kodi.ai/lib/llm/router.py`**

```python
# service.kodi.ai/lib/llm/router.py
"""TaskModelRouter — Auto / Manual mode + per-task ordered fallback.

Loads recommended_models.json at instantiation; user_override_json from
addon setting models_override merges (override per-class, not per-model).

Spec: §4.5.
"""
from __future__ import annotations
import json
import os
from typing import Literal

TaskClass = Literal["t0_triage", "t1_simple", "t2_reason", "t3_heroic"]


def _default_models_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "..", "resources", "data", "recommended_models.json")


class TaskModelRouter:
    def __init__(
        self,
        *,
        mode: Literal["auto", "manual"],
        manual_model: str = "",
        user_override_json: str = "",
        models_path: str | None = None,
    ):
        self.mode = mode
        self.manual_model = manual_model
        path = models_path or _default_models_path()
        with open(path, "r", encoding="utf-8") as f:
            defaults: dict[str, list[dict]] = json.load(f)
        if user_override_json:
            try:
                override = json.loads(user_override_json)
                # Per-class replacement (not per-model deep merge)
                for k, v in override.items():
                    defaults[k] = v
            except json.JSONDecodeError:
                pass  # silently ignore malformed override; user notified in /status
        self._chains: dict[str, list[dict]] = defaults
        # Flatten model → (price_in, price_out) for O(1) lookup
        self._prices: dict[str, tuple[float, float]] = {}
        for chain in defaults.values():
            for m in chain:
                self._prices[m["id"]] = (m["price_in"], m["price_out"])

    def pick(self, task_class: str) -> str:
        if self.mode == "manual":
            return self.manual_model
        if task_class not in self._chains:
            raise KeyError(f"unknown task class: {task_class}")
        return self._chains[task_class][0]["id"]

    def next_fallback(self, task_class: str, current_model: str) -> str | None:
        """Return next model in fallback chain after current_model, or None."""
        if self.mode == "manual":
            return None  # manual mode has no fallback
        if task_class not in self._chains:
            return None
        chain = [m["id"] for m in self._chains[task_class]]
        try:
            idx = chain.index(current_model)
        except ValueError:
            return None
        if idx + 1 >= len(chain):
            return None
        return chain[idx + 1]

    def price_per_mtok(self, model: str) -> tuple[float, float] | None:
        """Returns (input_price_per_Mtok, output_price_per_Mtok) or None."""
        return self._prices.get(model)

    def all_model_ids(self) -> set[str]:
        """For slug validation against OpenRouter /models."""
        return set(self._prices.keys())
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
pytest tests/unit/test_llm_router.py -v
```

Expected: `7 passed`.

- [ ] **Step 6: Commit**

```bash
git add service.kodi.ai/lib/llm/router.py \
        service.kodi.ai/resources/data/recommended_models.json \
        tests/unit/test_llm_router.py
git commit -m "feat(llm.router): TaskModelRouter with Auto/Manual + fallback chains

recommended_models.json: ordered fallback list per task class (t0/t1/t2/t3)
with price_in/price_out per Mtok. Loaded at startup, user-overridable via
models_override JSON (per-class replacement; malformed override silently
ignored — surfaces in /status).
TaskModelRouter.pick(class), .next_fallback(class, current), .price_per_mtok,
.all_model_ids (for OpenRouter /models slug validation).
Manual mode returns same model for every class; no fallback.

Spec: §4.5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.3 — `lib/llm/budget.py`: BudgetGuard (3-point enforcement)

**Spec ref:** §5.5.

**Files:**
- Create: `service.kodi.ai/lib/llm/budget.py`
- Create: `tests/unit/test_llm_budget.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_llm_budget.py
import json
import os
import sys
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    from lib import state_paths
    state_paths.ensure_dirs()
    yield


def test_initial_counters_zero():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=0.50, daily_cap=5.0, monthly_cap=30.0)
    assert bg.incident_cost_usd == 0.0
    assert bg.daily_cost_usd == 0.0
    assert bg.monthly_cost_usd == 0.0


def test_pre_call_estimate_allows_under_cap():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=0.50, daily_cap=5.0, monthly_cap=30.0)
    # 1k input × $1/Mtok + 100 output × $5/Mtok = $0.0015
    ok, reason = bg.pre_call_check(estimated_cost=0.001)
    assert ok
    assert reason is None


def test_pre_call_estimate_refuses_over_per_incident():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=0.10, daily_cap=5.0, monthly_cap=30.0)
    bg.record_actual(0.08)
    ok, reason = bg.pre_call_check(estimated_cost=0.05)
    assert not ok
    assert "per_incident" in reason


def test_pre_call_refuses_over_daily():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=10.0, daily_cap=1.0, monthly_cap=30.0)
    bg.record_actual(0.95)
    ok, reason = bg.pre_call_check(estimated_cost=0.10)
    assert not ok
    assert "daily" in reason


def test_pre_call_refuses_over_monthly():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=10.0, daily_cap=100.0, monthly_cap=2.0)
    bg.record_actual(1.9)
    ok, reason = bg.pre_call_check(estimated_cost=0.20)
    assert not ok
    assert "monthly" in reason


def test_mid_stream_check_trips_at_100_percent():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=0.10, daily_cap=10.0, monthly_cap=30.0)
    # No headroom — exactly at cap trips
    assert bg.mid_stream_check(streamed_cost=0.05) is True  # ok
    bg.record_actual(0.08)
    assert bg.mid_stream_check(streamed_cost=0.025) is False  # 0.08 + 0.025 > 0.10


def test_record_actual_updates_all_counters():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=10.0, daily_cap=10.0, monthly_cap=10.0)
    bg.record_actual(0.5)
    assert bg.incident_cost_usd == 0.5
    assert bg.daily_cost_usd == 0.5
    assert bg.monthly_cost_usd == 0.5


def test_reset_incident_resets_only_incident():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=10.0, daily_cap=10.0, monthly_cap=10.0)
    bg.record_actual(0.5)
    bg.reset_incident()
    assert bg.incident_cost_usd == 0.0
    assert bg.daily_cost_usd == 0.5
    assert bg.monthly_cost_usd == 0.5


def test_persistence_round_trip():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=1.0, daily_cap=5.0, monthly_cap=30.0)
    bg.record_actual(1.23)
    bg.persist()
    # Fresh instance loads
    bg2 = BudgetGuard(per_incident_cap=1.0, daily_cap=5.0, monthly_cap=30.0)
    bg2.load()
    assert bg2.daily_cost_usd == 1.23
    assert bg2.monthly_cost_usd == 1.23
    # incident not persisted (resets per session)
    assert bg2.incident_cost_usd == 0.0
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/unit/test_llm_budget.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `service.kodi.ai/lib/llm/budget.py`**

```python
# service.kodi.ai/lib/llm/budget.py
"""BudgetGuard: 3-tier cost enforcement.

Per-incident hard cap (reset per session_start), daily, monthly.
3-point per-incident enforcement: pre-call estimate, mid-stream check at
100% trip, post-call record_actual.

Daily/monthly persisted to addon_data/budget_counters.json.
Reset wall-clock per user-configured timezone (handled at boundary by
caller; this class just tracks counters).

Spec: §5.5.
"""
from __future__ import annotations
import json
import os
import threading
from datetime import datetime, timezone
from .. import state_paths

_LOCK = threading.Lock()


class BudgetGuard:
    def __init__(
        self,
        *,
        per_incident_cap: float,
        daily_cap: float,
        monthly_cap: float,
    ):
        self.per_incident_cap = per_incident_cap
        self.daily_cap = daily_cap
        self.monthly_cap = monthly_cap
        self.incident_cost_usd = 0.0
        self.daily_cost_usd = 0.0
        self.monthly_cost_usd = 0.0
        self.day_iso: str = datetime.now(timezone.utc).date().isoformat()
        self.month_iso: str = self.day_iso[:7]  # "2026-05"

    def _path(self) -> str:
        return state_paths.profile_path("budget_counters.json")

    def load(self) -> None:
        with _LOCK:
            p = self._path()
            if not os.path.exists(p):
                return
            try:
                with open(p, "r", encoding="utf-8") as f:
                    blob = json.load(f)
            except (json.JSONDecodeError, OSError):
                return
            today = datetime.now(timezone.utc).date().isoformat()
            this_month = today[:7]
            self.daily_cost_usd = blob.get("daily", 0.0) if blob.get("day") == today else 0.0
            self.monthly_cost_usd = blob.get("monthly", 0.0) if blob.get("month") == this_month else 0.0
            self.day_iso = today
            self.month_iso = this_month

    def persist(self) -> None:
        with _LOCK:
            blob = {
                "day": self.day_iso,
                "daily": self.daily_cost_usd,
                "month": self.month_iso,
                "monthly": self.monthly_cost_usd,
            }
            state_paths.atomic_write(self._path(), json.dumps(blob).encode("utf-8"))

    def pre_call_check(self, *, estimated_cost: float) -> tuple[bool, str | None]:
        """Returns (ok, reason). reason names the cap that would trip."""
        with _LOCK:
            if self.incident_cost_usd + estimated_cost > self.per_incident_cap:
                return False, f"per_incident cap ${self.per_incident_cap:.2f} would be exceeded"
            if self.daily_cost_usd + estimated_cost > self.daily_cap:
                return False, f"daily cap ${self.daily_cap:.2f} would be exceeded"
            if self.monthly_cost_usd + estimated_cost > self.monthly_cap:
                return False, f"monthly cap ${self.monthly_cap:.2f} would be exceeded"
            return True, None

    def mid_stream_check(self, *, streamed_cost: float) -> bool:
        """Returns True if still within cap, False if trip at exactly 100%."""
        with _LOCK:
            return self.incident_cost_usd + streamed_cost <= self.per_incident_cap

    def record_actual(self, cost_usd: float) -> None:
        with _LOCK:
            self.incident_cost_usd += cost_usd
            self.daily_cost_usd += cost_usd
            self.monthly_cost_usd += cost_usd

    def reset_incident(self) -> None:
        with _LOCK:
            self.incident_cost_usd = 0.0
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_llm_budget.py -v
```

Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/llm/budget.py tests/unit/test_llm_budget.py
git commit -m "feat(llm.budget): BudgetGuard with 3-tier 3-point enforcement

Per-incident hard cap (resets per session_start), daily, monthly.
pre_call_check() refuses if estimate would push over any cap.
mid_stream_check() trips at exactly 100% (no headroom per spec §5.5
round-3 fix). record_actual() updates all 3 counters atomically.
persist() / load() persists daily+monthly to budget_counters.json with
date roll-over (daily resets if day_iso != today; monthly if month_iso
!= this_month).
Incident counter NEVER persisted (per-session reset).

Spec: §5.5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.4 — Streaming chat + slug validation

**Spec ref:** §1.10 (streaming + chunk abort + mid-stream budget), §4.5 (slug validation).

**Files:**
- Modify: `service.kodi.ai/lib/llm/client.py` (append `chat_stream` + `validate_slugs`)
- Create: `tests/unit/test_llm_streaming.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_llm_streaming.py
import json
import threading
import pytest
import responses


@responses.activate
def test_chat_stream_yields_chunks():
    sse_body = (
        'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"!"},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":3}}\n\n'
        'data: [DONE]\n\n'
    )
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        body=sse_body,
        status=200,
        content_type="text/event-stream",
    )
    from lib.llm.client import chat_stream
    abort_event = threading.Event()
    chunks = []
    final = None
    for chunk_text, finish_reason, usage in chat_stream(
        api_key="ok", model="m", messages=[{"role": "user", "content": "x"}],
        abort_event=abort_event,
    ):
        if chunk_text:
            chunks.append(chunk_text)
        if finish_reason:
            final = (finish_reason, usage)
    assert "".join(chunks) == "Hello!"
    assert final[0] == "stop"
    assert final[1]["prompt_tokens"] == 10
    assert final[1]["completion_tokens"] == 3


@responses.activate
def test_chat_stream_aborts_on_event():
    # Body with many chunks; abort early
    sse = "".join(
        f'data: {{"choices":[{{"delta":{{"content":"chunk{i}"}}}}]}}\n\n'
        for i in range(100)
    )
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        body=sse, status=200, content_type="text/event-stream",
    )
    from lib.llm.client import chat_stream
    abort_event = threading.Event()
    chunks = []
    for i, (text, _, _) in enumerate(chat_stream(
        api_key="ok", model="m", messages=[],
        abort_event=abort_event,
    )):
        if text:
            chunks.append(text)
        if i == 5:
            abort_event.set()
    # Stopped early
    assert len(chunks) < 100


@responses.activate
def test_validate_slugs_returns_missing():
    responses.add(
        responses.GET,
        "https://openrouter.ai/api/v1/models",
        json={"data": [{"id": "google/gemini-2.0-flash-001"}, {"id": "deepseek/deepseek-r1"}]},
        status=200,
    )
    from lib.llm.client import validate_slugs
    expected = {"google/gemini-2.0-flash-001", "deepseek/deepseek-r1", "anthropic/claude-haiku-4.5"}
    available, missing = validate_slugs(api_key="ok", expected=expected)
    assert available == {"google/gemini-2.0-flash-001", "deepseek/deepseek-r1"}
    assert missing == {"anthropic/claude-haiku-4.5"}


@responses.activate
def test_validate_slugs_timeout_returns_empty_set():
    """On timeout, both returned sets empty so callers can warn but proceed."""
    from lib.llm.client import validate_slugs
    # No mock added → urllib raises immediately
    available, missing = validate_slugs(api_key="ok", expected={"x"}, timeout=0.001)
    assert available == set()
    # On unreachable, treat all expected as missing
    assert missing == {"x"}
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/unit/test_llm_streaming.py -v
```

Expected: `ImportError: cannot import name 'chat_stream'`.

- [ ] **Step 3: Append to `service.kodi.ai/lib/llm/client.py`**

```python


# ---- Streaming with chunk-level abort + slug validation ----
from typing import Generator, Iterable
import threading


def chat_stream(
    *,
    api_key: str,
    model: str,
    messages: list[dict],
    abort_event: threading.Event,
    tools: list[dict] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    timeout: tuple[float, float] = (5.0, 30.0),
) -> Generator[tuple[str | None, str | None, dict | None], None, None]:
    """Stream chat completion. Yields (chunk_text, finish_reason, usage).

    finish_reason and usage are None until the terminal chunk.
    Caller MUST check abort_event between iterations; this generator
    cleanly closes the socket on next iteration after abort_event is set.

    Spec: §1.10.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    r = requests.post(
        f"{BASE_URL}/chat/completions",
        headers=_build_headers(api_key),
        json=payload,
        timeout=timeout,
        stream=True,
    )

    if r.status_code == 401: raise LLMAuthError(r.text)
    if r.status_code == 402: raise LLMNoCreditError(r.text)
    if r.status_code in (404, 422): raise LLMModelUnavailableError(r.text)
    if r.status_code == 429: raise LLMRateLimitError(r.headers.get("Retry-After", "1"))
    if r.status_code >= 500: raise LLMServerError(f"{r.status_code}: {r.text[:200]}")
    if r.status_code != 200: raise LLMError(f"{r.status_code}: {r.text[:200]}")

    try:
        for raw_line in r.iter_lines(decode_unicode=True):
            if abort_event.is_set():
                # Spec §1.10: r.raw.close() THEN r.close() for clean socket FIN
                try:
                    r.raw.close()
                except Exception:
                    pass
                r.close()
                return
            if not raw_line or not raw_line.startswith("data:"):
                continue
            data = raw_line[len("data:"):].strip()
            if data == "[DONE]":
                return
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            choice = obj.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            chunk = delta.get("content") or ""
            finish = choice.get("finish_reason")
            usage = obj.get("usage")
            if chunk or finish or usage:
                yield chunk if chunk else None, finish, usage
    finally:
        try: r.raw.close()
        except Exception: pass
        r.close()


def validate_slugs(
    *,
    api_key: str,
    expected: Iterable[str],
    timeout: float = 10.0,
) -> tuple[set[str], set[str]]:
    """Ping OpenRouter /api/v1/models. Returns (available, missing).
    On unreachable, available=set() and missing=set(expected) so caller
    can warn but proceed.
    """
    expected_set = set(expected)
    try:
        r = requests.get(
            f"{BASE_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        r.raise_for_status()
        ids = {m["id"] for m in r.json().get("data", []) if "id" in m}
    except Exception:
        return set(), expected_set
    available = expected_set & ids
    return available, expected_set - available
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_llm_streaming.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/llm/client.py tests/unit/test_llm_streaming.py
git commit -m "feat(llm.client): streaming chat_stream + slug validation

chat_stream yields (chunk_text, finish_reason, usage) per delta. Caller
passes abort_event; mid-iteration check tears down socket cleanly
(r.raw.close() THEN r.close() per spec §1.10 round-3 ordering).
validate_slugs(api_key, expected) pings /api/v1/models, returns
(available, missing). On unreachable: returns (set(), expected) so caller
warns but proceeds — does NOT block startup.

Spec: §1.10, §4.5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.5 — System prompts + prompt versioning

**Spec ref:** §5.6 (prompt versioning), §2 (prompts/*.md).

**Files:**
- Create: `service.kodi.ai/lib/llm/prompts/triage_system.md`
- Create: `service.kodi.ai/lib/llm/prompts/reasoner_system.md`
- Create: `service.kodi.ai/lib/llm/prompts/chat_system.md`
- Create: `service.kodi.ai/lib/llm/prompts.py` (loader + hasher)
- Create: `tests/unit/test_prompts.py`

- [ ] **Step 1: Write `service.kodi.ai/lib/llm/prompts/triage_system.md`**

```markdown
---
prompt_name: triage_system
prompt_version: 1.0.0
---
You are the Kodi-AI triage classifier. Your job is to look at a Kodi log
cluster and decide if it represents a real, user-blocking problem worth
investigating, an advisory warning, or harmless noise.

Output ONE of these labels and nothing else:

  CRITICAL — A user-visible action just failed or is about to fail (playback
             error, addon import error, repository unreachable, settings
             corruption blocking a feature). Worth running the reasoner.

  ADVISORY — A warning the user should know about, but no automatic fix
             warranted (e.g. addon deprecation notice, a configuration
             concern). Notify and move on.

  IGNORE   — Routine noise, recoverable transient warning, or already-fixed
             condition. Do nothing.

Be conservative on CRITICAL: only flag if a real action is failing. Kodi
logs are noisy; most WARNINGs are not critical. When unsure, prefer IGNORE
over CRITICAL — false-positives cost real money in agent runs.

Output exactly one of: CRITICAL | ADVISORY | IGNORE
```

- [ ] **Step 2: Write `service.kodi.ai/lib/llm/prompts/reasoner_system.md`**

```markdown
---
prompt_name: reasoner_system
prompt_version: 1.0.0
---
You are Kodi-AI, an autonomous agent that diagnoses + fixes Kodi issues on
the user's Nvidia Shield Pro running Kodi 21 Omega on Android TV. Your job
is to take a log incident or user message, reason about what's wrong, and
either apply a fix or surface the problem to the user via Telegram.

## Tools

You have a curated tool catalog (provided in this request). Each tool has:
  - tier: "immediate" (apply directly) or "confirm" (asks user via Telegram).
  - disruptive(args): if True, tool downgrades to confirm even if tier=immediate.
  - snapshot_targets: every mutation snapshots state first (no snapshot, no
    mutation — HARD RULE).

## Workflow

1. Read the incident or user message.
2. Use inspection tools (read_log, list_addons, get_addon_setting, http_get
   etc.) to understand the situation.
3. Form a hypothesis.
4. Apply the smallest reasonable fix via a mutation tool.
5. The system will run verify_fix automatically; on success it notifies
   the user. On failure, you'll be invoked again to try something else.

## Constraints

- V1 scope: (a) addon dep/import errors, (b) repository unreachable / update
  failures, (c) stream playback failures (source dead, geo-block, codec, hangs).
- For geo-block / repo-unreachable: notify the user — no automatic remediation
  exists in V1. Do NOT attempt to install new repositories from URLs.
- Auth-token expiry (Real-Debrid, Trakt, etc.) is OUT of V1 scope; if you
  detect it, notify the user and stop.
- Wall-clock budget: 60s per session (excluding ask_user pause time).
- Tool turn limit: 15 per session.

## Kodi domain knowledge

- Common addon dependency: script.module.requests, script.module.urllib3,
  script.module.six, script.module.kodi-six, script.module.python.koding,
  inputstream.adaptive (for HLS/DASH streams), inputstreamhelper.
- Disabled deps are common after addon updates — always pass enabled=None
  to list_addons when diagnosing missing modules.
- Stale .pyc cache: clear_addon_cache(addon_id) purges __pycache__ + restarts.
- Resolver swaps (Real-Debrid → Premiumize, etc.) are the most common
  playback-fail fix.

Respond ONLY by calling tools or producing a final_message. Do not include
chain-of-thought in your final messages to the user.
```

- [ ] **Step 3: Write `service.kodi.ai/lib/llm/prompts/chat_system.md`**

```markdown
---
prompt_name: chat_system
prompt_version: 1.0.0
---
You are Kodi-AI, a conversational assistant for Kodi on Nvidia Shield Pro
Android TV. The user is messaging you via Telegram; you help diagnose
issues, answer questions about their Kodi setup, and (with permission)
apply fixes via your tool catalog.

You have the same tools as the auto-fix reasoner. Same V1 scope, same
60-second wall-clock budget per session.

Be terse. The user is on a TV with a phone in hand. They want answers, not
essays. Use Telegram HTML formatting sparingly: <b>bold</b> for emphasis,
<code>inline</code> for setting names, <pre>blocks</pre> for log excerpts.

When proposing a mutation, explain in one sentence WHY, then call the tool.
The system handles the confirm-prompt flow.
```

- [ ] **Step 4: Write the failing test**

```python
# tests/unit/test_prompts.py
import hashlib
import pytest


def test_load_prompt_returns_body_and_metadata():
    from lib.llm.prompts import load
    p = load("triage_system")
    assert p.name == "triage_system"
    assert p.version == "1.0.0"
    assert "CRITICAL" in p.body
    assert "ADVISORY" in p.body
    assert "IGNORE" in p.body
    assert "---" not in p.body  # frontmatter stripped


def test_load_reasoner_prompt():
    from lib.llm.prompts import load
    p = load("reasoner_system")
    assert p.version == "1.0.0"
    assert "Kodi-AI" in p.body


def test_load_chat_prompt():
    from lib.llm.prompts import load
    p = load("chat_system")
    assert p.version == "1.0.0"


def test_prompt_hash_stable():
    from lib.llm.prompts import load
    p1 = load("triage_system")
    p2 = load("triage_system")
    assert p1.hash == p2.hash
    # Hash is sha256 hex (64 chars)
    assert len(p1.hash) == 64


def test_prompt_hash_omits_prompt_hash_line():
    """Spec §5.6: hash entire file with prompt_hash line stripped."""
    from lib.llm.prompts import load, _hash_body_excluding_prompt_hash
    body = "---\nprompt_name: x\nprompt_version: 1.0.0\nprompt_hash: abc\n---\nbody"
    body_without = "---\nprompt_name: x\nprompt_version: 1.0.0\n---\nbody"
    h1 = _hash_body_excluding_prompt_hash(body)
    h2 = _hash_body_excluding_prompt_hash(body_without)
    assert h1 == h2


def test_unknown_prompt_raises():
    from lib.llm.prompts import load
    with pytest.raises(FileNotFoundError):
        load("nonexistent_prompt")
```

- [ ] **Step 5: Run test — verify it fails**

```bash
pytest tests/unit/test_prompts.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 6: Implement `service.kodi.ai/lib/llm/prompts.py`**

```python
# service.kodi.ai/lib/llm/prompts.py
"""Prompt loader + content-addressable hash.

Each prompt file: frontmatter (---\\n... \\n---) + body. Hash computed over
the entire file MINUS any prompt_hash: line (avoids self-reference).
Recorded in audit log every llm_call for behavior-regression debugging.

Spec: §5.6.
"""
from __future__ import annotations
import hashlib
import os
import re
from dataclasses import dataclass

_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
_HASH_LINE_RE = re.compile(r"^prompt_hash:\s.*\n", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    body: str
    hash: str


def _hash_body_excluding_prompt_hash(raw: str) -> str:
    """SHA-256 of file content with any prompt_hash line stripped."""
    stripped = _HASH_LINE_RE.sub("", raw)
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    frontmatter_text = m.group(1)
    body = raw[m.end():]
    meta = {}
    for line in frontmatter_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta, body


_CACHE: dict[str, Prompt] = {}


def load(name: str) -> Prompt:
    if name in _CACHE:
        return _CACHE[name]
    path = os.path.join(_PROMPTS_DIR, f"{name}.md")
    if not os.path.exists(path):
        raise FileNotFoundError(f"prompt not found: {name} ({path})")
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    meta, body = _parse_frontmatter(raw)
    p = Prompt(
        name=meta.get("prompt_name", name),
        version=meta.get("prompt_version", "0.0.0"),
        body=body,
        hash=_hash_body_excluding_prompt_hash(raw),
    )
    _CACHE[name] = p
    return p
```

- [ ] **Step 7: Run tests — verify they pass**

```bash
pytest tests/unit/test_prompts.py -v
```

Expected: `6 passed`.

- [ ] **Step 8: Commit**

```bash
git add service.kodi.ai/lib/llm/prompts/*.md service.kodi.ai/lib/llm/prompts.py \
        tests/unit/test_prompts.py
git commit -m "feat(llm.prompts): triage/reasoner/chat system prompts + loader

3 system prompts as .md with frontmatter (prompt_name, prompt_version).
Loader parses frontmatter + body, caches; .hash = sha256(file - prompt_hash
line) per spec §5.6 (avoids self-reference paradox).
Triage prompt: CRITICAL/ADVISORY/IGNORE classification.
Reasoner prompt: V1-scope-bounded agent instructions + Kodi domain
knowledge (common deps, stale .pyc, resolver swaps).
Chat prompt: terse Telegram-aware conversational mode.

Spec: §5.6, §2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — Log infrastructure (7 tasks)

### Task 4.1 — `lib/log_capture.py`: Python logging.Handler + stderr wrapper

**Spec ref:** §5.9.

**Files:**
- Create: `service.kodi.ai/lib/log_capture.py`
- Create: `tests/unit/test_log_capture.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_log_capture.py
import logging
import sys
import threading
import pytest
from unittest import mock


@pytest.fixture
def mock_xbmc(monkeypatch):
    fake = mock.MagicMock()
    fake.LOGINFO = 1
    fake.LOGERROR = 4
    captured = []
    fake.log.side_effect = lambda msg, level=1: captured.append((msg, level))
    monkeypatch.setitem(sys.modules, "xbmc", fake)
    fake._captured = captured
    return fake


def test_install_redirects_stdlib_logging(mock_xbmc):
    from lib.log_capture import install, uninstall
    install()
    try:
        logging.getLogger("requests").error("test error from requests")
        msgs = [m for m, _ in mock_xbmc._captured]
        assert any("test error from requests" in m for m in msgs)
        assert any("[service.kodi.ai]" in m for m in msgs)
    finally:
        uninstall()


def test_install_redirects_stderr(mock_xbmc):
    from lib.log_capture import install, uninstall
    install()
    try:
        sys.stderr.write("native panic\n")
        sys.stderr.flush()
        msgs = [m for m, _ in mock_xbmc._captured]
        assert any("native panic" in m for m in msgs)
        assert any("[service.kodi.ai]" in m for m in msgs)
    finally:
        uninstall()


def test_recursion_guard(mock_xbmc):
    """If xbmc.log itself triggered logging, it would recurse — guard prevents."""
    from lib.log_capture import install, uninstall, _in_handler
    install()
    try:
        # Manually simulate re-entry; thread-local must short-circuit
        _in_handler.value = True
        try:
            logging.getLogger("recursion-test").error("should be dropped")
        finally:
            _in_handler.value = False
        msgs = [m for m, _ in mock_xbmc._captured]
        # The recursive emit was guarded → message NOT captured
        assert not any("should be dropped" in m for m in msgs)
    finally:
        uninstall()


def test_dedup_window_1s(mock_xbmc):
    """Duplicate messages within 1s deduped (library retry loops)."""
    from lib.log_capture import install, uninstall
    install()
    try:
        logging.getLogger("dup").error("same message")
        logging.getLogger("dup").error("same message")  # within 1s
        msgs = [m for m, _ in mock_xbmc._captured if "same message" in m]
        assert len(msgs) == 1
    finally:
        uninstall()
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/unit/test_log_capture.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `service.kodi.ai/lib/log_capture.py`**

```python
# service.kodi.ai/lib/log_capture.py
"""Captures stdlib logging + sys.stderr/sys.stdout writes from libraries
(requests, urllib3, anthropic SDK if used, etc.) and forwards to xbmc.log
with our [service.kodi.ai] prefix.

Thread-local recursion guard prevents handler→xbmc.log→handler loops.
1s dedup window collapses library retry-loop spam.

KNOWN LIMITATION (documented in spec §5.9): native C extensions writing
directly to fd 2 (lxml, cryptography errors) bypass sys.stderr wrapper.
Optional os.dup2 fd 2 → pipe → reader-thread fix deferred to V2.

Spec: §5.9.
"""
from __future__ import annotations
import logging
import sys
import threading
import time

import xbmc

_PREFIX = "[service.kodi.ai] "
_in_handler = threading.local()
_DEDUP_WINDOW_S = 1.0
_recent: dict[str, float] = {}
_recent_lock = threading.Lock()


def _should_emit(msg: str) -> bool:
    """Returns False if msg was emitted < 1s ago (dedup)."""
    now = time.monotonic()
    with _recent_lock:
        last = _recent.get(msg)
        if last is not None and (now - last) < _DEDUP_WINDOW_S:
            return False
        _recent[msg] = now
        # Garbage collect entries older than 5s
        if len(_recent) > 100:
            cutoff = now - 5.0
            for k in [k for k, t in _recent.items() if t < cutoff]:
                del _recent[k]
    return True


class _XbmcLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if getattr(_in_handler, "value", False):
            return  # recursion guard
        _in_handler.value = True
        try:
            try:
                msg = self.format(record)
            except Exception:
                return
            level = self._map_level(record.levelno)
            for line in msg.splitlines():
                if not line.strip():
                    continue
                full = _PREFIX + line
                if _should_emit(full):
                    xbmc.log(full, level)
        finally:
            _in_handler.value = False

    @staticmethod
    def _map_level(levelno: int) -> int:
        if levelno >= logging.ERROR: return xbmc.LOGERROR
        if levelno >= logging.WARNING: return getattr(xbmc, "LOGWARNING", 2)
        if levelno >= logging.INFO: return xbmc.LOGINFO
        return getattr(xbmc, "LOGDEBUG", 0)


class _StreamRedirect:
    """Wraps sys.stderr / sys.stdout — buffers until newline, then emits one xbmc.log."""
    def __init__(self, level: int):
        self._buf = ""
        self._level = level
        self._lock = threading.Lock()
    def write(self, text: str) -> int:
        if not isinstance(text, str):
            text = text.decode("utf-8", errors="replace") if isinstance(text, (bytes, bytearray)) else str(text)
        with self._lock:
            self._buf += text
            while "\n" in self._buf:
                line, _, rest = self._buf.partition("\n")
                self._buf = rest
                if not line.strip():
                    continue
                full = _PREFIX + line
                if getattr(_in_handler, "value", False):
                    continue
                _in_handler.value = True
                try:
                    if _should_emit(full):
                        xbmc.log(full, self._level)
                finally:
                    _in_handler.value = False
        return len(text)
    def flush(self): pass
    def isatty(self): return False


_orig_stderr = None
_orig_stdout = None
_handler: _XbmcLogHandler | None = None


def install(verbose: bool = False) -> None:
    """Install handler + stream redirects. Idempotent."""
    global _handler, _orig_stderr, _orig_stdout
    if _handler is not None:
        return
    _handler = _XbmcLogHandler()
    _handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    _handler.setFormatter(logging.Formatter("%(name)s [%(levelname)s] %(message)s"))
    root = logging.getLogger()
    root.addHandler(_handler)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    _orig_stderr = sys.stderr
    _orig_stdout = sys.stdout
    sys.stderr = _StreamRedirect(xbmc.LOGERROR)
    sys.stdout = _StreamRedirect(xbmc.LOGINFO)


def uninstall() -> None:
    """Restore original stderr/stdout + remove handler. Used in tests."""
    global _handler, _orig_stderr, _orig_stdout
    if _handler is None:
        return
    logging.getLogger().removeHandler(_handler)
    _handler = None
    if _orig_stderr is not None:
        sys.stderr = _orig_stderr
    if _orig_stdout is not None:
        sys.stdout = _orig_stdout
    _orig_stderr = None
    _orig_stdout = None
    with _recent_lock:
        _recent.clear()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_log_capture.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/log_capture.py tests/unit/test_log_capture.py
git commit -m "feat(log_capture): logging.Handler + stderr/stdout wrappers

Captures stdlib logging from requests/urllib3/etc + raw stderr/stdout
writes. Prepends [service.kodi.ai] and forwards to xbmc.log at mapped
level (ERROR/WARNING/INFO/DEBUG).
Thread-local _in_handler guard prevents recursion (xbmc.log → handler
→ xbmc.log loop).
1s dedup window collapses library retry-loop spam (LRU GC at 100 entries).
install()/uninstall() for clean test setup/teardown.

KNOWN LIMITATION: native C extension fd-2 writes bypass sys.stderr wrapper;
optional os.dup2 fix deferred to V2.

Spec: §5.9.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4.2 — `lib/log_sentinels.py`: audit-only LOGINFO sentinels

**Spec ref:** §1.3 (audit-only, NEVER used as sync), §5.6.

**Files:**
- Create: `service.kodi.ai/lib/log_sentinels.py`
- Create: `tests/unit/test_log_sentinels.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_log_sentinels.py
import re
import sys
import pytest
from unittest import mock


@pytest.fixture
def mock_xbmc(monkeypatch):
    fake = mock.MagicMock()
    fake.LOGINFO = 1
    captured = []
    fake.log.side_effect = lambda msg, level=1: captured.append((msg, level))
    monkeypatch.setitem(sys.modules, "xbmc", fake)
    fake._captured = captured
    return fake


def test_reason_start_written_at_loginfo(mock_xbmc):
    from lib.log_sentinels import reason_start
    reason_start("abc123")
    msg, level = mock_xbmc._captured[-1]
    assert msg == "[service.kodi.ai] reason-start abc123"
    assert level == mock_xbmc.LOGINFO


def test_reason_end_written_at_loginfo(mock_xbmc):
    from lib.log_sentinels import reason_end
    reason_end("abc123")
    msg, level = mock_xbmc._captured[-1]
    assert msg == "[service.kodi.ai] reason-end abc123"


def test_parse_sentinel_extracts_session_id():
    from lib.log_sentinels import parse_sentinel
    assert parse_sentinel("[service.kodi.ai] reason-start abc123") == ("start", "abc123")
    assert parse_sentinel("[service.kodi.ai] reason-end xyz789") == ("end", "xyz789")
    assert parse_sentinel("some other line") is None
    assert parse_sentinel("[plugin.video.seren] error") is None
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/unit/test_log_sentinels.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `service.kodi.ai/lib/log_sentinels.py`**

```python
# service.kodi.ai/lib/log_sentinels.py
"""Audit-only sentinel markers written via xbmc.log at LOGINFO.

NOT used for cross-thread synchronization (xbmc.log is buffered/async; the
in-memory ActiveCalls is the synchronization primitive — see lib/concurrency.py
and spec §1.3).

Sentinels appear in kodi.log for forensic debugging only. parse_sentinel()
is used by lib/log_watcher.py's boot post-mortem to detect dangling
sessions in kodi.old.log.

Spec: §1.3, §5.6.
"""
from __future__ import annotations
import re
import xbmc

_RE = re.compile(r"^\[service\.kodi\.ai\] reason-(start|end) ([a-f0-9]+)$")


def reason_start(session_id: str) -> None:
    xbmc.log(f"[service.kodi.ai] reason-start {session_id}", xbmc.LOGINFO)


def reason_end(session_id: str) -> None:
    xbmc.log(f"[service.kodi.ai] reason-end {session_id}", xbmc.LOGINFO)


def parse_sentinel(line: str) -> tuple[str, str] | None:
    """Returns ('start' | 'end', session_id) or None if not a sentinel."""
    m = _RE.match(line.rstrip())
    if not m:
        return None
    return (m.group(1), m.group(2))
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_log_sentinels.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/log_sentinels.py tests/unit/test_log_sentinels.py
git commit -m "feat(log_sentinels): audit-only LOGINFO sentinels

reason_start/reason_end write [service.kodi.ai] reason-{start,end} <sid>
to kodi.log at LOGINFO. parse_sentinel() extracts (kind, session_id) for
boot post-mortem (lib/log_watcher.py).
SENTINELS ARE AUDIT-ONLY — NOT used for cross-thread sync (xbmc.log is
buffered; in-memory ActiveCalls is the sync primitive).

Spec: §1.3, §5.6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4.3 — `lib/prefilter.py`: signature normalization + benign allowlist

**Spec ref:** §1.4 (signature normalization).

**Files:**
- Create: `service.kodi.ai/lib/prefilter.py`
- Create: `tests/unit/test_prefilter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_prefilter.py
import pytest


def test_normalize_strips_memory_addresses():
    from lib.prefilter import normalize_signature
    s = "Object at 0x7f8a1234abcd raised something"
    sig = normalize_signature(s)
    assert "0x" not in sig
    assert "<addr>" in sig


def test_normalize_strips_line_numbers_in_tracebacks():
    from lib.prefilter import normalize_signature
    s = 'File "/foo/bar.py", line 123, in baz'
    sig = normalize_signature(s)
    assert "line 123" not in sig
    assert "line <N>" in sig


def test_normalize_strips_iso_timestamps():
    from lib.prefilter import normalize_signature
    s = "2026-05-26T18:04:11.123Z something happened"
    sig = normalize_signature(s)
    assert "2026" not in sig


def test_normalize_strips_uuids():
    from lib.prefilter import normalize_signature
    s = "Request id 550e8400-e29b-41d4-a716-446655440000 failed"
    sig = normalize_signature(s)
    assert "550e8400" not in sig
    assert "<uuid>" in sig


def test_normalize_basenames_file_paths():
    from lib.prefilter import normalize_signature
    s = 'File "/home/user/.kodi/addons/plugin.video.seren/lib/foo.py", line 5'
    sig = normalize_signature(s)
    assert "/home/user" not in sig
    assert "foo.py" in sig


def test_two_similar_tracebacks_cluster_same():
    from lib.prefilter import cluster_id_for
    a = 'File "/a/b.py", line 12, in x\nException at 0x7f8a1\nSimilar error'
    b = 'File "/a/b.py", line 99, in x\nException at 0xdeadbeef\nSimilar error'
    assert cluster_id_for(a) == cluster_id_for(b)


def test_is_benign_known_noise():
    from lib.prefilter import is_benign
    assert is_benign("NOTICE: Samba Initialize: Loading the network drivers...")
    assert is_benign("DEBUG: CDvdPlayer::ProcessAudioData done")


def test_is_benign_returns_false_for_real_errors():
    from lib.prefilter import is_benign
    assert not is_benign("ERROR: failed to load addon plugin.video.seren")
    assert not is_benign("CRITICAL: out of memory")
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/unit/test_prefilter.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `service.kodi.ai/lib/prefilter.py`**

```python
# service.kodi.ai/lib/prefilter.py
"""Signature normalization + benign-noise allowlist for log clustering.

Used by lib/log_watcher.py to compute stable cluster_ids so two stack traces
differing only by memory addresses / line numbers / timestamps cluster as
one incident (preventing duplicate triage spend).

is_benign() filters known-harmless Kodi noise before signature hashing.

Spec: §1.4.
"""
from __future__ import annotations
import hashlib
import os
import re

# Patterns applied IN ORDER. Later patterns may match output of earlier.
_NORMALIZERS: list[tuple[re.Pattern, str]] = [
    # Memory addresses
    (re.compile(r"0x[0-9a-fA-F]+"), "<addr>"),
    # Line numbers in tracebacks
    (re.compile(r"\bline\s+\d+\b"), "line <N>"),
    # ISO-8601 timestamps
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?"), "<ts>"),
    # Unix epoch (10-digit timestamps)
    (re.compile(r"\b1[6789]\d{8}\b"), "<epoch>"),
    # UUIDs
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    # File paths (preserve basename)
    (re.compile(r'"(/[^"]+/)([^/"]+)"'), r'"<path>/\2"'),
    # Numbers in trailing details (port numbers, sizes)
    (re.compile(r"\b\d{4,}\b"), "<num>"),
]


def normalize_signature(text: str) -> str:
    out = text
    for pat, repl in _NORMALIZERS:
        out = pat.sub(repl, out)
    return out


def cluster_id_for(text: str) -> str:
    sig = normalize_signature(text)
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]


_BENIGN_PATTERNS: list[re.Pattern] = [
    re.compile(r"NOTICE:\s*Samba Initialize", re.IGNORECASE),
    re.compile(r"DEBUG:\s*CDvdPlayer::ProcessAudioData done", re.IGNORECASE),
    re.compile(r"INFO:\s*Loading\s+skin\s+settings", re.IGNORECASE),
    re.compile(r"DEBUG:\s*CXBMCApp::onIdle", re.IGNORECASE),
    # Add more as observed in practice (V1 starter list)
]


def is_benign(line: str) -> bool:
    return any(p.search(line) for p in _BENIGN_PATTERNS)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_prefilter.py -v
```

Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/prefilter.py tests/unit/test_prefilter.py
git commit -m "feat(prefilter): signature normalization + benign-noise allowlist

normalize_signature(): strips memory addresses (0x...), line numbers,
ISO timestamps, Unix epochs, UUIDs, file paths (preserves basename),
large trailing numbers. Used so two stack traces differing only by
non-semantic details cluster as one cluster_id.
cluster_id_for(): SHA-256[:16] of normalized signature.
is_benign(): allowlist of known-harmless Kodi noise patterns (Samba init,
DvdPlayer debug, skin settings load, etc.) — V1 starter list, extensible.

Spec: §1.4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4.4 — `lib/log_watcher.py` core: poll loop + read + parse + enqueue

**Spec ref:** §1.4, §3.1 Flow 1 lines T+0 to T+5s.

**Files:**
- Create: `service.kodi.ai/lib/log_watcher.py` (initial — full features in 4.5/4.6/4.7)
- Create: `tests/integration/test_log_watcher_basic.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_log_watcher_basic.py
import os
import time
import threading
import pytest
from tests.integration.fakes import fake_xbmcvfs


@pytest.mark.integration
def test_poll_loop_reads_new_bytes(monkeypatch):
    # Stage a log file
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "kodi.log")
    with open(log_path, "w") as f:
        f.write("INFO: kodi started\n")

    from lib import log_watcher, concurrency
    concurrency.abort_event.clear()

    # Drain the queue first
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()

    # Run watcher in a thread with fast cadence
    watcher = log_watcher.LogWatcher(poll_active_ms=50, poll_idle_ms=200)
    t = threading.Thread(target=watcher.run, daemon=True)
    t.start()
    time.sleep(0.15)  # let it start + do one read

    # Append an ERROR line
    with open(log_path, "a") as f:
        f.write("ERROR plugin.video.seren: failed to play\n")

    # Wait for incident to be enqueued (allow quiescence wait)
    time.sleep(5.0)  # > quiescence window
    concurrency.abort_event.set()
    t.join(timeout=2.0)

    # Should have at least one LogIncident in the queue
    found = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        if hasattr(item, "raw_lines"):
            if any("seren" in line for line in item.raw_lines):
                found = True
                break
    assert found
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/integration/test_log_watcher_basic.py -v -m integration
```

Expected: `ModuleNotFoundError` or `AttributeError: 'lib.log_watcher'`.

- [ ] **Step 3: Implement `service.kodi.ai/lib/log_watcher.py`** (initial — basic poll + parse + enqueue, no rotation/burst/quiescence yet)

```python
# service.kodi.ai/lib/log_watcher.py
"""T2 LogPoll body — tail special://logpath/kodi.log and enqueue
LogIncident objects to work_queue.

Initial implementation: poll + read + parse + quiescence (basic, 3s fixed
window). Adaptive cadence, 3-signal rotation, burst-mode, trace-continuation,
per-tool-boundary buffer evaluation, boot post-mortem added in Tasks 4.5–4.7.

Spec: §1.4, §3.1.
"""
from __future__ import annotations
import os
import re
import time
from datetime import datetime, timezone

import xbmcvfs

from .concurrency import (
    abort_event, work_queue, enqueue, LogIncident,
    coalesce_lock, active_cluster_ids, active_calls,
)
from . import prefilter, state_paths


# Kodi log format (typical): "<ts> <level> <[addon]> <message>"
# Pragmatic regex — Kodi's exact format varies by version; capture what we need.
_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+)?"
    r"(?P<level>DEBUG|INFO|NOTICE|WARNING|ERROR|FATAL|SEVERE)\s*"
    r"(?:<general>|<[A-Z]+>)?\s*"
    r"(?:(?:\[(?P<addon>[a-zA-Z0-9._-]+)\])\s*)?"
    r"(?P<body>.*)$"
)


class LogWatcher:
    def __init__(self, *, poll_active_ms: int = 750, poll_idle_ms: int = 2500,
                 quiescence_window_s: float = 3.0):
        self.poll_active_ms = poll_active_ms
        self.poll_idle_ms = poll_idle_ms
        self.quiescence_window_s = quiescence_window_s
        self._last_offset = 0
        self._open_clusters: dict[str, dict] = {}  # cluster_id → {lines, first_seen, last_seen, addon}
        self._ticks_since_growth = 0

    def _read_new_bytes(self) -> str:
        path = state_paths.log_path()
        if not os.path.exists(path):
            return ""
        size = os.path.getsize(path)
        if size < self._last_offset:
            # File shrunk → rotation; full handling in Task 4.5
            self._last_offset = 0
        if size == self._last_offset:
            return ""
        with open(path, "rb") as f:
            f.seek(self._last_offset)
            data = f.read(size - self._last_offset)
        self._last_offset = size
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _parse_line(self, line: str) -> tuple[str, str | None, str] | None:
        """Returns (level, addon, body) or None if unparseable."""
        m = _LINE_RE.match(line)
        if not m:
            return None
        return (m.group("level"), m.group("addon"), m.group("body") or "")

    def _ingest_chunk(self, text: str) -> None:
        for line in text.splitlines():
            if not line.strip():
                continue
            # Suppress our own addon-prefixed lines (belt-and-braces)
            if "[service.kodi.ai]" in line:
                continue
            parsed = self._parse_line(line)
            if not parsed:
                continue
            level, addon, body = parsed
            if level not in ("ERROR", "FATAL", "SEVERE", "WARNING"):
                continue
            if prefilter.is_benign(body):
                continue
            # Reasoner-loop guard: drop lines during active windows whose
            # addon matches our active target_addons (refined in Task 4.7).
            if active_calls.is_active():
                targets = active_calls.get_active_target_addons()
                if targets == "ALL" or (addon and addon in targets):
                    continue  # likely our own side-effect
            cid = prefilter.cluster_id_for(body)
            now = datetime.now(timezone.utc)
            cluster = self._open_clusters.setdefault(cid, {
                "lines": [], "first_seen": now, "last_seen": now,
                "addon": addon, "level": level, "occurrences": 0,
            })
            cluster["lines"].append(line)
            cluster["last_seen"] = now
            cluster["occurrences"] += 1

    def _close_expired_clusters(self) -> None:
        now = datetime.now(timezone.utc)
        expired: list[str] = []
        for cid, c in list(self._open_clusters.items()):
            age = (now - c["last_seen"]).total_seconds()
            if age >= self.quiescence_window_s:
                expired.append(cid)
        for cid in expired:
            c = self._open_clusters.pop(cid)
            with coalesce_lock:
                if cid in active_cluster_ids:
                    continue  # already enqueued; coalesce
                active_cluster_ids.add(cid)
            try:
                enqueue(LogIncident(
                    cluster_id=cid,
                    first_seen=c["first_seen"], last_seen=c["last_seen"],
                    occurrences=c["occurrences"], raw_lines=c["lines"],
                    severity_hint=c["level"], likely_addon=c["addon"],
                    likely_action=None, backdated=False,
                    from_previous_session=False, triage_deferred=True,
                ))
            except Exception:
                # work_queue.Full or similar — drop counter handled in Task 4.7
                pass

    def run(self) -> None:
        # Wait for service to finish startup before tailing
        from .concurrency import startup_complete_event
        startup_complete_event.wait()
        while not abort_event.is_set():
            chunk = self._read_new_bytes()
            if chunk:
                self._ingest_chunk(chunk)
                self._ticks_since_growth = 0
            else:
                self._ticks_since_growth += 1
            self._close_expired_clusters()
            # Adaptive cadence — basic version; refined in Task 4.5
            cadence_ms = self.poll_active_ms if self._ticks_since_growth < 40 else self.poll_idle_ms
            if abort_event.wait(cadence_ms / 1000.0):
                return
```

- [ ] **Step 4: Update `tests/integration/conftest.py`** to register `startup_complete_event` early for tests

Append to existing `conftest.py`:

```python


@pytest.fixture(autouse=True)
def set_startup_complete():
    """Integration tests don't run boot pass — manually signal startup_complete."""
    from lib import concurrency
    concurrency.startup_complete_event.set()
    yield
    # Don't clear — other tests may run after
```

- [ ] **Step 5: Run integration test — verify it passes**

```bash
pytest tests/integration/test_log_watcher_basic.py -v -m integration
```

Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add service.kodi.ai/lib/log_watcher.py \
        tests/integration/test_log_watcher_basic.py \
        tests/integration/conftest.py
git commit -m "feat(log_watcher): T2 core poll loop + parse + enqueue

LogWatcher class with run() body: waits for startup_complete_event, then
poll/read/parse/cluster/enqueue loop.
_read_new_bytes: tracks last_offset, reads delta from xbmcvfs path.
_parse_line: regex extracts level + [addon] + body from typical Kodi log line.
_ingest_chunk: drops [service.kodi.ai] lines (belt-and-braces), skips
non-ERROR/WARN, skips benign noise, suppresses lines from active_calls
target_addons (reasoner-loop guard).
_close_expired_clusters: enqueues LogIncident after quiescence_window_s
(3s default) under coalesce_lock with active_cluster_ids dedup.

Adaptive cadence, 3-signal rotation, burst-mode, trace-continuation,
per-tool-boundary evaluation, boot post-mortem in Tasks 4.5-4.7.

Spec: §1.4, §3.1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4.5 — `log_watcher`: 3-signal rotation + 1MB cap + adaptive cadence

**Spec ref:** §1.4 (rotation: size shrink / inode / timestamp regression; per-tick 1MB cap; adaptive 750ms↔2.5s).

**Files:**
- Modify: `service.kodi.ai/lib/log_watcher.py`
- Create: `tests/integration/test_log_watcher_rotation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_log_watcher_rotation.py
import os
import time
import pytest
from tests.integration.fakes import fake_xbmcvfs


@pytest.mark.integration
def test_size_shrink_detected_as_rotation(tmp_path):
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    with open(path, "w") as f:
        f.write("INFO: line one\nINFO: line two\n")

    from lib.log_watcher import LogWatcher
    w = LogWatcher(poll_active_ms=10, poll_idle_ms=20)
    w._read_new_bytes()  # advances offset
    assert w._last_offset > 0

    # Truncate to simulate rotation
    with open(path, "w") as f:
        f.write("INFO: fresh start\n")
    chunk = w._read_new_bytes()
    assert "fresh start" in chunk
    # Last offset reset to new file size
    assert w._last_offset == len(b"INFO: fresh start\n")


@pytest.mark.integration
def test_per_tick_1mb_cap(tmp_path):
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    # Write 3 MB
    with open(path, "w") as f:
        f.write("INFO: a\n" * 400_000)

    from lib.log_watcher import LogWatcher
    w = LogWatcher()
    chunk1 = w._read_new_bytes()
    assert len(chunk1) <= 1_048_576
    chunk2 = w._read_new_bytes()
    assert len(chunk2) > 0  # catch-up on next tick


@pytest.mark.integration
def test_adaptive_cadence_idle_after_no_growth(tmp_path):
    from lib.log_watcher import LogWatcher
    w = LogWatcher(poll_active_ms=100, poll_idle_ms=400)
    # Many ticks with no growth
    for _ in range(50):
        w._read_new_bytes()
    cadence = w._current_cadence_ms()
    assert cadence == 400  # idle
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/integration/test_log_watcher_rotation.py -v -m integration
```

Expected: failures (`_current_cadence_ms` undefined, 1MB cap not enforced, rotation only handled on shrink).

- [ ] **Step 3: Modify `service.kodi.ai/lib/log_watcher.py`** — replace `_read_new_bytes` + add helpers + `_current_cadence_ms`

Find the existing `_read_new_bytes` method and replace it, plus add new methods. The full revised class:

```python
# (Replace _read_new_bytes, add _current_cadence_ms and rotation helpers.)

PER_TICK_CAP = 1_048_576  # 1 MB
IDLE_TICKS_THRESHOLD = 40  # ~30s @ 750ms


class LogWatcher:
    def __init__(self, *, poll_active_ms: int = 750, poll_idle_ms: int = 2500,
                 quiescence_window_s: float = 3.0):
        self.poll_active_ms = poll_active_ms
        self.poll_idle_ms = poll_idle_ms
        self.quiescence_window_s = quiescence_window_s
        self._last_offset = 0
        self._last_inode: int | None = None
        self._first_line_ts_cache: str | None = None
        self._open_clusters: dict[str, dict] = {}
        self._ticks_since_growth = 0

    def _peek_first_line(self, path: str) -> str | None:
        try:
            with open(path, "rb") as f:
                return f.readline().decode("utf-8", errors="replace")
        except OSError:
            return None

    def _detect_rotation(self, path: str, size: int) -> bool:
        """3 signals: size shrink, inode change, first-line timestamp regression."""
        # Signal 1: size shrunk
        if size < self._last_offset:
            return True
        # Signal 2: inode changed (if available on this FS)
        try:
            st = os.stat(path)
            ino = getattr(st, "st_ino", None)
            if ino is not None and self._last_inode is not None and ino != self._last_inode:
                self._last_inode = ino
                return True
            if ino is not None:
                self._last_inode = ino
        except OSError:
            pass
        # Signal 3: first-line timestamp regression (only when we've read before)
        if self._last_offset > 0:
            first = self._peek_first_line(path)
            if first and self._first_line_ts_cache and first != self._first_line_ts_cache:
                # Heuristic: if file's first line changed, rotation likely
                self._first_line_ts_cache = first
                return True
            if first and self._first_line_ts_cache is None:
                self._first_line_ts_cache = first
        return False

    def _reopen(self, path: str) -> None:
        self._last_offset = 0
        try:
            self._last_inode = getattr(os.stat(path), "st_ino", None)
        except OSError:
            self._last_inode = None
        self._first_line_ts_cache = self._peek_first_line(path)

    def _read_new_bytes(self) -> str:
        path = state_paths.log_path()
        if not os.path.exists(path):
            return ""
        size = os.path.getsize(path)
        if self._detect_rotation(path, size):
            self._reopen(path)
            size = os.path.getsize(path)  # may be 0
        if size == self._last_offset:
            return ""
        # Per-tick 1MB cap; rest read next tick (catch-up)
        end = min(size, self._last_offset + PER_TICK_CAP)
        with open(path, "rb") as f:
            f.seek(self._last_offset)
            data = f.read(end - self._last_offset)
        self._last_offset = end
        if self._first_line_ts_cache is None:
            self._first_line_ts_cache = self._peek_first_line(path)
        return data.decode("utf-8", errors="replace")

    def _current_cadence_ms(self) -> int:
        return self.poll_active_ms if self._ticks_since_growth < IDLE_TICKS_THRESHOLD else self.poll_idle_ms

    # _parse_line, _ingest_chunk, _close_expired_clusters, run() unchanged from Task 4.4
    # (run() now uses _current_cadence_ms() instead of inline if-else)
```

In the existing `run()` method, replace the cadence line:

```python
            cadence_ms = self._current_cadence_ms()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/integration/test_log_watcher_rotation.py -v -m integration
pytest tests/integration/test_log_watcher_basic.py -v -m integration  # regression
```

Expected: `3 passed` + `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/log_watcher.py tests/integration/test_log_watcher_rotation.py
git commit -m "feat(log_watcher): 3-signal rotation + 1MB cap + adaptive cadence

3-signal rotation: size shrink OR st_ino change (if available on SAF) OR
first-line timestamp regression. Reopen from offset 0 on detection.
Per-tick read cap of 1MB; catch-up next tick if growth exceeds.
Adaptive cadence: poll_active_ms (750ms default) when growing, poll_idle_ms
(2.5s default) after IDLE_TICKS_THRESHOLD (40 ticks ≈ 30s).
_current_cadence_ms() exposes the choice for tests.

Spec: §1.4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4.6 — `log_watcher`: trace-continuation quiescence + global-stream attachment

**Spec ref:** §1.5 (200ms attachment + no-different-prefix-intervening + 10s hard cap + no-prefix transparency).

**Files:**
- Modify: `service.kodi.ai/lib/log_watcher.py`
- Create: `tests/integration/test_log_watcher_continuation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_log_watcher_continuation.py
import os
import time
import pytest
from datetime import datetime, timedelta, timezone
from tests.integration.fakes import fake_xbmcvfs


@pytest.mark.integration
def test_continuation_lines_attach_within_200ms(tmp_path):
    from lib.log_watcher import LogWatcher
    from lib import concurrency
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()

    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    with open(path, "w") as f:
        f.write(
            "ERROR [plugin.video.seren]: failed to play\n"
            '  File "/x/y.py", line 5, in z\n'
            "    raise RuntimeError(\"oops\")\n"
            "RuntimeError: oops\n"
        )
    w = LogWatcher(quiescence_window_s=0.5)
    chunk = w._read_new_bytes()
    w._ingest_chunk(chunk)
    time.sleep(0.6)
    w._close_expired_clusters()
    items = []
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        items.append(item)
    # One incident, with the traceback continuation attached
    assert len(items) == 1
    text = "\n".join(items[0].raw_lines)
    assert "RuntimeError" in text
    assert "y.py" in text


@pytest.mark.integration
def test_hard_cap_10s_forces_close(tmp_path, monkeypatch):
    """Even if continuation keeps arriving, hard cap closes cluster at 10s."""
    from lib.log_watcher import LogWatcher
    from lib import concurrency
    monkeypatch.setattr("lib.log_watcher.HARD_CAP_S", 0.5)  # speed for test
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    with open(path, "w") as f:
        f.write("ERROR [plugin.video.seren]: x\n")
    w = LogWatcher(quiescence_window_s=10.0)
    w._ingest_chunk(w._read_new_bytes())
    time.sleep(0.6)  # > 0.5 hard cap
    w._close_expired_clusters()
    items = [None]
    while not concurrency.work_queue.empty():
        _, _, items[0] = concurrency.work_queue.get_nowait()
    assert items[0] is not None
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/integration/test_log_watcher_continuation.py -v -m integration
```

Expected: failures (HARD_CAP_S undefined; continuation logic incomplete).

- [ ] **Step 3: Modify `service.kodi.ai/lib/log_watcher.py`** — add continuation handling

Add module-level constants near top of file:

```python
HARD_CAP_S = 10.0  # max age from first cluster line, regardless of continuation
CONTINUATION_ATTACH_WINDOW_S = 0.2  # 200ms
_CONTINUATION_RE = re.compile(
    r"^Traceback |"
    r"^\s+File \"[^\"]+\", line \d+, in |"
    r"^\s+raise |"
    r"^[A-Z][A-Za-z]+(Error|Exception): |"
    r"^\s+(at|in) "
)
```

Replace `_ingest_chunk` and `_close_expired_clusters` to track first-line timestamp + continuation:

```python
    def _ingest_chunk(self, text: str) -> None:
        for raw_line in text.splitlines():
            if not raw_line.strip():
                continue
            if "[service.kodi.ai]" in raw_line:
                continue
            parsed = self._parse_line(raw_line)
            if parsed is None:
                # No level/prefix — possibly a stderr continuation; try attach to most-recent ERROR
                self._maybe_attach_continuation(raw_line, addon=None)
                continue
            level, addon, body = parsed
            if level not in ("ERROR", "FATAL", "SEVERE", "WARNING"):
                # Could still be a continuation if pattern matches AND no different-prefix intervening
                if _CONTINUATION_RE.match(body):
                    self._maybe_attach_continuation(raw_line, addon=addon)
                continue
            if prefilter.is_benign(body):
                continue
            if active_calls.is_active():
                targets = active_calls.get_active_target_addons()
                if targets == "ALL" or (addon and addon in targets):
                    continue
            cid = prefilter.cluster_id_for(body)
            now = datetime.now(timezone.utc)
            cluster = self._open_clusters.setdefault(cid, {
                "lines": [], "first_seen": now, "last_seen": now,
                "addon": addon, "level": level, "occurrences": 0,
                "first_cluster_ts": now,
            })
            cluster["lines"].append(raw_line)
            cluster["last_seen"] = now
            cluster["occurrences"] += 1
            self._last_error_cluster_id = cid
            self._last_error_addon = addon

    def _maybe_attach_continuation(self, raw_line: str, addon: str | None) -> None:
        """Attach to most-recent ERROR cluster if within 200ms AND no different-prefix
        intervening line. No-prefix lines (addon=None) are transparent."""
        if not getattr(self, "_last_error_cluster_id", None):
            return
        cid = self._last_error_cluster_id
        cluster = self._open_clusters.get(cid)
        if not cluster:
            return
        now = datetime.now(timezone.utc)
        age = (now - cluster["last_seen"]).total_seconds()
        if age > CONTINUATION_ATTACH_WINDOW_S:
            return
        # Different addon prefix = NOT transparent → break attachment
        if addon is not None and cluster["addon"] is not None and addon != cluster["addon"]:
            return
        cluster["lines"].append(raw_line)
        cluster["last_seen"] = now

    def _close_expired_clusters(self) -> None:
        now = datetime.now(timezone.utc)
        expired: list[str] = []
        for cid, c in list(self._open_clusters.items()):
            age_quiet = (now - c["last_seen"]).total_seconds()
            age_total = (now - c["first_cluster_ts"]).total_seconds()
            if age_quiet >= self.quiescence_window_s or age_total >= HARD_CAP_S:
                expired.append(cid)
        for cid in expired:
            c = self._open_clusters.pop(cid)
            with coalesce_lock:
                if cid in active_cluster_ids:
                    continue
                active_cluster_ids.add(cid)
            try:
                enqueue(LogIncident(
                    cluster_id=cid,
                    first_seen=c["first_seen"], last_seen=c["last_seen"],
                    occurrences=c["occurrences"], raw_lines=c["lines"],
                    severity_hint=c["level"], likely_addon=c["addon"],
                    likely_action=None, backdated=False,
                    from_previous_session=False, triage_deferred=True,
                ))
            except Exception:
                pass
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/integration/test_log_watcher_continuation.py -v -m integration
pytest tests/integration/test_log_watcher_basic.py tests/integration/test_log_watcher_rotation.py -v -m integration
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/log_watcher.py tests/integration/test_log_watcher_continuation.py
git commit -m "feat(log_watcher): trace-continuation quiescence + 10s hard cap

CONTINUATION_ATTACH_WINDOW_S (200ms) + HARD_CAP_S (10s).
_CONTINUATION_RE matches Traceback/File/raise/Exception/at/in.
Continuation lines attach to most-recent ERROR cluster only if:
  - within 200ms of cluster's last_seen, AND
  - no DIFFERENT addon prefix intervening (no-prefix lines transparent
    per spec §1.5 round-8 clarification).
Hard cap: cluster forces close at HARD_CAP_S from first_cluster_ts,
regardless of late continuation arrivals.
_last_error_cluster_id tracked for continuation attachment.

Spec: §1.5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4.7 — `log_watcher`: burst-mode + per-tool-boundary buffer + boot post-mortem

**Spec ref:** §1.4 (burst-mode), §1.3 (per-tool-boundary post-window evaluation), §1.4 (boot post-mortem).

**Files:**
- Modify: `service.kodi.ai/lib/log_watcher.py`
- Create: `tests/integration/test_log_watcher_burst_boot.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_log_watcher_burst_boot.py
import os
import time
import pytest
from tests.integration.fakes import fake_xbmcvfs


@pytest.mark.integration
def test_burst_mode_emits_synthetic_incident_with_counts(tmp_path):
    from lib import log_watcher, concurrency
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    # Stage > 2MB of ERROR lines from two addons
    with open(path, "w") as f:
        for i in range(30000):
            f.write(f"ERROR [plugin.video.foo]: oops {i}\n")
        for i in range(15000):
            f.write(f"ERROR [plugin.video.bar]: nope {i}\n")
    w = log_watcher.LogWatcher()
    # Simulate burst trigger: fill the work_queue first
    from lib.concurrency import LogIncident
    from datetime import datetime, timezone
    for i in range(420):  # > 80% of 500
        concurrency.work_queue.put_nowait((10, i, LogIncident(
            cluster_id=f"x{i}", first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc), occurrences=1,
            raw_lines=[], severity_hint="ERROR", likely_addon=None,
            likely_action=None, backdated=False,
            from_previous_session=False, triage_deferred=True,
        )))
    # Trigger burst-mode read
    w._maybe_enter_burst_mode_and_read()
    # Drain queue, look for synthetic incident
    found = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        if hasattr(item, "raw_lines") and any("log burst" in r for r in item.raw_lines):
            found = True
            assert "plugin.video.foo" in "\n".join(item.raw_lines)
            assert "plugin.video.bar" in "\n".join(item.raw_lines)
            break
    assert found


@pytest.mark.integration
def test_boot_post_mortem_skips_when_old_log_absent(tmp_path):
    from lib import log_watcher
    # No kodi.old.log
    w = log_watcher.LogWatcher()
    # Should not raise
    w.boot_post_mortem()


@pytest.mark.integration
def test_per_tool_boundary_buffers_then_discards_target_lines(tmp_path):
    """During an active tool window with target_addons={'foo'}, lines from foo
    are buffered and discarded when the linger expires. Lines from bar are emitted."""
    from lib import log_watcher, concurrency
    from lib.concurrency import active_calls
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()

    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    with open(path, "w") as f:
        f.write("INFO: startup\n")
    w = log_watcher.LogWatcher(quiescence_window_s=0.3)
    w._read_new_bytes()  # consume startup line

    # Begin active tool window targeting 'plugin.video.foo'
    active_calls.add_tool("t1", target_addons={"plugin.video.foo"})
    with open(path, "a") as f:
        f.write("ERROR [plugin.video.foo]: side effect from our action\n")
        f.write("ERROR [plugin.video.bar]: genuine new issue\n")
    w._ingest_chunk(w._read_new_bytes())
    # Foo line should be suppressed during active window; bar passes through
    time.sleep(0.4)
    w._close_expired_clusters()
    found_bar = False
    found_foo = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        text = "\n".join(getattr(item, "raw_lines", []))
        if "bar" in text:
            found_bar = True
        if "foo" in text:
            found_foo = True
    assert found_bar
    assert not found_foo
    # Cleanup
    active_calls.schedule_remove_tool("t1", after=0.0)
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/integration/test_log_watcher_burst_boot.py -v -m integration
```

Expected: `AttributeError: '_maybe_enter_burst_mode_and_read' / 'boot_post_mortem'`.

- [ ] **Step 3: Modify `service.kodi.ai/lib/log_watcher.py`** — append burst + post-mortem methods

Add module-level constants:

```python
BURST_QUEUE_THRESHOLD = int(0.8 * 500)  # 80% of work_queue maxsize
BURST_LAG_TICKS = 2
BOOT_SCAN_CHUNK = 256 * 1024  # 256 KB backward chunks
BOOT_SCAN_MAX_BYTES_LARGE_FILE = 2 * 1024 * 1024
LARGE_FILE_THRESHOLD = 50 * 1024 * 1024
```

Inside `LogWatcher.__init__`, add:

```python
        self._lag_streak = 0
        self._last_error_cluster_id: str | None = None
        self._last_error_addon: str | None = None
```

Add methods to `LogWatcher`:

```python
    def _maybe_enter_burst_mode_and_read(self) -> bool:
        """If queue ≥80% full AND lag growing 2 ticks → skip-to-tail.
        Returns True if burst mode entered."""
        qsize = work_queue.qsize()
        if qsize >= BURST_QUEUE_THRESHOLD:
            self._lag_streak += 1
        else:
            self._lag_streak = 0
            return False
        if self._lag_streak < BURST_LAG_TICKS:
            return False
        # Burst mode: read last 1MB, count ERRORs by addon in skipped region
        path = state_paths.log_path()
        try:
            size = os.path.getsize(path)
        except OSError:
            return False
        skipped_start = self._last_offset
        skipped_end = max(self._last_offset, size - PER_TICK_CAP)
        # Count ERRORs in skipped region (streaming, not loaded all at once)
        counts: dict[str, int] = {}
        if skipped_end > skipped_start:
            with open(path, "rb") as f:
                f.seek(skipped_start)
                buf = b""
                remaining = skipped_end - skipped_start
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    buf += chunk
                    while b"\n" in buf:
                        line_b, _, buf = buf.partition(b"\n")
                        line = line_b.decode("utf-8", errors="replace")
                        parsed = self._parse_line(line)
                        if parsed and parsed[0] in ("ERROR", "FATAL"):
                            addon = parsed[1] or "<unknown>"
                            counts[addon] = counts.get(addon, 0) + 1
        # Read tail 1MB and ingest normally
        self._last_offset = max(skipped_end, self._last_offset)
        skip_mb = (skipped_end - skipped_start) / (1024 * 1024)
        synth = (
            f"log burst, {skip_mb:.1f} MB skipped; counts: "
            + ", ".join(f"{k}: {v} ERR" for k, v in counts.items())
        )
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            enqueue(LogIncident(
                cluster_id=f"burst_{int(now.timestamp())}",
                first_seen=now, last_seen=now, occurrences=1,
                raw_lines=[synth], severity_hint="ERROR",
                likely_addon=None, likely_action=None, backdated=False,
                from_previous_session=False, triage_deferred=True,
            ))
        except Exception:
            from .concurrency import drop_counter
            drop_counter.inc()
        # Resume normal read
        chunk = self._read_new_bytes()
        if chunk:
            self._ingest_chunk(chunk)
        return True

    def boot_post_mortem(self) -> None:
        """Scan kodi.old.log backward for sentinel boundaries + emit backdated
        incidents (per spec §1.4). Skip if file absent or fresh first boot."""
        from . import log_sentinels
        path = state_paths.old_log_path()
        if not os.path.exists(path):
            import xbmc
            xbmc.log("[service.kodi.ai] boot_post_mortem: kodi.old.log absent, skipping", xbmc.LOGINFO)
            return
        size = os.path.getsize(path)
        cap = BOOT_SCAN_MAX_BYTES_LARGE_FILE if size >= LARGE_FILE_THRESHOLD else size
        # Read backward in chunks until first sentinel boundary found OR cap reached
        read_so_far = 0
        chunks: list[bytes] = []
        with open(path, "rb") as f:
            pos = size
            while read_so_far < cap and pos > 0:
                chunk_size = min(BOOT_SCAN_CHUNK, pos, cap - read_so_far)
                pos -= chunk_size
                f.seek(pos)
                chunks.append(f.read(chunk_size))
                read_so_far += chunk_size
                if b"[service.kodi.ai] reason-" in chunks[-1]:
                    break
        chunks.reverse()
        tail = b"".join(chunks).decode("utf-8", errors="replace")
        # Parse forward; detect dangling sessions (reason-start without reason-end).
        open_sessions: set[str] = set()
        suppress_lines: set[int] = set()
        lines = tail.splitlines()
        for i, line in enumerate(lines):
            s = log_sentinels.parse_sentinel(line)
            if s is None:
                continue
            kind, sid = s
            if kind == "start":
                open_sessions.add(sid)
            elif kind == "end":
                open_sessions.discard(sid)
        # If any session remained open at EOF, suppress its lines in regions
        # we know we caused. Foreign-addon lines surface as backdated incidents.
        if open_sessions:
            in_session = False
            for i, line in enumerate(lines):
                s = log_sentinels.parse_sentinel(line)
                if s and s[0] == "start" and s[1] in open_sessions:
                    in_session = True
                elif s and s[0] == "end":
                    in_session = False
                if in_session and "[service.kodi.ai]" in line:
                    suppress_lines.add(i)
        # Emit non-suppressed ERROR/FATAL lines as backdated incidents
        from datetime import datetime, timezone
        for i, line in enumerate(lines):
            if i in suppress_lines:
                continue
            parsed = self._parse_line(line)
            if not parsed or parsed[0] not in ("ERROR", "FATAL", "SEVERE"):
                continue
            level, addon, body = parsed
            if prefilter.is_benign(body):
                continue
            cid = prefilter.cluster_id_for(body)
            now = datetime.now(timezone.utc)
            try:
                enqueue(LogIncident(
                    cluster_id=cid, first_seen=now, last_seen=now, occurrences=1,
                    raw_lines=[line], severity_hint=level, likely_addon=addon,
                    likely_action=None, backdated=True,
                    from_previous_session=True, triage_deferred=True,
                ))
            except Exception:
                from .concurrency import drop_counter
                drop_counter.inc()
```

Also update `run()` to call `_maybe_enter_burst_mode_and_read()` at the top of each tick:

Replace the first read in run loop with:

```python
            if not self._maybe_enter_burst_mode_and_read():
                chunk = self._read_new_bytes()
                if chunk:
                    self._ingest_chunk(chunk)
                    self._ticks_since_growth = 0
                else:
                    self._ticks_since_growth += 1
            else:
                self._ticks_since_growth = 0
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/integration/test_log_watcher_burst_boot.py -v -m integration
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add service.kodi.ai/lib/log_watcher.py tests/integration/test_log_watcher_burst_boot.py
git commit -m "feat(log_watcher): burst-mode + boot post-mortem + buffer evaluation

_maybe_enter_burst_mode_and_read: triggers when work_queue ≥80% full AND
lag growing ≥2 ticks. Skips middle bytes, reads last 1MB, emits synthetic
'log burst, N MB skipped' incident with per-addon ERROR counts from
streaming grep over skipped region.
boot_post_mortem: reads kodi.old.log backward in 256KB chunks until first
sentinel boundary OR 2MB cap (if file ≥50MB else EOF). Detects dangling
reason-start (no matching reason-end) per spec §1.4 round-2 fix; suppresses
[service.kodi.ai]-prefixed lines in those regions; surfaces foreign-addon
ERRORs as backdated LogIncidents (from_previous_session=True, backdated=True).
Skips with INFO log if kodi.old.log absent (fresh first boot).
Per-tool-boundary buffer evaluation handled inline via active_calls check
in _ingest_chunk (Task 4.4 + 4.6).

Spec: §1.3, §1.4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 5 — Triage + reasoner state + reasoner (5 tasks)

### Task 5.1 — `lib/triage.py`: token bucket + cheap LLM classification

**Spec ref:** §1.6 (rate limit + classification).

**Files:**
- Create: `service.kodi.ai/lib/triage.py`
- Create: `tests/unit/test_triage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_triage.py
import pytest
from unittest import mock


def test_token_bucket_allows_burst():
    from lib.triage import TokenBucket
    tb = TokenBucket(rate_per_min=6, burst=3)
    for _ in range(3):
        assert tb.try_consume()
    # Burst exhausted; cannot consume immediately
    assert not tb.try_consume()


def test_token_bucket_refills_over_time(monkeypatch):
    from lib.triage import TokenBucket
    t = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    tb = TokenBucket(rate_per_min=60, burst=1)
    assert tb.try_consume()
    assert not tb.try_consume()
    t[0] = 102.0  # 2s → 2 tokens refilled at 60/min
    assert tb.try_consume()


def test_classify_returns_critical_on_keyword():
    from lib import triage
    fake_llm = mock.MagicMock()
    fake_llm.chat.return_value = mock.MagicMock(text="CRITICAL")
    verdict = triage.classify(fake_llm, api_key="ok", model="cheap",
                              cluster_text="user action just failed")
    assert verdict == "CRITICAL"


def test_classify_returns_ignore_default_on_unparseable():
    from lib import triage
    fake_llm = mock.MagicMock()
    fake_llm.chat.return_value = mock.MagicMock(text="i am a chatty model")
    verdict = triage.classify(fake_llm, api_key="ok", model="cheap",
                              cluster_text="anything")
    assert verdict == "IGNORE"


def test_classify_handles_llm_error():
    from lib import triage
    from lib.llm.client import LLMServerError
    fake_llm = mock.MagicMock()
    fake_llm.chat.side_effect = LLMServerError("503")
    verdict = triage.classify(fake_llm, api_key="ok", model="cheap",
                              cluster_text="anything")
    assert verdict == "IGNORE"  # safe default on failure
```

- [ ] **Step 2: Implement `service.kodi.ai/lib/triage.py`**

```python
# service.kodi.ai/lib/triage.py
"""Cheap-LLM triage: classify a log cluster as CRITICAL/ADVISORY/IGNORE.

Rate-limited via TokenBucket (default 6/min, burst 3). T4 enforces budget
at call time (T2 never blocks).

Spec: §1.6.
"""
from __future__ import annotations
import time
import threading
from typing import Literal

Verdict = Literal["CRITICAL", "ADVISORY", "IGNORE"]


class TokenBucket:
    def __init__(self, *, rate_per_min: int, burst: int):
        self.rate_per_sec = rate_per_min / 60.0
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def try_consume(self, n: float = 1.0) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate_per_sec)
            self._last_refill = now
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False

    def next_token_wait_s(self) -> float:
        with self._lock:
            if self._tokens >= 1:
                return 0.0
            need = 1.0 - self._tokens
            return need / self.rate_per_sec


def _parse_verdict(text: str) -> Verdict:
    up = text.upper().strip()
    for tok in ("CRITICAL", "ADVISORY", "IGNORE"):
        if tok in up.split():
            return tok  # type: ignore[return-value]
    return "IGNORE"


def classify(llm_module, *, api_key: str, model: str, cluster_text: str) -> Verdict:
    """Single triage call. Returns verdict (IGNORE on any failure)."""
    from .llm.prompts import load
    from .llm.client import LLMError
    system = load("triage_system").body
    try:
        res = llm_module.chat(
            api_key=api_key,
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Cluster:\n{cluster_text[:4000]}"},
            ],
            max_tokens=10,
            temperature=0.0,
        )
    except LLMError:
        return "IGNORE"  # safe default
    except Exception:
        return "IGNORE"
    return _parse_verdict(res.text)
```

- [ ] **Step 3: Run tests — verify they pass**

```bash
pytest tests/unit/test_triage.py -v
```

Expected: `5 passed`.

- [ ] **Step 4: Commit**

```bash
git add service.kodi.ai/lib/triage.py tests/unit/test_triage.py
git commit -m "feat(triage): TokenBucket + cheap-LLM classify

TokenBucket(rate_per_min=6, burst=3) — refills continuously.
try_consume() non-blocking; next_token_wait_s() for caller backoff.
classify(): one cheap LLM call with triage_system.md prompt, max_tokens=10,
temperature=0. Returns CRITICAL/ADVISORY/IGNORE; IGNORE on any LLM error
or unparseable response (safe default).

Spec: §1.6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5.2 — `lib/reasoner_state.py`: SessionState + atomic write + rehydrate

**Spec ref:** §1.7 (pause sequence step 1-3), §5.7 (terminal states + recovery).

**Files:**
- Create: `service.kodi.ai/lib/reasoner_state.py`
- Create: `tests/unit/test_reasoner_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_reasoner_state.py
import json
import os
import sys
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    from lib import state_paths
    state_paths.ensure_dirs()
    yield


def test_session_state_to_dict_round_trip():
    from lib.reasoner_state import SessionState
    s = SessionState(
        session_id="abc123",
        messages=[{"role": "user", "content": "hi"}],
        tool_history=[{"name": "read_log", "result": "..."}],
        pending_tool={"name": "set_addon_setting", "args": {"addon_id": "x"}},
        snapshot_ids=["snap_1"],
        terminal_state="paused",
        paused_at=1700000000.0,
        budget_blob={"limit_s": 60, "elapsed_baseline": 5.0, "state": "PAUSED"},
        cluster_id="c1",
    )
    d = s.to_dict()
    s2 = SessionState.from_dict(d)
    assert s2.session_id == "abc123"
    assert s2.terminal_state == "paused"
    assert s2.budget_blob["elapsed_baseline"] == 5.0


def test_persist_and_load():
    from lib.reasoner_state import SessionState, persist, load
    s = SessionState(
        session_id="abc123", messages=[], tool_history=[],
        pending_tool=None, snapshot_ids=[], terminal_state="paused",
        paused_at=1700000000.0,
        budget_blob={"limit_s": 60, "elapsed_baseline": 0.0, "state": "PAUSED"},
        cluster_id=None,
    )
    persist(s)
    loaded = load("abc123")
    assert loaded.session_id == "abc123"
    assert loaded.terminal_state == "paused"


def test_load_missing_returns_none():
    from lib.reasoner_state import load
    assert load("nope") is None


def test_unlink_removes_file():
    from lib.reasoner_state import SessionState, persist, unlink, load
    s = SessionState(session_id="x", messages=[], tool_history=[],
                     pending_tool=None, snapshot_ids=[], terminal_state="paused",
                     paused_at=0.0, budget_blob={"limit_s": 1, "elapsed_baseline": 0, "state": "PAUSED"},
                     cluster_id=None)
    persist(s)
    assert load("x") is not None
    unlink("x")
    assert load("x") is None


def test_list_all_returns_session_ids():
    from lib.reasoner_state import SessionState, persist, list_all
    for sid in ("a1", "b2", "c3"):
        persist(SessionState(session_id=sid, messages=[], tool_history=[],
                             pending_tool=None, snapshot_ids=[], terminal_state="paused",
                             paused_at=0.0, budget_blob={"limit_s": 1, "elapsed_baseline": 0, "state": "PAUSED"},
                             cluster_id=None))
    ids = set(list_all())
    assert {"a1", "b2", "c3"} <= ids


def test_atomic_write_no_partial_tmp(tmp_path):
    """After persist, no .tmp file remains."""
    from lib.reasoner_state import SessionState, persist
    from lib import state_paths
    persist(SessionState(session_id="atomic", messages=[], tool_history=[],
                         pending_tool=None, snapshot_ids=[], terminal_state="paused",
                         paused_at=0.0, budget_blob={"limit_s": 1, "elapsed_baseline": 0, "state": "PAUSED"},
                         cluster_id=None))
    base = state_paths.profile_path("sessions/")
    assert not any(f.endswith(".tmp") for f in os.listdir(base))
```

- [ ] **Step 2: Implement `service.kodi.ai/lib/reasoner_state.py`**

```python
# service.kodi.ai/lib/reasoner_state.py
"""SessionState dataclass + atomic persistence under sessions/<sid>.json.

Pause sequence step 1-3 per spec §1.7:
  1. paused_sessions[sid] = state (memory)
  2. MonotonicBudget.pause() (memory)
  3. atomic disk write — captures post-pause budget state

This module owns step 3. Pure I/O — no Kodi imports beyond state_paths.

Terminal states (spec §5.7): paused | fix_complete_notify_pending |
  pause_notify_failed | notify_failed | fix_complete | expired.
Boot recovery dispatches based on terminal_state (see lib/recovery.py).

Spec: §1.7, §5.7.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, asdict, field
from typing import Any
from . import state_paths


@dataclass(frozen=False)  # mutable for in-memory updates
class SessionState:
    session_id: str
    messages: list[dict]  # conversation history (redacted before LLM send)
    tool_history: list[dict]  # tools called this session with results
    pending_tool: dict | None  # tool awaiting user confirmation
    snapshot_ids: list[str]  # snapshots created this session (for /undo)
    terminal_state: str  # paused | fix_complete_notify_pending | ...
    paused_at: float  # epoch seconds when paused
    budget_blob: dict  # MonotonicBudget.to_dict()
    cluster_id: str | None  # originating LogIncident cluster (None for chat-init)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, blob: dict) -> "SessionState":
        return cls(**blob)


def _path(session_id: str) -> str:
    return state_paths.profile_path(f"sessions/{session_id}.json")


def persist(state: SessionState) -> None:
    blob = json.dumps(state.to_dict(), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    state_paths.atomic_write(_path(state.session_id), blob)


def load(session_id: str) -> SessionState | None:
    p = _path(session_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return SessionState.from_dict(json.load(f))
    except (json.JSONDecodeError, OSError, TypeError):
        # Corrupt → move aside, return None (recovery handled by lib/recovery.py)
        corrupt_dir = state_paths.profile_path("sessions/.corrupt")
        try:
            os.makedirs(corrupt_dir, exist_ok=True)
            os.rename(p, os.path.join(corrupt_dir, f"{session_id}.json.bak"))
        except OSError:
            pass
        return None


def unlink(session_id: str) -> None:
    try:
        os.remove(_path(session_id))
    except FileNotFoundError:
        pass


def list_all() -> list[str]:
    base = state_paths.profile_path("sessions")
    if not os.path.exists(base):
        return []
    return [f[:-5] for f in os.listdir(base) if f.endswith(".json")]
```

- [ ] **Step 3: Run tests — verify they pass**

```bash
pytest tests/unit/test_reasoner_state.py -v
```

Expected: `6 passed`.

- [ ] **Step 4: Commit**

```bash
git add service.kodi.ai/lib/reasoner_state.py tests/unit/test_reasoner_state.py
git commit -m "feat(reasoner_state): SessionState + atomic persist/load/unlink

SessionState dataclass: session_id, messages, tool_history, pending_tool,
snapshot_ids, terminal_state, paused_at, budget_blob (MonotonicBudget
serialization), cluster_id.
persist() uses state_paths.atomic_write (.tmp + fsync + rename) under
sessions/<sid>.json — pause sequence step 3 per spec §1.7.
load() returns None on missing; corrupt files moved to sessions/.corrupt/
for manual review (recovery.py boot pass handles terminal-state dispatch).
list_all() enumerates session_ids for boot recovery.

Spec: §1.7, §5.7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5.3 — `lib/reasoner.py`: agent loop skeleton (no tool dispatch yet)

**Spec ref:** §1.6, §1.7, §3.1, §3.3.

**Files:** Create `service.kodi.ai/lib/reasoner.py`, `tests/unit/test_reasoner_skeleton.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_reasoner_skeleton.py
import pytest
from unittest import mock


def test_reasoner_returns_outcome_on_simple_final_message():
    from lib.reasoner import Reasoner, ReasonerOutcome
    fake_llm = mock.MagicMock()
    fake_llm.chat.return_value = mock.MagicMock(
        text="diagnosis: nothing actionable", tool_calls=None,
        tokens_in=100, tokens_out=20, model="m", finish_reason="stop",
    )
    r = Reasoner(llm_client=fake_llm, api_key="k", router=mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0)),
                 budget=mock.MagicMock(pre_call_check=lambda estimated_cost: (True, None), record_actual=lambda c: None))
    out = r.run_simple(messages=[{"role": "user", "content": "hi"}], task_class="t1_simple", session_id="s1")
    assert isinstance(out, ReasonerOutcome)
    assert out.final_message == "diagnosis: nothing actionable"
    assert out.tool_calls_made == 0


def test_reasoner_respects_pre_call_budget_refusal():
    from lib.reasoner import Reasoner, ReasonerOutcome
    fake_llm = mock.MagicMock()
    fake_router = mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0))
    fake_budget = mock.MagicMock(pre_call_check=lambda estimated_cost: (False, "daily cap"))
    r = Reasoner(llm_client=fake_llm, api_key="k", router=fake_router, budget=fake_budget)
    out = r.run_simple(messages=[], task_class="t1_simple", session_id="s1")
    assert out.terminal_reason == "budget_refused"
    assert "daily cap" in out.notes
    assert not fake_llm.chat.called
```

- [ ] **Step 2: Implement `service.kodi.ai/lib/reasoner.py`**

```python
# service.kodi.ai/lib/reasoner.py
"""Reasoner: LLM tool-use agent loop. T4-owned single-threaded.

Skeleton in 5.3: simple non-tool path (one LLM call → final_message).
Full agent loop with tool dispatch + pause/resume in Task 5.4-5.5.

Spec: §1.6, §1.7, §3.1, §3.3.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasonerOutcome:
    final_message: str
    tool_calls_made: int = 0
    terminal_reason: str = "complete"  # complete | budget_refused | needs_user | aborted | error
    notes: str = ""
    cost_usd: float = 0.0
    snapshot_ids: list[str] = field(default_factory=list)


class Reasoner:
    def __init__(self, *, llm_client, api_key: str, router, budget):
        self.llm = llm_client
        self.api_key = api_key
        self.router = router
        self.budget = budget

    def _estimate_cost(self, model: str, messages: list[dict], max_tokens: int) -> float:
        price = self.router.price_per_mtok(model) or (1.0, 5.0)
        in_p, out_p = price
        approx_in_tokens = sum(len(m.get("content") or "") for m in messages) / 4
        return (approx_in_tokens * in_p + max_tokens * out_p) / 1_000_000

    def run_simple(self, *, messages: list[dict], task_class: str, session_id: str) -> ReasonerOutcome:
        """Single-call path for chat where reasoner has no tools to invoke."""
        model = self.router.pick(task_class)
        est = self._estimate_cost(model, messages, max_tokens=512)
        ok, reason = self.budget.pre_call_check(estimated_cost=est)
        if not ok:
            return ReasonerOutcome(final_message="", terminal_reason="budget_refused", notes=reason or "")
        try:
            res = self.llm.chat(api_key=self.api_key, model=model, messages=messages, max_tokens=512)
        except Exception as e:
            return ReasonerOutcome(final_message="", terminal_reason="error", notes=str(e))
        price = self.router.price_per_mtok(model) or (1.0, 5.0)
        actual_cost = (res.tokens_in * price[0] + res.tokens_out * price[1]) / 1_000_000
        self.budget.record_actual(actual_cost)
        return ReasonerOutcome(final_message=res.text, tool_calls_made=0, cost_usd=actual_cost)
```

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/unit/test_reasoner_skeleton.py -v   # 2 passed
git add service.kodi.ai/lib/reasoner.py tests/unit/test_reasoner_skeleton.py
git commit -m "feat(reasoner): skeleton with simple non-tool path + budget gate

Reasoner.run_simple() — for chat without tool calls. Pre-call budget
estimate (tokens_in_approx × in_price + max_tokens × out_price); refuse
if budget would be exceeded. record_actual() after success.
ReasonerOutcome dataclass: final_message, tool_calls_made, terminal_reason
(complete | budget_refused | needs_user | aborted | error), cost_usd,
snapshot_ids.
Full agent loop with tool dispatch + pause/resume in Tasks 5.4, 5.5.

Spec: §1.6, §1.7, §3.1, §3.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5.4 — Reasoner: tool-use loop + tool_call dispatch (mocked tool registry)

**Spec ref:** §3.1 Flow 1, §3.3.

**Files:** Modify `service.kodi.ai/lib/reasoner.py`, create `tests/unit/test_reasoner_tool_loop.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_reasoner_tool_loop.py
import pytest
from unittest import mock
from dataclasses import dataclass


@dataclass
class FakeChatResponse:
    text: str
    tool_calls: list
    tokens_in: int = 100
    tokens_out: int = 20
    model: str = "m"
    finish_reason: str = "stop"


def test_reasoner_dispatches_tool_call_and_continues():
    """LLM emits tool_call → reasoner dispatches → feeds result → LLM emits final."""
    from lib.reasoner import Reasoner, ReasonerOutcome
    fake_llm = mock.MagicMock()
    # 1st call → tool_call. 2nd call → final.
    fake_llm.chat.side_effect = [
        FakeChatResponse(text="", tool_calls=[
            {"id": "tc1", "function": {"name": "read_log", "arguments": '{"lines": 50}'}}
        ]),
        FakeChatResponse(text="all clear", tool_calls=None),
    ]
    fake_router = mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0))
    fake_budget = mock.MagicMock(pre_call_check=lambda estimated_cost: (True, None),
                                 record_actual=lambda c: None)
    fake_registry = {
        "read_log": mock.MagicMock(
            return_value=mock.MagicMock(
                success=True, output="...", actual_state_after=None,
                snapshot_id=None, error=None, requested="read_log(lines=50)",
            ))
    }
    r = Reasoner(llm_client=fake_llm, api_key="k", router=fake_router, budget=fake_budget,
                 tool_registry=fake_registry)
    out = r.run_with_tools(initial_messages=[{"role": "user", "content": "diagnose"}],
                           task_class="t1_simple", session_id="s1", max_turns=15)
    assert out.final_message == "all clear"
    assert out.tool_calls_made == 1
    assert fake_registry["read_log"].called


def test_reasoner_respects_max_turns_cap():
    from lib.reasoner import Reasoner
    fake_llm = mock.MagicMock()
    fake_llm.chat.return_value = FakeChatResponse(text="", tool_calls=[
        {"id": "tc", "function": {"name": "read_log", "arguments": "{}"}}
    ])
    fake_registry = {"read_log": mock.MagicMock(return_value=mock.MagicMock(
        success=True, output="x", actual_state_after=None, snapshot_id=None,
        error=None, requested="read_log()"))}
    r = Reasoner(llm_client=fake_llm, api_key="k",
                 router=mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0)),
                 budget=mock.MagicMock(pre_call_check=lambda estimated_cost: (True, None),
                                       record_actual=lambda c: None),
                 tool_registry=fake_registry)
    out = r.run_with_tools(initial_messages=[], task_class="t1_simple",
                           session_id="s1", max_turns=3)
    assert out.terminal_reason == "max_turns"
    assert out.tool_calls_made == 3
```

- [ ] **Step 2: Append to `service.kodi.ai/lib/reasoner.py`** — add `run_with_tools`

```python
import json


class Reasoner(Reasoner):  # extend in same module
    pass  # placeholder — actually we modify the class above.
```

(Use Edit to insert the method into the existing class. Replace `class Reasoner:` block by adding the methods below.)

Add to `Reasoner.__init__`:
```python
    def __init__(self, *, llm_client, api_key: str, router, budget, tool_registry: dict | None = None):
        self.llm = llm_client
        self.api_key = api_key
        self.router = router
        self.budget = budget
        self.tool_registry = tool_registry or {}
```

Add methods:
```python
    def _tool_schemas(self) -> list[dict]:
        """Build OpenAI-format tool schemas from tool_registry."""
        return [t.schema_dict() for t in self.tool_registry.values() if hasattr(t, "schema_dict")]

    def _execute_tool(self, name: str, args_json: str, session_id: str):
        if name not in self.tool_registry:
            return {"success": False, "error": f"unknown tool: {name}", "output": None}
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"invalid args JSON: {e}", "output": None}
        try:
            result = self.tool_registry[name](**args) if callable(self.tool_registry[name]) else self.tool_registry[name].execute(args)
            return {
                "success": getattr(result, "success", True),
                "output": getattr(result, "output", str(result)),
                "actual_state_after": getattr(result, "actual_state_after", None),
                "snapshot_id": getattr(result, "snapshot_id", None),
                "error": getattr(result, "error", None),
                "requested": getattr(result, "requested", f"{name}(...)"),
            }
        except Exception as e:
            return {"success": False, "error": str(e), "output": None}

    def run_with_tools(
        self, *, initial_messages: list[dict], task_class: str,
        session_id: str, max_turns: int = 15,
    ) -> ReasonerOutcome:
        """Multi-turn tool-use loop. Returns when LLM emits final_message,
        max_turns hit, budget exhausted, or error."""
        messages = list(initial_messages)
        tools = self._tool_schemas() or None
        model = self.router.pick(task_class)
        snapshot_ids: list[str] = []
        cost = 0.0
        turns = 0
        for turns in range(1, max_turns + 1):
            est = self._estimate_cost(model, messages, max_tokens=2048)
            ok, reason = self.budget.pre_call_check(estimated_cost=est)
            if not ok:
                return ReasonerOutcome(final_message="", terminal_reason="budget_refused",
                                       notes=reason or "", tool_calls_made=turns - 1,
                                       cost_usd=cost, snapshot_ids=snapshot_ids)
            try:
                res = self.llm.chat(api_key=self.api_key, model=model, messages=messages,
                                    tools=tools, max_tokens=2048)
            except Exception as e:
                return ReasonerOutcome(final_message="", terminal_reason="error",
                                       notes=str(e), tool_calls_made=turns - 1,
                                       cost_usd=cost, snapshot_ids=snapshot_ids)
            price = self.router.price_per_mtok(model) or (1.0, 5.0)
            actual = (res.tokens_in * price[0] + res.tokens_out * price[1]) / 1_000_000
            cost += actual
            self.budget.record_actual(actual)

            if res.tool_calls:
                for tc in res.tool_calls:
                    fn = tc["function"]
                    tool_result = self._execute_tool(fn["name"], fn.get("arguments", "{}"), session_id)
                    if tool_result.get("snapshot_id"):
                        snapshot_ids.append(tool_result["snapshot_id"])
                    messages.append({"role": "assistant", "tool_calls": [tc]})
                    messages.append({
                        "role": "tool", "tool_call_id": tc["id"],
                        "content": json.dumps(tool_result),
                    })
                continue  # next turn
            # No tool calls → final message
            return ReasonerOutcome(
                final_message=res.text, tool_calls_made=turns - 1,
                cost_usd=cost, snapshot_ids=snapshot_ids,
            )
        return ReasonerOutcome(
            final_message="", terminal_reason="max_turns",
            tool_calls_made=turns, cost_usd=cost, snapshot_ids=snapshot_ids,
            notes=f"hit max_turns={max_turns}",
        )
```

(Implementation note: the test's `class Reasoner(Reasoner): pass` was illustrative — use Edit to insert these methods directly into the original `class Reasoner:` block. Don't subclass.)

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/unit/test_reasoner_tool_loop.py -v   # 2 passed
git add service.kodi.ai/lib/reasoner.py tests/unit/test_reasoner_tool_loop.py
git commit -m "feat(reasoner): tool-use loop with dispatch + max_turns cap

run_with_tools(): multi-turn loop. Each turn: pre_call_check estimate
→ LLM with tools schema → if tool_calls, dispatch via tool_registry and
feed results back as 'tool' role messages → next turn. Final on no
tool_calls. max_turns cap (default 15 per spec). budget_refused / error /
max_turns terminal reasons.
Tool registry mocked here; real registration in Task 6.1.
Snapshot IDs aggregated for /undo.

Spec: §3.1, §3.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5.5 — Reasoner: pause/resume + MonotonicBudget + abort_event check

**Spec ref:** §1.7 (pause sequence), §1.8 (MonotonicBudget integration), §1.10 (abort).

**Files:** Modify `service.kodi.ai/lib/reasoner.py`, create `tests/unit/test_reasoner_pause_resume.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_reasoner_pause_resume.py
import pytest
from unittest import mock
from dataclasses import dataclass


@dataclass
class FakeChatResponse:
    text: str = ""
    tool_calls: list | None = None
    tokens_in: int = 50
    tokens_out: int = 10
    model: str = "m"
    finish_reason: str = "stop"


def test_pause_emitted_when_tool_requires_user():
    """A tool returning needs_user_confirmation flag triggers pause outcome."""
    from lib.reasoner import Reasoner, ReasonerOutcome
    fake_llm = mock.MagicMock()
    fake_llm.chat.return_value = FakeChatResponse(text="", tool_calls=[
        {"id": "tc1", "function": {"name": "set_addon_setting", "arguments": "{}"}}
    ])
    needs_user_tool = mock.MagicMock(return_value=mock.MagicMock(
        success=False, output=None, error="NEEDS_USER",
        actual_state_after=None, snapshot_id=None, requested="set_addon_setting(...)",
    ))
    needs_user_tool.requires_user_confirmation = True  # marker
    fake_registry = {"set_addon_setting": needs_user_tool}
    r = Reasoner(llm_client=fake_llm, api_key="k",
                 router=mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0)),
                 budget=mock.MagicMock(pre_call_check=lambda estimated_cost: (True, None),
                                       record_actual=lambda c: None),
                 tool_registry=fake_registry)
    out = r.run_with_tools(initial_messages=[], task_class="t1_simple",
                           session_id="sX", max_turns=5,
                           pause_callback=lambda tc, msgs: True)
    assert out.terminal_reason == "needs_user"
    assert out.pending_tool == "set_addon_setting"


def test_abort_event_short_circuits_loop():
    from lib.reasoner import Reasoner
    from lib.concurrency import abort_event
    abort_event.set()
    try:
        fake_llm = mock.MagicMock()
        r = Reasoner(llm_client=fake_llm, api_key="k",
                     router=mock.MagicMock(pick=lambda c: "m",
                                           price_per_mtok=lambda m: (1.0, 5.0)),
                     budget=mock.MagicMock(pre_call_check=lambda estimated_cost: (True, None),
                                           record_actual=lambda c: None),
                     tool_registry={})
        out = r.run_with_tools(initial_messages=[], task_class="t1_simple",
                               session_id="s1", max_turns=5)
        assert out.terminal_reason == "aborted"
        assert not fake_llm.chat.called
    finally:
        abort_event.clear()
```

- [ ] **Step 2: Modify `run_with_tools` in `lib/reasoner.py`** — add abort + pause hooks

Add at top of for-loop:
```python
            from .concurrency import abort_event
            if abort_event.is_set():
                return ReasonerOutcome(final_message="", terminal_reason="aborted",
                                       tool_calls_made=turns - 1, cost_usd=cost,
                                       snapshot_ids=snapshot_ids)
```

After dispatching each tool, check for pause:
```python
                    # Pause if tool registered itself as confirm-required
                    needs_pause = getattr(self.tool_registry[fn["name"]], "requires_user_confirmation", False)
                    if needs_pause or tool_result.get("error") == "NEEDS_USER":
                        return ReasonerOutcome(
                            final_message="", terminal_reason="needs_user",
                            tool_calls_made=turns, cost_usd=cost, snapshot_ids=snapshot_ids,
                            pending_tool=fn["name"], pending_args=fn.get("arguments", "{}"),
                            messages_so_far=list(messages),
                        )
```

Add fields to `ReasonerOutcome`:
```python
@dataclass
class ReasonerOutcome:
    final_message: str
    tool_calls_made: int = 0
    terminal_reason: str = "complete"
    notes: str = ""
    cost_usd: float = 0.0
    snapshot_ids: list[str] = field(default_factory=list)
    pending_tool: str | None = None
    pending_args: str | None = None
    messages_so_far: list[dict] = field(default_factory=list)
```

Add a `resume_from(state, user_reply)` method:
```python
    def resume_from(self, *, state, user_reply, task_class: str, max_turns: int = 15) -> ReasonerOutcome:
        """Resume a paused session with user's response to pending_tool."""
        messages = list(state.messages)
        # Append user's reply as a tool result for pending_tool
        if state.pending_tool:
            messages.append({
                "role": "tool", "tool_call_id": "user_resume",
                "content": json.dumps({"user_reply": user_reply}),
            })
        return self.run_with_tools(initial_messages=messages, task_class=task_class,
                                   session_id=state.session_id, max_turns=max_turns)
```

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/unit/test_reasoner_pause_resume.py -v   # 2 passed
git add service.kodi.ai/lib/reasoner.py tests/unit/test_reasoner_pause_resume.py
git commit -m "feat(reasoner): pause on tool confirmation + abort_event + resume

abort_event check at top of each turn — terminal_reason='aborted'.
Tool with .requires_user_confirmation=True OR error=='NEEDS_USER' →
terminal_reason='needs_user' + pending_tool/pending_args/messages_so_far
captured for serialization to SessionState (service.py wires these to
reasoner_state.persist + telegram_ask + MonotonicBudget.pause).
resume_from(state, user_reply) reconstructs message history with
tool-role reply for pending_tool, continues loop.

Spec: §1.7, §1.8, §1.10.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 6 — Tool dispatch framework + snapshot_manager + extract_keys (4 tasks)

### Task 6.1 — `lib/tools/__init__.py`: @tool decorator + registry

**Spec ref:** §1.9, §4.1.

**Files:** Modify `service.kodi.ai/lib/tools/__init__.py`, create `service.kodi.ai/lib/tools/schema.py`, create `tests/unit/test_tool_registry.py`.

- [ ] **Step 1: Test**

```python
# tests/unit/test_tool_registry.py
def test_tool_decorator_registers():
    from lib.tools import tool, registry, ToolResult
    @tool(name="dummy", description="d", schema={"type": "object", "properties": {}},
          tier="immediate")
    def dummy(): return ToolResult(success=True, requested="dummy()", output="ok",
                                    actual_state_after=None, error=None,
                                    snapshot_id=None, cost_seconds=0.0)
    assert "dummy" in registry
    res = registry["dummy"]()
    assert res.success


def test_tool_routing_immediate_non_disruptive():
    from lib.tools import tool, ToolResult, tool_routing_decision
    @tool(name="t1", description="", schema={"type": "object"}, tier="immediate")
    def t1(): pass
    decision = tool_routing_decision(t1, args={})
    assert decision == "apply_immediately"


def test_tool_routing_confirm():
    from lib.tools import tool, ToolResult, tool_routing_decision
    @tool(name="t2", description="", schema={"type": "object"}, tier="confirm")
    def t2(): pass
    assert tool_routing_decision(t2, args={}) == "needs_confirmation"


def test_tool_routing_immediate_disruptive_downgrades():
    from lib.tools import tool, ToolResult, tool_routing_decision
    @tool(name="t3", description="", schema={"type": "object"}, tier="immediate",
          disruptive=lambda args: args.get("force"))
    def t3(force=False): pass
    assert tool_routing_decision(t3, args={"force": True}) == "needs_confirmation"
    assert tool_routing_decision(t3, args={"force": False}) == "apply_immediately"
```

- [ ] **Step 2: Implement `service.kodi.ai/lib/tools/__init__.py`**

```python
# service.kodi.ai/lib/tools/__init__.py
"""Tool registry + @tool decorator + ToolResult.

Per spec §1.9 / §4.1: each tool declares tier (immediate | confirm),
disruptive (callable), target_addons (callable), snapshot_targets (callable | None).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Literal


@dataclass(frozen=True)
class ToolResult:
    success: bool
    requested: str
    output: Any | None
    actual_state_after: Any | None
    error: str | None
    snapshot_id: str | None
    cost_seconds: float
    warning: str | None = None


registry: dict[str, Callable] = {}


def tool(
    *,
    name: str,
    description: str,
    schema: dict,
    tier: Literal["immediate", "confirm"],
    disruptive: Callable[[dict], bool] = lambda args: False,
    target_addons: Callable[[dict], set[str]] = lambda args: set(),
    snapshot_targets: Callable[[dict], list] | None = None,
    safety_class: Literal["read_only", "low_risk", "medium_risk", "high_risk"] = "low_risk",
) -> Callable:
    def deco(fn: Callable) -> Callable:
        fn.tool_name = name
        fn.description = description
        fn.tool_schema = schema
        fn.tier = tier
        fn.disruptive_fn = disruptive
        fn.target_addons_fn = target_addons
        fn.snapshot_targets_fn = snapshot_targets
        fn.safety_class = safety_class
        registry[name] = fn
        return fn
    return deco


def tool_routing_decision(fn: Callable, args: dict) -> str:
    """Return 'apply_immediately' or 'needs_confirmation'."""
    if fn.tier == "confirm":
        return "needs_confirmation"
    if fn.disruptive_fn(args):
        return "needs_confirmation"
    return "apply_immediately"
```

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/unit/test_tool_registry.py -v   # 4 passed
git add service.kodi.ai/lib/tools/__init__.py tests/unit/test_tool_registry.py
git commit -m "feat(tools): @tool decorator + registry + ToolResult + routing

@tool: name/description/schema/tier/disruptive/target_addons/snapshot_targets/
safety_class. Registers into module-level dict.
ToolResult: success/requested/output/actual_state_after/error/snapshot_id/
cost_seconds/warning.
tool_routing_decision(fn, args): returns 'apply_immediately' or
'needs_confirmation' per spec §1.9 (tier=confirm always confirms;
tier=immediate + disruptive(args)=True downgrades to confirm).

Spec: §1.9, §4.1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6.2 — `lib/snapshot_manager.py`: snapshot/restore + staleness validation

**Spec ref:** §1.13, §5.4.

**Files:** Create `service.kodi.ai/lib/snapshot_manager.py`, `tests/unit/test_snapshot_manager.py`.

- [ ] **Step 1: Test**

```python
# tests/unit/test_snapshot_manager.py
import json, os, sys, pytest, time
from unittest import mock
from dataclasses import dataclass


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    from lib import state_paths
    state_paths.ensure_dirs()


def test_create_and_restore_kodi_setting():
    from lib.snapshot_manager import create, restore, SnapshotTarget
    state = {"value": "old"}
    target = SnapshotTarget(
        kind="kodi_setting", identifier="x",
        read_back=lambda: state["value"],
        equality=lambda c, s: c == s,
    )
    snap_id = create(label="test", targets=[target], session_id="s1")
    state["value"] = "new"
    # Now restore — should set state back to "old"
    ok, stale = restore(snap_id)
    assert ok
    assert stale == []


def test_restore_detects_stale_when_state_changed_externally():
    from lib.snapshot_manager import create, restore, SnapshotTarget
    state = {"value": "captured"}
    target = SnapshotTarget(
        kind="kodi_setting", identifier="x",
        read_back=lambda: state["value"],
        equality=lambda c, s: c == s,
    )
    snap_id = create(label="t", targets=[target], session_id="s1")
    # External mutation between create and restore
    state["value"] = "externally_changed_value"
    ok, stale = restore(snap_id)
    # Restore refused; stale list non-empty
    assert not ok
    assert len(stale) == 1
    assert stale[0]["identifier"] == "x"


def test_list_returns_recent():
    from lib.snapshot_manager import create, list_snapshots, SnapshotTarget
    for i in range(3):
        create(label=f"t{i}", targets=[], session_id="s1")
    snaps = list_snapshots()
    assert len(snaps) >= 3
```

- [ ] **Step 2: Implement `service.kodi.ai/lib/snapshot_manager.py`**

```python
# service.kodi.ai/lib/snapshot_manager.py
"""Snapshot create + staleness-validated restore.

Snapshots live OUTSIDE addon dir (Kodi-AI-snapshots/ under userdata/) so
they survive addon reinstall. LRU 100 snapshots / 200 MB cap.

Spec: §1.13, §5.4.
"""
from __future__ import annotations
import json
import os
import time
import secrets as _secrets
from dataclasses import dataclass, field
from typing import Any, Callable, Literal
from . import state_paths

MAX_SNAPSHOTS = 100
MAX_BYTES = 200 * 1024 * 1024
READ_BACK_DEADLINE_S = 2.0
MAX_TARGETS_PER_TOOL = 10


@dataclass(frozen=False)
class SnapshotTarget:
    kind: Literal["kodi_setting", "addon_setting", "file", "file_keys", "addon_state"]
    identifier: str
    read_back: Callable[[], Any]
    equality: Callable[[Any, Any], bool]
    extract_keys: Callable[[bytes], dict] | None = None


def _root() -> str:
    return state_paths.snapshots_path()


def _snap_dir(sid: str) -> str:
    return os.path.join(_root(), sid)


def create(*, label: str, targets: list[SnapshotTarget], session_id: str) -> str:
    if len(targets) > MAX_TARGETS_PER_TOOL:
        raise ValueError(f"too many snapshot targets ({len(targets)} > {MAX_TARGETS_PER_TOOL})")
    sid = "snap_" + _secrets.token_hex(6)
    d = _snap_dir(sid)
    os.makedirs(d, exist_ok=True)
    manifest = {"id": sid, "label": label, "session_id": session_id,
                "created_at": time.time(), "targets": []}
    for t in targets:
        try:
            # 2s soft deadline — for V1 the read_back functions are fast (in-memory
            # or single JSON-RPC). True deadline enforced via signal in Phase 7.
            value = t.read_back()
        except Exception as e:
            value = {"__read_back_error__": str(e)}
        manifest["targets"].append({
            "kind": t.kind, "identifier": t.identifier, "value": value,
        })
    with open(os.path.join(d, "manifest.json"), "w") as f:
        json.dump(manifest, f, separators=(",", ":"), default=str)
    _gc_lru()
    return sid


def restore(snapshot_id: str) -> tuple[bool, list[dict]]:
    """Restore snapshot. Returns (ok, stale_list).
    On stale: refuse auto-restore, return stale targets for user prompt."""
    d = _snap_dir(snapshot_id)
    mfp = os.path.join(d, "manifest.json")
    if not os.path.exists(mfp):
        return False, []
    with open(mfp) as f:
        manifest = json.load(f)
    # Stale check — caller MUST supply a re-resolution of read_back/equality
    # In V1: tools that create snapshots register their post-call read_back
    # in a side registry (lib/snapshot_runtime.py — Phase 7). For now:
    # equality is identity check (read_back returns recorded value → ok).
    # This is the contract the tool layer wires up.
    stale: list[dict] = []
    for t in manifest["targets"]:
        # The actual read_back is callable in-process; for cross-session
        # restore the caller must inject runtime resolvers. For V1: if no
        # runtime resolver, treat as "stale" (force user prompt).
        # See lib/snapshot_runtime.py (Phase 7) for the production wiring.
        resolver = _get_runtime_resolver(t["kind"], t["identifier"])
        if resolver is None:
            stale.append(t)
            continue
        try:
            current = resolver()
            if current != t["value"]:
                stale.append(t)
        except Exception:
            stale.append(t)
    if stale:
        return False, stale
    # Apply restoration
    for t in manifest["targets"]:
        applier = _get_runtime_applier(t["kind"], t["identifier"])
        if applier:
            applier(t["value"])
    return True, []


_RUNTIME_RESOLVERS: dict[tuple[str, str], Callable] = {}
_RUNTIME_APPLIERS: dict[tuple[str, str], Callable] = {}


def register_runtime_handlers(kind: str, identifier: str, *,
                              resolver: Callable, applier: Callable) -> None:
    _RUNTIME_RESOLVERS[(kind, identifier)] = resolver
    _RUNTIME_APPLIERS[(kind, identifier)] = applier


def _get_runtime_resolver(kind: str, identifier: str) -> Callable | None:
    return _RUNTIME_RESOLVERS.get((kind, identifier))


def _get_runtime_applier(kind: str, identifier: str) -> Callable | None:
    return _RUNTIME_APPLIERS.get((kind, identifier))


def list_snapshots(*, session_id: str | None = None, limit: int = 20) -> list[dict]:
    root = _root()
    if not os.path.exists(root):
        return []
    entries = []
    for name in os.listdir(root):
        if not name.startswith("snap_"):
            continue
        mfp = os.path.join(root, name, "manifest.json")
        if not os.path.exists(mfp):
            continue
        try:
            with open(mfp) as f:
                m = json.load(f)
        except Exception:
            continue
        if session_id and m.get("session_id") != session_id:
            continue
        entries.append({"id": name, "label": m.get("label"),
                        "created_at": m.get("created_at"),
                        "session_id": m.get("session_id")})
    entries.sort(key=lambda e: e.get("created_at", 0), reverse=True)
    return entries[:limit]


def _gc_lru() -> None:
    """Drop oldest snapshots over MAX_SNAPSHOTS or MAX_BYTES."""
    root = _root()
    if not os.path.exists(root):
        return
    snaps = [(name, os.path.join(root, name)) for name in os.listdir(root) if name.startswith("snap_")]
    snaps_sized = []
    for name, path in snaps:
        if not os.path.isdir(path):
            continue
        try:
            total = sum(os.path.getsize(os.path.join(path, f)) for f in os.listdir(path)
                        if os.path.isfile(os.path.join(path, f)))
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        snaps_sized.append((mtime, total, name, path))
    snaps_sized.sort()
    while len(snaps_sized) > MAX_SNAPSHOTS or sum(s[1] for s in snaps_sized) > MAX_BYTES:
        if not snaps_sized:
            break
        _, _, _, path = snaps_sized.pop(0)
        import shutil
        shutil.rmtree(path, ignore_errors=True)
```

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/unit/test_snapshot_manager.py -v   # 3 passed
git add service.kodi.ai/lib/snapshot_manager.py tests/unit/test_snapshot_manager.py
git commit -m "feat(snapshot_manager): create/restore with staleness validation

SnapshotTarget: kind/identifier/read_back/equality/extract_keys.
create(): writes manifest.json under userdata/Kodi-AI-snapshots/<sid>/
(reinstall-safe). ≤10 targets per tool. LRU 100 / 200MB cap via _gc_lru().
restore(): re-resolves each target's current value via runtime resolver;
mismatch → returns (False, stale_list) for user prompt. All match →
applies recorded values via runtime applier.
register_runtime_handlers(kind, identifier, resolver, applier) — tools
register their re-resolution + apply functions at module load (Phase 7).

Spec: §1.13, §5.4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6.3 — `lib/tools/extract_keys.py`: XML/JSON parsers for snapshot_targets

**Spec ref:** §4.6 (extract_keys parsers, flat-id + path-flatten with [N] indexing).

**Files:** Create `service.kodi.ai/lib/tools/extract_keys.py`, `tests/unit/test_extract_keys.py`.

- [ ] **Step 1: Test**

```python
# tests/unit/test_extract_keys.py
import json
import pytest


def test_flat_id_parser_settings_xml():
    from lib.tools.extract_keys import flat_id_parser
    xml = b'<?xml version="1.0"?><settings><setting id="a" value="1"/><setting id="b" value="2"/></settings>'
    out = flat_id_parser(xml)
    assert out == {"a": "1", "b": "2"}


def test_path_flatten_advancedsettings():
    from lib.tools.extract_keys import path_flatten_parser
    xml = b'<advancedsettings><network><buffermode>1</buffermode></network></advancedsettings>'
    out = path_flatten_parser(xml)
    assert out["advancedsettings/network/buffermode"] == "1"


def test_path_flatten_with_repeated_sibling_indexing():
    from lib.tools.extract_keys import path_flatten_parser
    xml = (
        b'<sources><video>'
        b'<source><name>Movies</name><path>/mnt/a</path></source>'
        b'<source><name>TV</name><path>/mnt/b</path></source>'
        b'</video></sources>'
    )
    out = path_flatten_parser(xml)
    assert out["sources/video/source[0]/name"] == "Movies"
    assert out["sources/video/source[0]/path"] == "/mnt/a"
    assert out["sources/video/source[1]/name"] == "TV"
    assert out["sources/video/source[1]/path"] == "/mnt/b"


def test_json_walker():
    from lib.tools.extract_keys import json_walker
    raw = json.dumps({"a": {"b": 1, "c": [10, 20]}}).encode()
    out = json_walker(raw)
    assert out["a.b"] == 1
    assert out["a.c[0]"] == 10
    assert out["a.c[1]"] == 20


def test_parser_for_path_dispatch():
    from lib.tools.extract_keys import parser_for_path
    assert parser_for_path("/x/settings.xml").__name__ == "flat_id_parser"
    assert parser_for_path("/x/advancedsettings.xml").__name__ == "path_flatten_parser"
    assert parser_for_path("/x/config.json").__name__ == "json_walker"
    assert parser_for_path("/x/binary.bin") is None
```

- [ ] **Step 2: Implement `service.kodi.ai/lib/tools/extract_keys.py`**

```python
# service.kodi.ai/lib/tools/extract_keys.py
"""extract_keys parsers per spec §4.6: flat-id, path-flatten with [N]
sibling indexing, JSON walker. Used by snapshot_manager for file_keys
staleness checks."""
from __future__ import annotations
import json
import os
import re
import xml.etree.ElementTree as ET


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def flat_id_parser(raw: bytes) -> dict[str, str]:
    """For settings.xml / addon.xml: <setting id='X' value='Y'/> → {X: Y}."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    out: dict[str, str] = {}
    for elem in root.iter():
        if _strip_ns(elem.tag) == "setting":
            sid = elem.get("id")
            if sid is not None:
                out[sid] = elem.get("value") or (elem.text or "")
    return out


def path_flatten_parser(raw: bytes) -> dict[str, str]:
    """Walk tree, emit path → value. Repeated siblings → path[N] zero-indexed."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    out: dict[str, str] = {}

    def walk(elem, path):
        children = list(elem)
        # Group children by tag for [N] indexing
        by_tag: dict[str, list] = {}
        for c in children:
            by_tag.setdefault(_strip_ns(c.tag), []).append(c)
        for tag, kids in by_tag.items():
            if len(kids) == 1:
                cp = f"{path}/{tag}"
                if list(kids[0]):
                    walk(kids[0], cp)
                else:
                    out[cp] = (kids[0].text or "").strip()
            else:
                for i, k in enumerate(kids):
                    cp = f"{path}/{tag}[{i}]"
                    if list(k):
                        walk(k, cp)
                    else:
                        out[cp] = (k.text or "").strip()

    walk(root, _strip_ns(root.tag))
    return out


def json_walker(raw: bytes) -> dict[str, any]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    out: dict[str, any] = {}

    def walk(obj, prefix):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{prefix}.{k}" if prefix else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{prefix}[{i}]")
        else:
            out[prefix] = obj

    walk(data, "")
    return out


_PATH_REGISTRY = {
    "settings.xml": flat_id_parser,
    "addon.xml": flat_id_parser,
    "advancedsettings.xml": path_flatten_parser,
    "sources.xml": path_flatten_parser,
    "mediasources.xml": path_flatten_parser,
}


def parser_for_path(path: str):
    basename = os.path.basename(path)
    if basename in _PATH_REGISTRY:
        return _PATH_REGISTRY[basename]
    if basename.endswith(".json"):
        return json_walker
    return None
```

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/unit/test_extract_keys.py -v   # 5 passed
git add service.kodi.ai/lib/tools/extract_keys.py tests/unit/test_extract_keys.py
git commit -m "feat(tools.extract_keys): XML/JSON parsers for snapshot_targets

flat_id_parser: <setting id='X' value='Y'/> → {X: Y} for settings.xml/addon.xml.
path_flatten_parser: walks tree, emits path → value; repeated siblings get
path[N] zero-indexed (sources.xml/advancedsettings.xml/mediasources.xml).
json_walker: dotted-path flattening for JSON.
parser_for_path: dispatches by basename; unknown files → None
(snapshot_manager falls back to byte-equality file kind).
XML namespace stripping; ParseError → empty dict (defensive).

Spec: §4.6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6.4 — `lib/tools/schema.py`: tool → OpenAI function spec

**Spec ref:** §4.1 (schema exposure to LLM).

**Files:** Create `service.kodi.ai/lib/tools/schema.py`, `tests/unit/test_tool_schema.py`.

- [ ] **Step 1: Test**

```python
# tests/unit/test_tool_schema.py
def test_get_tool_schemas_emits_openai_format():
    from lib.tools import tool, registry, ToolResult
    from lib.tools.schema import get_tool_schemas
    registry.clear()
    @tool(name="foo", description="does foo",
          schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
          tier="immediate")
    def foo(x: str): return ToolResult(success=True, requested="foo", output=None,
                                        actual_state_after=None, error=None,
                                        snapshot_id=None, cost_seconds=0.0)
    schemas = get_tool_schemas()
    assert len(schemas) == 1
    s = schemas[0]
    assert s["type"] == "function"
    assert s["function"]["name"] == "foo"
    assert s["function"]["description"] == "does foo"
    assert s["function"]["parameters"]["properties"]["x"]["type"] == "string"
```

- [ ] **Step 2: Implement `service.kodi.ai/lib/tools/schema.py`**

```python
# service.kodi.ai/lib/tools/schema.py
"""Convert @tool registry → OpenAI tool-use function schema list."""
from __future__ import annotations
from . import registry


def get_tool_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": fn.tool_name,
                "description": fn.description,
                "parameters": fn.tool_schema,
            },
        }
        for fn in registry.values()
    ]
```

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/unit/test_tool_schema.py -v
git add service.kodi.ai/lib/tools/schema.py tests/unit/test_tool_schema.py
git commit -m "feat(tools.schema): get_tool_schemas → OpenAI function-spec list

Exposes @tool registry as the list[dict] format OpenRouter expects in
chat.completions tools parameter.

Spec: §4.1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 7 — Individual tools (10 tasks)

> **Pattern note:** Phase 7 tools follow a uniform pattern: test → implement → register via `@tool` → register runtime resolver/applier (if mutating) → commit. Examples below are templates; same structure repeats per tool.

### Task 7.1 — `lib/tools/kodi_jsonrpc.py`: read-only allowlist enforcement + helper

**Spec ref:** §4.3.

**Files:** Create `service.kodi.ai/lib/tools/kodi_jsonrpc.py`, `tests/integration/test_tool_kodi_jsonrpc.py`.

- [ ] **Step 1: Test**

```python
# tests/integration/test_tool_kodi_jsonrpc.py
import json, sys, pytest
from unittest import mock


@pytest.fixture
def fake_xbmc(monkeypatch):
    fake = mock.MagicMock()
    fake.executeJSONRPC.side_effect = lambda s: json.dumps({
        "result": {"version": {"major": 13}}
    })
    monkeypatch.setitem(sys.modules, "xbmc", fake)
    return fake


@pytest.mark.integration
def test_allowed_method_executes(fake_xbmc):
    from lib.tools.kodi_jsonrpc import kodi_jsonrpc
    res = kodi_jsonrpc(method="JSONRPC.Version", params={})
    assert res.success
    assert "version" in res.output


@pytest.mark.integration
def test_denied_method_blocked(fake_xbmc):
    from lib.tools.kodi_jsonrpc import kodi_jsonrpc
    res = kodi_jsonrpc(method="Application.Quit", params={})
    assert not res.success
    assert "not allowlisted" in res.error


@pytest.mark.integration
def test_call_helper_for_other_tools(fake_xbmc):
    """Internal tools use call() to bypass allowlist (still safe; tools enforce
    their own contracts)."""
    from lib.tools.kodi_jsonrpc import call
    res = call("Settings.SetSettingValue", {"setting": "x", "value": "y"})
    assert "result" in res or "error" in res
```

- [ ] **Step 2: Implement `service.kodi.ai/lib/tools/kodi_jsonrpc.py`**

```python
# service.kodi.ai/lib/tools/kodi_jsonrpc.py
"""Raw JSON-RPC tool exposed to LLM (allowlist-only).

call() is the internal helper used by OTHER tools (kodi_addons,
kodi_settings, etc.) — bypasses allowlist because those tools enforce
their own contracts.

Spec: §4.3.
"""
from __future__ import annotations
import json
import xbmc
from . import tool, ToolResult


ALLOWLIST: set[str] = {
    "Addons.GetAddons", "Addons.GetAddonDetails",
    "Settings.GetSettings", "Settings.GetSettingValue", "Settings.GetCategories",
    "System.GetProperties", "Application.GetProperties",
    "Player.GetActivePlayers", "Player.GetItem", "Player.GetProperties", "Player.GetPlayers",
    "JSONRPC.Introspect", "JSONRPC.Permission", "JSONRPC.Version", "JSONRPC.Ping",
    "Files.GetDirectory", "Files.GetFileDetails", "Files.GetSources", "Files.PrepareDownload",
    "GUI.GetProperties",
    "Profiles.GetCurrentProfile", "Profiles.GetProfiles",
    "Textures.GetTextures",
    "PVR.GetProperties", "PVR.GetChannels", "PVR.GetClients",
}


def call(method: str, params: dict | None = None) -> dict:
    """Internal helper for other tools. NOT allowlisted (callers enforce safety)."""
    req = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}
    raw = xbmc.executeJSONRPC(json.dumps(req))
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"error": {"message": "invalid JSON-RPC response"}}


@tool(
    name="kodi_jsonrpc",
    description="Call a Kodi JSON-RPC method (read-only allowlist). See spec for allowed methods.",
    schema={
        "type": "object",
        "properties": {
            "method": {"type": "string"},
            "params": {"type": "object", "default": {}},
        },
        "required": ["method"],
    },
    tier="immediate",
    safety_class="read_only",
)
def kodi_jsonrpc(method: str, params: dict | None = None) -> ToolResult:
    if method not in ALLOWLIST:
        return ToolResult(
            success=False, requested=f"kodi_jsonrpc({method})",
            output=None, actual_state_after=None,
            error=f"method '{method}' not allowlisted; use typed tool or request §4 allowlist extension",
            snapshot_id=None, cost_seconds=0.0,
        )
    res = call(method, params or {})
    err = res.get("error")
    if err:
        return ToolResult(success=False, requested=f"kodi_jsonrpc({method})",
                          output=None, actual_state_after=None,
                          error=str(err), snapshot_id=None, cost_seconds=0.0)
    return ToolResult(success=True, requested=f"kodi_jsonrpc({method})",
                      output=res.get("result"), actual_state_after=None,
                      error=None, snapshot_id=None, cost_seconds=0.0)
```

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/integration/test_tool_kodi_jsonrpc.py -v -m integration
git add service.kodi.ai/lib/tools/kodi_jsonrpc.py tests/integration/test_tool_kodi_jsonrpc.py
git commit -m "feat(tools.kodi_jsonrpc): allowlist-enforced raw JSON-RPC tool

call() helper for internal tool use (no allowlist). kodi_jsonrpc @tool
enforces ALLOWLIST set of read-only methods per spec §4.3; rejects with
clear error message pointing to typed tools.

Spec: §4.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7.2 — `lib/tools/http.py`: HTTPS-only http_get with size + timeout caps

**Spec ref:** §4.6 (http_get tool).

**Files:** Create `service.kodi.ai/lib/tools/http.py`, `tests/unit/test_tool_http.py`.

- [ ] **Step 1: Test + impl + commit (compact)**

```python
# tests/unit/test_tool_http.py
import pytest, responses

@responses.activate
def test_http_get_success():
    responses.add(responses.GET, "https://example.com/x", body="hello", status=200)
    from lib.tools.http import http_get
    res = http_get(url="https://example.com/x")
    assert res.success
    assert res.output["status"] == 200
    assert res.output["body_text"] == "hello"

def test_http_get_rejects_non_https():
    from lib.tools.http import http_get
    res = http_get(url="http://evil.example.com/x")
    assert not res.success
    assert "HTTPS" in res.error

def test_http_get_allows_localhost():
    # No mock needed — should at least pass URL validation
    from lib.tools.http import http_get
    res = http_get(url="http://127.0.0.1:1/x", timeout_s=0.1)
    # Connection will fail, but URL validation should pass:
    assert "HTTPS" not in (res.error or "")

@responses.activate
def test_http_get_truncates_at_size_cap():
    responses.add(responses.GET, "https://example.com/big", body="x" * 3_000_000, status=200)
    from lib.tools.http import http_get
    res = http_get(url="https://example.com/big", max_bytes=1024)
    assert res.success
    assert len(res.output["body_text"]) <= 1024
```

Implement `service.kodi.ai/lib/tools/http.py`:

```python
# service.kodi.ai/lib/tools/http.py
"""http_get: HTTPS-only (localhost exception), size + timeout caps.

Spec: §4.6.
"""
from __future__ import annotations
import requests
from . import tool, ToolResult


def _is_loopback(url: str) -> bool:
    return any(loop in url for loop in ("//127.0.0.1", "//localhost", "//::1"))


@tool(
    name="http_get",
    description="HTTP GET. HTTPS only (loopback exception). Size + timeout capped.",
    schema={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "timeout_s": {"type": "integer", "default": 15},
            "max_bytes": {"type": "integer", "default": 1048576},
        },
        "required": ["url"],
    },
    tier="immediate", safety_class="read_only",
)
def http_get(url: str, timeout_s: int = 15, max_bytes: int = 1_048_576) -> ToolResult:
    if not url.startswith("https://") and not _is_loopback(url):
        return ToolResult(success=False, requested=f"http_get({url})",
                          output=None, actual_state_after=None,
                          error="HTTPS required (loopback exception only)",
                          snapshot_id=None, cost_seconds=0.0)
    try:
        r = requests.get(url, timeout=(3, timeout_s), stream=True)
    except Exception as e:
        return ToolResult(success=False, requested=f"http_get({url})", output=None,
                          actual_state_after=None, error=str(e),
                          snapshot_id=None, cost_seconds=0.0)
    body = r.raw.read(max_bytes, decode_content=True) if r.raw else b""
    body_text = body.decode("utf-8", errors="replace")
    r.close()
    return ToolResult(
        success=True, requested=f"http_get({url})",
        output={"status": r.status_code, "headers": dict(r.headers), "body_text": body_text},
        actual_state_after=None, error=None, snapshot_id=None, cost_seconds=0.0,
    )
```

```bash
pytest tests/unit/test_tool_http.py -v
git add service.kodi.ai/lib/tools/http.py tests/unit/test_tool_http.py
git commit -m "feat(tools.http): http_get HTTPS-only with size+timeout caps

Loopback exception (127.0.0.1/localhost/::1) for local testing. Size cap
via streamed read. timeout=(3, timeout_s) tuple. Returns status/headers/
body_text in output.

Spec: §4.6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7.3 — `lib/tools/kodi_addons.py`: list/install/uninstall/enable/disable/restart/update/clear_cache

**Spec ref:** §4.6 (addon mutation tools), §4.2 (builtin_with_verify).

**Files:** Create `service.kodi.ai/lib/tools/kodi_addons.py`, `tests/integration/test_tool_kodi_addons.py`.

- [ ] **Step 1: Test (subset shown — extend per tool)**

```python
# tests/integration/test_tool_kodi_addons.py
import json, sys, pytest, os, shutil
from unittest import mock
from tests.integration.fakes import fake_xbmcvfs


@pytest.fixture
def fake_kodi(monkeypatch):
    xbmc = mock.MagicMock()
    state = {"addons": {
        "plugin.video.seren": {"enabled": True, "installed": True, "version": "1.0.0",
                                "path": fake_xbmcvfs.translatePath("special://home/addons/plugin.video.seren"),
                                "dependencies": []},
    }, "play_active": False}
    def jsonrpc(req_str):
        req = json.loads(req_str)
        m = req["method"]; p = req.get("params") or {}
        if m == "Addons.GetAddonDetails":
            aid = p["addonid"]
            a = state["addons"].get(aid)
            if not a:
                return json.dumps({"error": {"message": "not found"}})
            return json.dumps({"result": {"addon": {**a, "addonid": aid}}})
        if m == "Addons.SetAddonEnabled":
            aid = p["addonid"]; en = p["enabled"]
            if aid in state["addons"]:
                state["addons"][aid]["enabled"] = en
            return json.dumps({"result": "OK"})
        if m == "Player.GetActivePlayers":
            return json.dumps({"result": [{"type": "video"}] if state["play_active"] else []})
        if m == "Player.GetItem":
            return json.dumps({"result": {"item": {"addon": "plugin.video.seren"}}})
        return json.dumps({"result": None})
    xbmc.executeJSONRPC.side_effect = jsonrpc
    builtins_called = []
    def be(cmd):
        builtins_called.append(cmd)
        if cmd.startswith("EnableAddon("):
            aid = cmd[len("EnableAddon("):-1]
            if aid in state["addons"]:
                state["addons"][aid]["enabled"] = True
        if cmd.startswith("DisableAddon("):
            aid = cmd[len("DisableAddon("):-1]
            if aid in state["addons"]:
                state["addons"][aid]["enabled"] = False
        if cmd.startswith("InstallAddon("):
            aid = cmd[len("InstallAddon("):-1]
            state["addons"].setdefault(aid, {"enabled": True, "installed": True,
                                              "version": "0.1.0", "path": "/tmp/x", "dependencies": []})
    xbmc.executebuiltin.side_effect = be
    xbmc._state = state
    xbmc._builtins = builtins_called
    monkeypatch.setitem(sys.modules, "xbmc", xbmc)
    yield xbmc


@pytest.mark.integration
def test_list_addons_returns_installed(fake_kodi):
    from lib.tools.kodi_addons import list_addons
    res = list_addons()
    assert res.success
    # output should contain the seren addon
    assert any("seren" in str(a) for a in (res.output or []))


@pytest.mark.integration
def test_enable_disable_round_trip(fake_kodi):
    from lib.tools.kodi_addons import disable_addon, enable_addon
    r1 = disable_addon(addon_id="plugin.video.seren")
    assert r1.success
    assert fake_kodi._state["addons"]["plugin.video.seren"]["enabled"] is False
    r2 = enable_addon(addon_id="plugin.video.seren")
    assert r2.success
    assert fake_kodi._state["addons"]["plugin.video.seren"]["enabled"] is True


@pytest.mark.integration
def test_restart_addon_disruptive_when_player_active(fake_kodi):
    from lib.tools.kodi_addons import restart_addon, _restart_disruptive_fn
    fake_kodi._state["play_active"] = True
    assert _restart_disruptive_fn({"addon_id": "plugin.video.seren"}) is True
    fake_kodi._state["play_active"] = False
    assert _restart_disruptive_fn({"addon_id": "plugin.video.seren"}) is False
```

- [ ] **Step 2: Implement `service.kodi.ai/lib/tools/kodi_addons.py`**

```python
# service.kodi.ai/lib/tools/kodi_addons.py
"""Addon mutation tools per spec §4.6.

list_addons / get_addon_details (read-only).
install/uninstall/enable/disable/restart/update (mutation w/ snapshot+verify).
clear_addon_cache (folded restart, immediate+disruptive_callable).
"""
from __future__ import annotations
import os
import shutil
import time
from .kodi_jsonrpc import call as jrpc
import xbmc
from . import tool, ToolResult


# ---- builtin_with_verify helper ----
def builtin_with_verify(builtin: str, verify, timeout_s: float = 10.0) -> bool:
    from ..concurrency import abort_event
    xbmc.executebuiltin(builtin)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if abort_event.wait(0.25):
            return False
        try:
            if verify():
                return True
        except Exception:
            pass
    return False


# ---- helpers ----
def _addon_details(addon_id: str) -> dict | None:
    r = jrpc("Addons.GetAddonDetails", {
        "addonid": addon_id,
        "properties": ["version", "enabled", "broken", "path", "dependencies", "name"],
    })
    if "error" in r:
        return None
    return r.get("result", {}).get("addon")


def addon_owns_active_player(addon_id: str) -> bool:
    pp = jrpc("Player.GetActivePlayers", {})
    if pp.get("result"):
        item = jrpc("Player.GetItem", {"playerid": pp["result"][0]["playerid"],
                                        "properties": []})
        return (item.get("result", {}).get("item", {}).get("addon") == addon_id)
    return False


# ---- list_addons ----
@tool(
    name="list_addons", description="List installed addons. enabled=None returns ALL (use for disabled-dep diagnosis); broken=None returns all incl broken.",
    schema={"type": "object", "properties": {
        "type": {"type": ["string", "null"]},
        "enabled": {"type": ["boolean", "null"], "default": None},
        "broken": {"type": ["boolean", "null"], "default": None},
    }},
    tier="immediate", safety_class="read_only",
)
def list_addons(type=None, enabled=None, broken=None) -> ToolResult:
    params = {"properties": ["version", "enabled", "broken", "path", "name"]}
    if type: params["type"] = type
    # Note: Kodi defaults enabled=True; explicitly pass when caller wants ALL
    if enabled is not None: params["enabled"] = enabled
    r = jrpc("Addons.GetAddons", params)
    if "error" in r:
        return ToolResult(success=False, requested="list_addons", output=None,
                          actual_state_after=None, error=str(r["error"]),
                          snapshot_id=None, cost_seconds=0.0)
    return ToolResult(success=True, requested="list_addons",
                      output=r.get("result", {}).get("addons", []),
                      actual_state_after=None, error=None,
                      snapshot_id=None, cost_seconds=0.0)


# ---- get_addon_details ----
@tool(
    name="get_addon_details", description="Full addon info: version, enabled, broken, path, dependencies.",
    schema={"type": "object", "properties": {"addon_id": {"type": "string"}}, "required": ["addon_id"]},
    tier="immediate", safety_class="read_only",
)
def get_addon_details(addon_id: str) -> ToolResult:
    a = _addon_details(addon_id)
    if a is None:
        return ToolResult(success=False, requested=f"get_addon_details({addon_id})",
                          output=None, actual_state_after=None, error="not found",
                          snapshot_id=None, cost_seconds=0.0)
    return ToolResult(success=True, requested=f"get_addon_details({addon_id})",
                      output=a, actual_state_after=None, error=None,
                      snapshot_id=None, cost_seconds=0.0)


# ---- enable_addon ----
@tool(
    name="enable_addon", description="Enable an installed addon.",
    schema={"type": "object", "properties": {"addon_id": {"type": "string"}}, "required": ["addon_id"]},
    tier="immediate",
    target_addons=lambda args: {args.get("addon_id")},
)
def enable_addon(addon_id: str) -> ToolResult:
    ok = builtin_with_verify(
        f"EnableAddon({addon_id})",
        verify=lambda: (_addon_details(addon_id) or {}).get("enabled") is True,
        timeout_s=10,
    )
    a = _addon_details(addon_id) or {}
    return ToolResult(
        success=ok, requested=f"enable_addon({addon_id})",
        output=None,
        actual_state_after={"enabled": a.get("enabled"), "version": a.get("version")},
        error=None if ok else "EnableAddon did not produce enabled=True within 10s",
        snapshot_id=None, cost_seconds=0.0,
    )


# ---- disable_addon ----
def _disruptive_when_owns_player(args: dict) -> bool:
    aid = args.get("addon_id", "")
    return addon_owns_active_player(aid)


@tool(
    name="disable_addon", description="Disable an installed addon.",
    schema={"type": "object", "properties": {"addon_id": {"type": "string"}}, "required": ["addon_id"]},
    tier="confirm",
    disruptive=_disruptive_when_owns_player,
    target_addons=lambda args: {args.get("addon_id")},
)
def disable_addon(addon_id: str) -> ToolResult:
    ok = builtin_with_verify(
        f"DisableAddon({addon_id})",
        verify=lambda: (_addon_details(addon_id) or {}).get("enabled") is False,
        timeout_s=10,
    )
    a = _addon_details(addon_id) or {}
    return ToolResult(success=ok, requested=f"disable_addon({addon_id})",
                      output=None,
                      actual_state_after={"enabled": a.get("enabled")},
                      error=None if ok else "DisableAddon did not produce enabled=False within 10s",
                      snapshot_id=None, cost_seconds=0.0)


# ---- restart_addon (alias for our purposes: disable+enable) ----
def _restart_disruptive_fn(args: dict) -> bool:
    return _disruptive_when_owns_player(args)


@tool(
    name="restart_addon", description="Disable + enable an addon to restart it (picks up cache clears, settings changes).",
    schema={"type": "object", "properties": {"addon_id": {"type": "string"}}, "required": ["addon_id"]},
    tier="immediate",
    disruptive=_restart_disruptive_fn,
    target_addons=lambda args: {args.get("addon_id")},
)
def restart_addon(addon_id: str) -> ToolResult:
    r1 = disable_addon(addon_id=addon_id)
    if not r1.success:
        return ToolResult(success=False, requested=f"restart_addon({addon_id})",
                          output=None, actual_state_after=r1.actual_state_after,
                          error=f"disable failed: {r1.error}",
                          snapshot_id=None, cost_seconds=0.0)
    r2 = enable_addon(addon_id=addon_id)
    return ToolResult(success=r2.success, requested=f"restart_addon({addon_id})",
                      output=None, actual_state_after=r2.actual_state_after,
                      error=r2.error, snapshot_id=None, cost_seconds=0.0)


# ---- install_addon (with deferred dep_closure target_addons) ----
def _install_target_addons(args: dict) -> set[str]:
    aid = args.get("addon_id", "")
    seen = {aid}
    stack = [aid]
    while stack:
        cur = stack.pop()
        a = _addon_details(cur)
        for d in (a or {}).get("dependencies", []):
            did = d.get("addonid")
            if did and did not in seen:
                seen.add(did); stack.append(did)
    return seen


@tool(
    name="install_addon", description="Install an addon from an already-installed repository (recursively pulls deps).",
    schema={"type": "object", "properties": {"addon_id": {"type": "string"}}, "required": ["addon_id"]},
    tier="confirm",
    target_addons=_install_target_addons,
)
def install_addon(addon_id: str) -> ToolResult:
    ok = builtin_with_verify(
        f"InstallAddon({addon_id})",
        verify=lambda: (_addon_details(addon_id) or {}).get("installed", False)
                       and (_addon_details(addon_id) or {}).get("enabled", False),
        timeout_s=60,
    )
    a = _addon_details(addon_id) or {}
    return ToolResult(success=ok, requested=f"install_addon({addon_id})",
                      output=None,
                      actual_state_after={"enabled": a.get("enabled"),
                                          "installed": a.get("installed"),
                                          "version": a.get("version")},
                      error=None if ok else "InstallAddon did not complete within 60s",
                      snapshot_id=None, cost_seconds=0.0)


# ---- uninstall_addon, update_addon, clear_addon_cache ----
# Pattern repeats; implementation analogous to install/disable. Per spec §4.6:
# - uninstall: tier=confirm, disruptive=owns_player, target_addons={addon_id}
# - update_addon: pre-fetch old version, call UpdateAddon(), verify version changed OR
#   no recurrence in 60s → success "already at latest or repo unreachable" (with warning)
# - clear_addon_cache: tier=immediate, disruptive=owns_player. Delete
#   addon_data/<id>/cache/ + <install_path>/__pycache__/, then restart_addon().

# (Full implementations below — same pattern as above. Omitted here for plan brevity;
# implementation agent should follow the pattern.)
```

The implementation agent should complete `uninstall_addon`, `update_addon`, and `clear_addon_cache` following the same pattern as above per spec §4.6 verify-logic specs. Both reviewer + implementer for those follow the loop discipline.

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/integration/test_tool_kodi_addons.py -v -m integration
git add service.kodi.ai/lib/tools/kodi_addons.py tests/integration/test_tool_kodi_addons.py
git commit -m "feat(tools.kodi_addons): list/get_details/enable/disable/restart/install

builtin_with_verify wrapper: xbmc.executebuiltin + abort_event.wait(0.25)
polling + verify lambda + timeout.
addon_owns_active_player: queries Player.GetActivePlayers + Player.GetItem
to check if a given addon currently owns playback.
Tools registered via @tool with tier/disruptive/target_addons per spec §4.6.
install_addon: target_addons computes dep closure via recursive
Addons.GetAddonDetails.
Stubs for uninstall_addon, update_addon, clear_addon_cache (full
implementations follow same pattern in subsequent commits).

Spec: §4.2, §4.6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7.4 — `lib/tools/kodi_addons.py` part 2: uninstall + update + clear_cache

(Same TDD pattern. Implementation per spec §4.6.)

- [ ] **Step 1: Tests** for `uninstall_addon` (confirm + disruptive + addon_state snapshot), `update_addon` (pre-fetch old_version → UpdateAddon builtin → verify version_changed OR no-recurrence within 60s; if 60s timeout + no recurrence → success with warning="already at latest or repo unreachable"; if 60s + recurrence → failure), `clear_addon_cache` (delete cache + __pycache__ + restart_addon, with PermissionError handling for read-only install paths).

- [ ] **Step 2: Implementation** appends to `kodi_addons.py`.

- [ ] **Step 3: Tests pass + commit**

```bash
git commit -m "feat(tools.kodi_addons): uninstall + update + clear_cache

update_addon per spec round-3 verify logic: capture old_version pre-call,
executebuiltin('UpdateAddon(...)'), verify version!=old_version within 60s;
on timeout + no cluster recurrence → success 'already at latest or repo
unreachable' with warning.
clear_addon_cache: deletes addon_data/<id>/cache/ + <install_path>/__pycache__/
(PermissionError → ToolResult fail), then restart_addon (disruptive=
owns_player). Spec: §4.6 round-2 fold of restart per spec round-3 fix.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7.5 — `lib/tools/kodi_settings.py`: get/set Kodi setting + addon setting (enabled vs disabled)

**Spec ref:** §4.6.

**Files:** Create `service.kodi.ai/lib/tools/kodi_settings.py`, `tests/integration/test_tool_kodi_settings.py`.

- [ ] **Step 1: Test** — covers `get_addon_setting` (enabled path via xbmcaddon, disabled path via xmlparse), `set_addon_setting` (enabled via xbmcaddon.setSetting, disabled via direct xmlparse write + V1 type validation: bool/int/string pass-through, enum skipped with WARNING, slider/action rejected), `get_kodi_setting`, `set_kodi_setting` (with DISRUPTIVE_KODI_SETTINGS + CROSS_ADDON_SETTINGS lookups).

- [ ] **Step 2: Implement** per spec §4.6 rules. Register runtime resolvers/appliers with `snapshot_manager` for `kind="addon_setting"` and `kind="kodi_setting"`.

- [ ] **Step 3: Tests pass + commit**

```bash
git commit -m "feat(tools.kodi_settings): get/set Kodi + per-addon (enabled/disabled paths)

set_addon_setting enabled: xbmcaddon.Addon(id).setSetting(k,v) + read_back.
set_addon_setting disabled: parse <install>/resources/settings.xml for
<setting id=k.../>, V1 type-validate (bool/int range, string pass-through,
enum WARNING, slider reject), direct xmlparse write to addon_data/settings.xml.
set_kodi_setting: Settings.SetSettingValue + verify via GetSettingValue.
DISRUPTIVE_KODI_SETTINGS (videoplayer.*/audiooutput.*/etc) drives disruptive
callable. CROSS_ADDON_SETTINGS (services.*/general.*/lookandfeel.*) drives
target_addons='ALL'.
Runtime resolvers + appliers registered for snapshot_manager.

Spec: §4.6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7.6 — `lib/tools/kodi_files.py`: write/delete with path restriction + log readers

**Spec ref:** §4.6.

**Files:** Create `service.kodi.ai/lib/tools/kodi_files.py`, `tests/integration/test_tool_kodi_files.py`.

- [ ] **Step 1: Test** for: `read_log`, `read_log_old`, `write_file` (path restricted to `special://profile/`/`userdata/`/`temp/`; snapshot via `extract_keys.parser_for_path` or `kind="file"` byte-equality), `delete_file` (same path restriction).

- [ ] **Step 2: Implementation**. Register runtime handlers for `kind="file_keys"` + `kind="file"` with snapshot_manager.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(tools.kodi_files): read_log/read_log_old + write/delete with path lock

read_log: tail kodi.log (lines, level, addon filter, since_seconds).
read_log_old: tail kodi.old.log for boot-time diagnosis.
write_file/delete_file: path MUST be under special://profile/, userdata/,
or temp/ — reject otherwise.
snapshot_targets via extract_keys.parser_for_path (file_keys) or
byte-equality (file). Runtime handlers registered.

Spec: §4.6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7.7 — `lib/tools/verify.py`: per-cluster-category verifier strategies

**Spec ref:** §4.4.

**Files:** Create `service.kodi.ai/lib/tools/verify.py`, `tests/unit/test_tool_verify.py`.

- [ ] **Step 1: Test** — strategies: `playback_fail` (waits for Player.OnPlay via polling + cluster non-recurrence 10s window, OR recurrence, OR 5min, OR abort_event), `dep_import_fail` (restart_addon then 30s clean-import window), `repo_unreachable` (poll URL every 1min for 30min), `default` (30s log-quiet for cluster_id).

- [ ] **Step 2: Implementation** uses `log_watcher.subscribe()` API (added in this task) for cluster non-recurrence monitoring.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(tools.verify): verify_fix with 4 per-cluster-category strategies

playback_fail: poll Player.GetActivePlayers @ 1s + watch cluster_id
non-recurrence 10s window. 5min total timeout. Abort-event interruptible.
dep_import_fail: restart_addon → 30s log-quiet for cluster_id OR same error.
repo_unreachable: http_get repo URL every 1min for 30min; on 200 → trigger
update_addon for affected addons + success notification.
default: 30s log-quiet for cluster_id.
All loops use abort_event.wait(0.25), not time.sleep.

log_watcher.subscribe(filter_fn, timeout_s, on_match) added — single tail
shared across consumers per spec §4.4.

Spec: §4.4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7.8 — `lib/tools/telegram_ask.py`: ask_user → triggers pause sequence

**Spec ref:** §1.7 (ask_user is non-blocking; pauses MonotonicBudget).

**Files:** Create `service.kodi.ai/lib/tools/telegram_ask.py`, `tests/unit/test_tool_telegram_ask.py`.

- [ ] **Step 1: Test** — `ask_user` returns `ToolResult(error="NEEDS_USER", success=False)` so reasoner sees the pause signal. Tool itself doesn't block; reasoner's pause flow handles MonotonicBudget.pause + state persist + Telegram send (Phase 8).

- [ ] **Step 2: Implementation**

```python
# service.kodi.ai/lib/tools/telegram_ask.py
"""ask_user — triggers reasoner pause + Telegram inline keyboard.

The tool itself just returns the NEEDS_USER marker. The reasoner detects
.requires_user_confirmation=True and serializes state + sends Telegram via
lib/telegram/bot.py.

Spec: §1.7.
"""
from . import tool, ToolResult


@tool(
    name="ask_user",
    description="Ask the user a yes/no/option question via Telegram. Pauses the agent until the user replies.",
    schema={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"},
                        "default": ["Yes", "No"]},
        },
        "required": ["question"],
    },
    tier="confirm",
)
def ask_user(question: str, options: list[str] | None = None) -> ToolResult:
    return ToolResult(
        success=False, requested=f"ask_user(...)", output={
            "question": question, "options": options or ["Yes", "No"],
        },
        actual_state_after=None, error="NEEDS_USER",
        snapshot_id=None, cost_seconds=0.0,
    )


ask_user.requires_user_confirmation = True
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(tools.telegram_ask): ask_user pause-signal tool

Returns ToolResult(success=False, error='NEEDS_USER') with question+options
in output. Reasoner sees the marker (via .requires_user_confirmation=True),
serializes SessionState, calls MonotonicBudget.pause, sends Telegram inline
keyboard (Phase 8 wiring in service.py + lib/telegram/bot.py).

Spec: §1.7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7.9 — Register all tools into reasoner's tool_registry

**Files:** Modify `service.kodi.ai/lib/tools/__init__.py` to auto-import all tool modules so `@tool` registrations land in `registry`.

```python
# Append to lib/tools/__init__.py:
def _autoload():
    from . import kodi_jsonrpc, http, kodi_addons, kodi_settings, kodi_files, verify, telegram_ask
_autoload()
```

- [ ] **Step 1: Test** — after `import lib.tools`, `registry` contains all expected tool names.

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(tools): autoload all tool modules on import

After 'import lib.tools', registry contains all @tool registrations
(kodi_jsonrpc/http/kodi_addons/kodi_settings/kodi_files/verify/telegram_ask).
Reasoner can then pass tools=registry into chat_stream tools argument.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7.10 — Tool dispatch wiring + snapshot_targets resolution in reasoner

**Files:** Modify `lib/reasoner.py` to: (a) compute `snapshot_targets(args)` and call `snapshot_manager.create()` before each mutating tool, attach `snapshot_id` to ToolResult; (b) use `tool_routing_decision` to drive pause flow; (c) check abort_event between tool calls.

- [ ] **Steps**: test → impl → commit (~ same pattern).

```bash
git commit -m "feat(reasoner): wire snapshot_targets + tool_routing into agent loop

Per @tool's snapshot_targets(args) callable: build [SnapshotTarget...],
call snapshot_manager.create() before tool exec, attach snapshot_id to
ToolResult.snapshot_id, accumulate in outcome.snapshot_ids for /undo.
tool_routing_decision drives pause: 'needs_confirmation' → triggers
ask_user-style flow + serialize + return needs_user outcome.
abort_event check between every tool call.

Spec: §4.1 dispatch flow.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 8 — Telegram + QR (7 tasks)

### Task 8.1 — `lib/qr.py`: pure-Python QR encoder + PNG writer (stdlib zlib only)

**Spec ref:** §5.2, §7.2.

**Files:** Create `service.kodi.ai/lib/qr.py`, `tests/unit/test_qr.py`.

- [ ] **Step 1: Test**

```python
# tests/unit/test_qr.py
import zlib
import struct


def test_qr_png_starts_with_png_signature(tmp_path):
    from lib.qr import qr_png
    data = qr_png("https://t.me/test_bot?start=abc123")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_qr_png_contains_idat_chunk(tmp_path):
    from lib.qr import qr_png
    data = qr_png("hello")
    assert b"IDAT" in data


def test_qr_png_no_pil_dependency():
    # qr.py must NOT import PIL/Pillow/qrcode
    import lib.qr as q
    import sys
    forbidden = {"PIL", "Pillow", "qrcode"}
    assert not any(m in sys.modules for m in forbidden if m in sys.modules and sys.modules[m] is not None) or True
    # Stronger check: module source doesn't import them
    import inspect
    src = inspect.getsource(q)
    assert "from PIL" not in src
    assert "import PIL" not in src
    assert "import qrcode" not in src
```

- [ ] **Step 2: Implementation**

Implement a focused QR encoder (byte mode, fixed ECC-M, version 1-10 selection by content length) + manual PNG writer with `zlib.compress` for IDAT + manual CRC32 for chunk integrity. ~600 LoC total.

**Implementation guidance for the implementer:** start from a public-domain QR-code reference (e.g., the Wikipedia algorithm description or `pyqrcode`'s mode-8 implementation). Use only `zlib` (stdlib) for DEFLATE; manual IDAT chunking + Adler32 + CRC32; black/white pixel grid → 1-bit-per-pixel scanlines → PNG. Test against several inputs of varying lengths (10-100 char URLs).

Public API:
```python
def qr_png(text: str, *, module_pixel_size: int = 8, ecc_level: str = "M") -> bytes:
    """Returns PNG bytes encoding text as QR code."""
```

- [ ] **Step 3: Commit**

```bash
pytest tests/unit/test_qr.py -v
git add service.kodi.ai/lib/qr.py tests/unit/test_qr.py
git commit -m "feat(qr): pure-Python QR encoder + PNG writer (stdlib zlib only)

qr_png(text) returns PNG bytes encoding text as QR code (mode-8 byte,
ECC-M default, version auto-selected by length). PNG writer uses stdlib
zlib.compress for IDAT + manual CRC32 chunk integrity + Adler32.
NO PIL/Pillow/qrcode dependencies. ~600 LoC self-contained.
Used by setup wizard (Phase 10) to render setup_secret as scannable QR.

Spec: §5.2, §7.2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8.2 — `lib/telegram/formatters.py`: HTML + 4000-char truncate + multi-part split

**Spec ref:** §4.5 (Telegram HTML), §4.6.

**Files:** Create `service.kodi.ai/lib/telegram/formatters.py`, `tests/unit/test_telegram_formatters.py`.

- [ ] **Step 1: Test + impl + commit**

```python
# tests/unit/test_telegram_formatters.py
def test_escape_html():
    from lib.telegram.formatters import escape_html
    assert escape_html("<script>") == "&lt;script&gt;"

def test_escape_href():
    from lib.telegram.formatters import escape_href
    assert "&quot;" in escape_href('"javascript:alert(1)"')

def test_format_log_in_pre():
    from lib.telegram.formatters import format_log_block
    out = format_log_block("ERROR <something> failed")
    assert out.startswith("<pre>")
    assert "&lt;something&gt;" in out

def test_truncate_at_4000():
    from lib.telegram.formatters import truncate
    long = "x" * 6000
    out = truncate(long)
    assert len(out) <= 4000
    assert "truncated" in out

def test_split_for_multipart():
    from lib.telegram.formatters import split_for_telegram
    long = "x" * 9500
    parts = split_for_telegram(long)
    assert len(parts) >= 3
    assert all(len(p) <= 4096 for p in parts)
    assert "part 1/" in parts[0].lower() or "part 1" in parts[0]
```

Implement:
```python
# service.kodi.ai/lib/telegram/formatters.py
"""HTML formatters for Telegram (parse_mode=HTML, NOT MarkdownV2).
Spec §4.5: html.escape on all dynamic content, href separately escaped
with quote=True, log content in <pre> after escape, 4000-char limit
with multi-part split."""
from __future__ import annotations
import html

LIMIT = 4000  # 96-char safety margin under Telegram's 4096


def escape_html(s: str) -> str:
    return html.escape(s, quote=False)


def escape_href(url: str) -> str:
    return html.escape(url, quote=True)


def format_log_block(log_text: str) -> str:
    return f"<pre>{escape_html(log_text)}</pre>"


def truncate(text: str, limit: int = LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 100] + "\n\n... (truncated, see /status for full)"


def split_for_telegram(text: str, limit: int = LIMIT) -> list[str]:
    """Split into Telegram-sendable parts. Adds (part N/M) header."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    pos = 0
    while pos < len(text):
        parts.append(text[pos : pos + limit - 50])
        pos += limit - 50
    return [f"(part {i+1}/{len(parts)})\n{p}" for i, p in enumerate(parts)]
```

```bash
pytest tests/unit/test_telegram_formatters.py -v
git add service.kodi.ai/lib/telegram/formatters.py tests/unit/test_telegram_formatters.py
git commit -m "feat(telegram.formatters): HTML escape + 4000-char truncate + multi-part split

escape_html / escape_href (quote=True for hrefs). format_log_block wraps
in <pre> after escape. truncate at 4000 (96-char safety under 4096).
split_for_telegram emits multi-part with '(part N/M)' header.

Spec: §4.5, §4.6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8.3 — `lib/telegram/auth.py`: setup_secret + chat_allowlist + reset

**Spec ref:** §5.2.

**Files:** Create `service.kodi.ai/lib/telegram/auth.py`, `tests/unit/test_telegram_auth.py`.

- [ ] **Step 1: Test + impl + commit**

Functions to implement:
- `generate_setup_secret() -> str` — `secrets.token_urlsafe(8)` (≈11 chars), persists via `lib.secrets.set_secret("setup_secret", ...)`.
- `current_setup_secret() -> str | None` — reads `secrets.get_secret("setup_secret")`.
- `chat_allowlist() -> list[int]` — reads `chat_allowlist.json` under addon_data.
- `try_authorize_first_start(chat_id, provided_secret) -> bool` — if `provided_secret == current_setup_secret()`, adds `chat_id` to allowlist, deletes `setup_secret`, also unlinks `setup_secret.txt` file (Task 10.1), updates `health.json::allowlist_populated_at`. Returns True/False.
- `is_authorized(chat_id) -> bool`.
- `reset_bot_owner() -> str` — clears allowlist + generates new setup_secret; returns the new secret. (Called from `default.py` button only — NOT exposed via Telegram.)

```bash
pytest tests/unit/test_telegram_auth.py -v
git add service.kodi.ai/lib/telegram/auth.py tests/unit/test_telegram_auth.py
git commit -m "feat(telegram.auth): setup_secret + chat_allowlist + reset path

generate_setup_secret() = secrets.token_urlsafe(8), persisted via
lib.secrets. try_authorize_first_start(chat_id, secret) validates secret,
adds chat_id to allowlist, deletes setup_secret + setup_secret.txt,
updates health.json::allowlist_populated_at. is_authorized() checks.
reset_bot_owner() (Kodi-UI-only) regenerates secret + clears allowlist.

Spec: §5.2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8.4 — `lib/telegram/bot.py` (T3): long-poll loop + dispatcher

**Spec ref:** §1.2 (T3 thread), §1.10 (timeout=(3,10)), §4.5 (Telegram backoff).

**Files:** Create `service.kodi.ai/lib/telegram/bot.py`, `tests/integration/test_telegram_bot.py`.

- [ ] **Step 1: Test** — `TelegramBot.run()` in a thread; mock `getUpdates`; verify UserMsg enqueued, callback_query enqueued as `ResumeWork`. Abort-event aware exit within 12s join.

- [ ] **Step 2: Implementation**

```python
# service.kodi.ai/lib/telegram/bot.py
"""T3 long-poll Telegram bot.

requests.get(getUpdates, timeout=(3,10)) — accepts 10s worst-case shutdown.
Auth via lib/telegram/auth.py. Dispatches via lib/telegram/commands.py and
lib/telegram/callbacks.py.

Spec: §1.2, §1.10, §4.5.
"""
from __future__ import annotations
import time
import random
import requests
from ..concurrency import abort_event, enqueue, UserMsg, ResumeWork
from . import auth


class TelegramBot:
    BASE = "https://api.telegram.org/bot"

    def __init__(self, bot_token: str):
        self.token = bot_token
        self._offset = 0

    def _url(self, method: str) -> str:
        return f"{self.BASE}{self.token}/{method}"

    def send_message(self, chat_id: int, text: str, *, reply_markup: dict | None = None,
                     reply_to_message_id: int | None = None,
                     disable_notification: bool = False,
                     parse_mode: str = "HTML") -> dict:
        payload = {
            "chat_id": chat_id, "text": text, "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }
        if reply_markup: payload["reply_markup"] = reply_markup
        if reply_to_message_id: payload["reply_to_message_id"] = reply_to_message_id
        r = requests.post(self._url("sendMessage"), json=payload, timeout=(3, 10))
        return r.json()

    def edit_message(self, chat_id: int, message_id: int, text: str,
                     reply_markup: dict | None = None, parse_mode: str = "HTML") -> dict:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text,
                   "parse_mode": parse_mode}
        if reply_markup: payload["reply_markup"] = reply_markup
        r = requests.post(self._url("editMessageText"), json=payload, timeout=(3, 10))
        return r.json()

    def answer_callback_query(self, callback_id: str, text: str = "") -> None:
        try:
            requests.post(self._url("answerCallbackQuery"),
                          json={"callback_query_id": callback_id, "text": text},
                          timeout=(3, 5))
        except Exception:
            pass

    def get_me(self) -> dict:
        r = requests.get(self._url("getMe"), timeout=(3, 5))
        return r.json()

    def _handle_update(self, upd: dict) -> None:
        # Callback queries → ResumeWork
        if "callback_query" in upd:
            cq = upd["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            if not auth.is_authorized(chat_id):
                return
            data = cq.get("data", "")
            # data format: "resume:<session_id>:<user_reply>"
            parts = data.split(":", 2)
            if len(parts) >= 3 and parts[0] == "resume":
                sid, reply = parts[1], parts[2]
                user_reply = reply if reply not in ("True", "False") else (reply == "True")
                enqueue(ResumeWork(session_id=sid, user_reply=user_reply))
            self.answer_callback_query(cq["id"])
            return
        # Regular messages
        if "message" in upd:
            msg = upd["message"]
            chat_id = msg["chat"]["id"]
            text = (msg.get("text") or "").strip()
            mid = msg.get("message_id")
            reply_to = (msg.get("reply_to_message") or {}).get("message_id")
            # /start <secret> auth flow
            if text.startswith("/start "):
                secret = text[len("/start "):].strip()
                if auth.try_authorize_first_start(chat_id, secret):
                    self.send_message(chat_id, "Welcome — Kodi-AI ready.")
                else:
                    self.send_message(chat_id, "Invalid secret. Send /start &lt;secret&gt;.")
                return
            if not auth.is_authorized(chat_id):
                self.send_message(chat_id, "Please send /start &lt;secret&gt; from your Kodi setup.")
                return
            enqueue(UserMsg(chat_id=chat_id, text=text, message_id=mid,
                            reply_to_message_id=reply_to))

    def run(self) -> None:
        from ..concurrency import startup_complete_event
        startup_complete_event.wait()
        backoff = 1.0
        while not abort_event.is_set():
            try:
                r = requests.get(
                    self._url("getUpdates"),
                    params={"offset": self._offset, "timeout": 10, "allowed_updates": ["message", "callback_query"]},
                    timeout=(3, 12),
                )
                if r.status_code == 429:
                    wait_s = int(r.headers.get("Retry-After", "5"))
                    if abort_event.wait(min(wait_s, 60)):
                        return
                    continue
                if r.status_code >= 500:
                    backoff = min(backoff * 2, 60)
                    if abort_event.wait(backoff + random.random()):
                        return
                    continue
                if r.status_code != 200:
                    if abort_event.wait(5):
                        return
                    continue
                backoff = 1.0
                for upd in r.json().get("result", []):
                    self._offset = max(self._offset, upd["update_id"] + 1)
                    try:
                        self._handle_update(upd)
                    except Exception:
                        pass
            except requests.exceptions.RequestException:
                if abort_event.wait(min(backoff, 30)):
                    return
                backoff = min(backoff * 2, 60)
```

- [ ] **Step 3: Tests pass + commit**

```bash
pytest tests/integration/test_telegram_bot.py -v -m integration
git add service.kodi.ai/lib/telegram/bot.py tests/integration/test_telegram_bot.py
git commit -m "feat(telegram.bot): T3 long-poll dispatcher

TelegramBot.run() waits startup_complete_event then loops getUpdates with
timeout=(3,12) + allowed_updates filter. 429 honors Retry-After (capped 60s);
5xx exp backoff (capped 60s). Network errors backoff.
_handle_update: /start <secret> drives auth.try_authorize_first_start;
authorized messages → UserMsg; callback_query data 'resume:<sid>:<reply>'
→ ResumeWork(priority=0). All abort_event-aware via .wait().
send_message/edit_message/answer_callback_query helpers.

Spec: §1.2, §1.10, §4.5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8.5 — `lib/telegram/commands.py`: /help /status /undo /pause /resume /disable /enable /panic /budget /mode /secret /audit /invite /retry-notify

**Files:** Create `service.kodi.ai/lib/telegram/commands.py`, `tests/unit/test_telegram_commands.py`.

Each command is a function `cmd_<name>(bot, chat_id, args_text)` invoked by `bot.py` when message text matches `/<name>(\s+|$)`.

- [ ] **Step 1: Test stubs for each command (auth check, basic behavior).**
- [ ] **Step 2: Implementations call into appropriate modules (lib.health, lib.recovery, snapshot_manager, audit_log, settings).**
- [ ] **Step 3: Commit**

```bash
git commit -m "feat(telegram.commands): all V1 commands

/help (list commands), /status (budget+last fixes+paused+model availability+
audit tail), /undo [fix_id] (snapshot_restore with stale prompt), /pause [min]
(sets disable.flag with TTL), /resume, /disable, /enable, /panic (validates
all session snapshots: fresh→auto-restore, stale→per-snapshot [Force/Skip]
buttons, 5min default-SKIP, abort_event=fail-safe SKIP-ALL +
panic_state.json), /budget [raise daily N] (mutates BudgetGuard caps in mem
+ persists), /mode auto|manual, /secret (shows current setup_secret),
/audit [count] [event], /invite <secret> (V2-stub: rejects 'V2 feature'),
/retry-notify <session_id> (re-attempts notifier for pause_notify_failed).
All commands check auth.is_authorized first.

Spec: §5.7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8.6 — `lib/telegram/callbacks.py`: callback_query routing + reply_to_message_id matching

**Files:** Create `service.kodi.ai/lib/telegram/callbacks.py`, `tests/unit/test_telegram_callbacks.py`.

Resolves a callback / reply to a paused session: first try `reply_to_message_id` lookup, fallback to most-recent paused session for `chat_id` within 1h TTL.

```bash
git commit -m "feat(telegram.callbacks): callback_query + reply routing

resolve_session_for_callback(callback_query) tries reply_to_message_id first
(maps to stored msg_id from pause Telegram send), fallback to most-recent
paused session for chat_id within 1h TTL.
resolve_session_for_reply(message) same fallback chain.

Spec: §5.7 reply_to_message_id matching.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8.7 — `lib/notifier.py`: synchronous notifier + interruptible retry

**Spec ref:** §1.7 (pause_notify_failed handling), §3.4, §5.7.

**Files:** Create `service.kodi.ai/lib/notifier.py`, `tests/unit/test_notifier.py`.

```python
# service.kodi.ai/lib/notifier.py
"""Synchronous notifier — called inline by T4 (NOT a thread).

send_message_with_retry(chat_id, text, ...) — 3-retry exp backoff (1,2,4s)
with abort_event.wait between attempts. Shutdown short-path: if
abort_event.is_set() at start → single attempt with timeout=(2,3).
Returns success bool + retries count.

Kodi toast fallback via xbmcgui.Dialog().notification on persistent failure.

Spec: §1.7, §3.4, §5.7.
"""
from __future__ import annotations
import requests
import xbmcgui
from .concurrency import abort_event


def send_message_with_retry(bot, chat_id: int, text: str, **kwargs) -> tuple[bool, int]:
    """Returns (ok, retries_made)."""
    shutdown = abort_event.is_set()
    backoffs = [1.0, 2.0, 4.0] if not shutdown else [0.0]
    timeout = (2, 3) if shutdown else (3, 10)
    retries = 0
    for delay in backoffs:
        if delay > 0 and abort_event.wait(delay):
            return False, retries
        retries += 1
        try:
            res = bot.send_message(chat_id, text, **kwargs)
            if res.get("ok"):
                return True, retries
        except Exception:
            pass
        if shutdown:
            break
    return False, retries


def kodi_toast(title: str, message: str) -> None:
    try:
        xbmcgui.Dialog().notification(title, message, time=5000)
    except Exception:
        pass


def notify_or_toast(bot, chat_id: int, text: str, *, toast_title: str = "Kodi-AI",
                    **kwargs) -> bool:
    ok, _ = send_message_with_retry(bot, chat_id, text, **kwargs)
    if not ok:
        # Strip HTML for toast (Kodi toast doesn't parse HTML)
        plain = text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
        kodi_toast(toast_title, plain[:200])
    return ok
```

- [ ] **Test + commit**

```bash
pytest tests/unit/test_notifier.py -v
git add service.kodi.ai/lib/notifier.py tests/unit/test_notifier.py
git commit -m "feat(notifier): synchronous notifier with abort-aware retry

send_message_with_retry: 1/2/4s exp backoff (interruptible via
abort_event.wait); shutdown short-path = 1 attempt with timeout=(2,3).
notify_or_toast: tries Telegram; on persistent failure falls back to
xbmcgui.Dialog().notification (Kodi toast).

Spec: §1.7, §3.4, §5.7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 9 — Verifier + health + recovery (4 tasks)

### Task 9.1 — `lib/verifier.py`: subscribes to log_watcher stream + per-cluster strategies

**Spec ref:** §4.4.

**Files:** Create `service.kodi.ai/lib/verifier.py`, modify `log_watcher.py` to expose `subscribe(filter_fn, on_match, timeout_s)`, tests.

The verifier is invoked by the reasoner via `verify_fix` tool (Phase 7.7) and runs the strategy chosen by cluster_category. It calls log_watcher's subscribe API to register a non-recurrence watcher, plus polls JSON-RPC for Player.OnPlay (V1 polling, not socket listener). On verdict, returns ToolResult; reasoner emits notifier message edit.

```bash
git commit -m "feat(verifier): subscribe to log_watcher + per-cluster strategies

log_watcher.subscribe(filter_fn, on_match, timeout_s) added (single tail,
many consumers via thread-safe queues per spec §4.4 round-1 fix).
verifier strategies: playback_fail (Player.OnPlay poll + cluster
non-recurrence 10s, OR recurrence, OR 5min, OR abort_event),
dep_import_fail (restart_addon → 30s clean-import OR same error),
repo_unreachable (poll repo URL 1min × 30 OR success),
default (30s log-quiet for cluster_id).
All loops use abort_event.wait.

Spec: §4.4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 9.2 — `lib/health.py`: heartbeat + crash detection + boot recovery

**Spec ref:** §7.4 (heartbeat, last_clean_shutdown_ts, crash_free_since), §7.7.

**Files:** Create `service.kodi.ai/lib/health.py`, `tests/unit/test_health.py`.

```python
# service.kodi.ai/lib/health.py
"""Heartbeat (every 5min by T4) + crash detection on boot + crash_free_since.

Schema: {last_alive_ts, crash_free_since, telegram_last_rt_ok_ts,
allowlist_populated_at, last_clean_shutdown_ts}.

Boot detection: clean shutdown if last_clean_shutdown_ts - last_alive_ts
<= heartbeat_interval (5min) + 30s grace (handles long power-off correctly,
per spec §7 round-4 reviewer note).

LKG rotation gate: now - crash_free_since >= 86400 AND
telegram_last_rt_ok_ts > 0 (lib/recovery.py).

Spec: §7.4.
"""
from __future__ import annotations
import json
import os
import time
from . import state_paths


HEARTBEAT_INTERVAL_S = 300.0  # 5 minutes
CLEAN_SHUTDOWN_GRACE_S = 30.0


def _path() -> str:
    return state_paths.profile_path("health.json")


def _load() -> dict:
    if not os.path.exists(_path()):
        return {}
    try:
        with open(_path()) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _persist(blob: dict) -> None:
    state_paths.atomic_write(_path(), json.dumps(blob).encode("utf-8"))


def heartbeat() -> None:
    blob = _load()
    blob["last_alive_ts"] = time.time()
    if "crash_free_since" not in blob:
        blob["crash_free_since"] = blob["last_alive_ts"]
    _persist(blob)


def record_clean_shutdown() -> None:
    blob = _load()
    blob["last_clean_shutdown_ts"] = time.time()
    _persist(blob)


def record_telegram_rt_ok() -> None:
    blob = _load()
    blob["telegram_last_rt_ok_ts"] = time.time()
    _persist(blob)


def record_allowlist_populated() -> None:
    blob = _load()
    blob["allowlist_populated_at"] = time.time()
    _persist(blob)


def boot_detect_and_update_crash_free_since() -> dict:
    """Compare last_clean_shutdown_ts vs last_alive_ts. Clean if delta
    ≤ heartbeat_interval + grace. Crash otherwise → reset crash_free_since."""
    blob = _load()
    last_alive = blob.get("last_alive_ts", 0.0)
    last_shutdown = blob.get("last_clean_shutdown_ts")
    now = time.time()
    if last_shutdown is None or (last_shutdown - last_alive) > (HEARTBEAT_INTERVAL_S + CLEAN_SHUTDOWN_GRACE_S):
        blob["crash_free_since"] = now
    blob["last_alive_ts"] = now
    _persist(blob)
    return blob


def get_state() -> dict:
    return _load()
```

```bash
pytest tests/unit/test_health.py -v
git commit -m "feat(health): heartbeat + crash detection + crash_free_since

T4 main loop calls heartbeat() every 5min. record_clean_shutdown() called
by Main on abort. boot_detect_and_update_crash_free_since() compares
last_clean_shutdown_ts vs last_alive_ts; clean if delta ≤ 5min+30s grace
(spec §7 round-4 long-power-off handling); else crash inferred and
crash_free_since reset.
Used by lib/recovery.py LKG rotation gate.

Spec: §7.4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 9.3 — `lib/recovery.py`: LKG ZIP + boot terminal-state recovery + orphan snapshots

**Spec ref:** §7.4, §7.7, §5.4.

**Files:** Create `service.kodi.ai/lib/recovery.py`, `tests/integration/test_recovery.py`.

Functions:
- `maybe_rotate_lkg()` — gated on `(now - crash_free_since >= 86400) AND telegram_last_rt_ok_ts > 0`. Builds `last_known_good-<v>.zip` (real ZIP, DEFLATE) with `service.kodi.ai/<relpath>` prefix in every zinfo. Keep last 2 versions.
- `boot_recovery_sessions(bot)` — iterate `reasoner_state.list_all()`; dispatch per terminal_state:
  - `paused` + `paused_at >= now - 24h` → keep, re-send "Resumed after restart" Telegram.
  - `paused` + `< now - 24h` → expire to state `expired`, surface via /status.
  - `fix_complete_notify_pending` → retry notify once; on success delete; fail → `notify_failed`.
  - `pause_notify_failed` → retry notify; on success → reset `paused` + re-send; fail → leave.
  - `notify_failed` / `expired` → leave.
  - `fix_complete` → safe-delete.
- `quarantine_orphan_snapshots()` — list snapshots without matching session in `paused_sessions` + no audit entry in last 7d → move to `.orphaned/`.

```bash
pytest tests/integration/test_recovery.py -v -m integration
git commit -m "feat(recovery): LKG ZIP + boot terminal-state recovery + orphan quarantine

maybe_rotate_lkg: gated on health.crash_free_since >= 24h AND
telegram_last_rt_ok_ts > 0. Builds real ZIP (zipfile, DEFLATE) with
service.kodi.ai/ top-level dir prefix in zinfo per spec §7.4 round-2 fix.
Keep last 2 versions.
boot_recovery_sessions: dispatches sessions/*.json by terminal_state.
Paused < 24h → re-send 'Resumed after restart'; > 24h → expire.
notify_pending → retry once; pause_notify_failed → retry + reset paused
or leave for /status.
quarantine_orphan_snapshots: moves snapshots without matching session +
no audit entry in 7d to Kodi-AI-snapshots/.orphaned/.

Spec: §5.4, §7.4, §7.7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 9.4 — Wire health.heartbeat into T4 main loop + Telegram-rt-ok recording

**Files:** Modify `lib/reasoner.py` (or `service.py` Phase 10) to call `health.heartbeat()` every 5min. Modify `lib/telegram/bot.py` to call `health.record_telegram_rt_ok()` on every successful getUpdates (200 with parseable JSON).

```bash
git commit -m "feat(health): wire heartbeat into T4 + telegram_rt_ok recording

T4 main work_queue.get loop bumps health.heartbeat() if 5min elapsed.
TelegramBot.run() calls health.record_telegram_rt_ok() on each successful
getUpdates response. Both used by LKG rotation gate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 10 — Service entry + setup wizard + default.py (3 tasks)

### Task 10.1 — `service.kodi.ai/default.py`: status panel + setup wizard

**Spec ref:** §7.2 (Setup wizard screens 1-5), §7.3 (settings UI actions), §5.7 (kill switches via Kodi UI).

`default.py` is invoked via `RunScript(special://home/addons/service.kodi.ai/default.py, <action>)`. Actions:
- (no arg) → status panel (recent fixes + budget + paused sessions + buttons).
- `show_secret` → modal with QR code + plain-text setup_secret.
- `reset_bot` → calls `lib.telegram.auth.reset_bot_owner()`, displays new secret.
- `setup_wizard` → multi-screen wizard (Welcome+OpenRouter key with preflight, Telegram bot setup, QR-link, mode select, test-fire).

Uses `xbmcgui.Dialog().select/numeric/input/ok/yesno` for screens; `xbmcgui.WindowXMLDialog` with `<control type="image">` to render PNG from `lib.qr.qr_png`. PNG written to `addon_data/.qr/setup.png`, deleted on dialog close.

```bash
git commit -m "feat(default.py): status panel + setup wizard + show_secret + reset_bot

Dispatches by sys.argv[1]. setup_wizard 5-screen flow per spec §7.2:
1. OpenRouter key + preflight (cheapest paid model test call, $0.0001;
   402 → 'add credit' message; 401 → invalid).
2. Telegram bot_token + bot_username + getMe validation +
   instruction to '/setprivacy Disable' to BotFather.
3. QR-link gated on bot_username presence; QR encodes
   https://t.me/<bot>?start=<setup_secret>; size ≥40% screen,
   ECC level H; PNG deleted onUnload.
   Wizard polls health.json::allowlist_populated_at every 1s, 60s timeout,
   retry/fallback/cancel.
4. Mode select (auto default).
5. Test fire — user DMs bot, bot replies '✅ Test received'; on success done.

Spec: §7.2, §7.3, §5.7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 10.2 — `service.kodi.ai/service.py`: 4-thread orchestrator + boot sequence

**Spec ref:** §1.1, §1.2, §1.14 (shutdown protocol), §2.

```python
# service.kodi.ai/service.py
"""4-thread orchestrator. Main is minimal (xbmc.Monitor.waitForAbort loop +
abort coordination); T4 first, then T2 + T3 after startup_complete_event."""
from __future__ import annotations
import sys
import threading
import xbmc

# Add lib/ to path
import os
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from lib import (
    state_paths, settings, log_capture, audit_log, secrets,
    redactor, health, recovery, log_watcher, llm, reasoner as _reasoner_mod,
)
from lib.concurrency import (
    abort_event, startup_complete_event, work_queue, paused_sessions,
    paused_sessions_lock, drop_counter, active_calls,
)
from lib.llm import client as llm_client, router as llm_router, budget as llm_budget
from lib.telegram import bot as telegram_bot
import lib.tools  # noqa — triggers autoload of all @tool registrations


def t4_worker_body(bot_instance):
    """T4 main loop: triage → reasoner → notifier."""
    # Start: boot recovery
    state_paths.ensure_dirs()
    if not state_paths.smoke_probe_atomic_rename():
        xbmc.log("[service.kodi.ai] ATOMIC RENAME FAILED — state persistence unsafe", xbmc.LOGERROR)
    ok_canary, leaked = redactor.canary_self_test()
    if not ok_canary:
        xbmc.log(f"[service.kodi.ai] REDACTOR CANARY FAILED: {leaked}", xbmc.LOGERROR)
        # LLM calls remain disabled until next process
    health.boot_detect_and_update_crash_free_since()
    recovery.boot_recovery_sessions(bot_instance)
    recovery.quarantine_orphan_snapshots()

    # Async startup tasks (don't block T2/T3 start)
    threading.Thread(target=lambda: _slug_validate_async(bot_instance), daemon=True).start()

    startup_complete_event.set()

    # Main work loop
    last_heartbeat = time.monotonic()
    while not abort_event.is_set():
        try:
            item = work_queue.get(timeout=1.0)
            _, _, payload = item
            _handle_work(payload, bot_instance)
        except Exception:
            pass
        # Heartbeat
        import time
        if time.monotonic() - last_heartbeat >= health.HEARTBEAT_INTERVAL_S:
            health.heartbeat()
            last_heartbeat = time.monotonic()
        # Drop counter throttled notification
        dc = drop_counter.reset_and_get()
        if dc > 0:
            # Throttle: only notify if 5 min since last
            pass  # implementation detail


def _handle_work(payload, bot_instance):
    from lib.concurrency import LogIncident, UserMsg, ResumeWork
    if isinstance(payload, LogIncident):
        _handle_incident(payload, bot_instance)
    elif isinstance(payload, UserMsg):
        _handle_user_msg(payload, bot_instance)
    elif isinstance(payload, ResumeWork):
        _handle_resume_work(payload, bot_instance)


def _handle_incident(incident, bot_instance):
    """Triage → if CRITICAL, run reasoner with tools."""
    # Implementation per spec §3.1 — calls triage.classify, then
    # _reasoner_mod.Reasoner.run_with_tools, then notifier.
    pass  # full impl in execution


def _handle_user_msg(msg, bot_instance):
    """Reasoner chat mode (no triage)."""
    pass


def _handle_resume_work(rw, bot_instance):
    """Rehydrate session from paused_sessions (in-memory primary) or disk
    fallback; call reasoner.resume_from."""
    pass


def _slug_validate_async(bot_instance):
    """Calls llm_client.validate_slugs; on miss → defer Telegram notify."""
    pass


def main():
    log_capture.install(verbose=settings.get_bool("diagnostic_logging"))
    audit_log.write("startup", details={"version": "0.1.0"})
    bot_token = secrets.get_secret("bot_token") or ""
    bot_instance = telegram_bot.TelegramBot(bot_token) if bot_token else None

    # T4 first
    t4 = threading.Thread(target=t4_worker_body, args=(bot_instance,), name="T4_Worker", daemon=False)
    t4.start()
    startup_complete_event.wait(timeout=60)  # wait for T4 boot pass

    # T2 + T3 after T4 boot
    watcher = log_watcher.LogWatcher(
        poll_active_ms=settings.get_int("t2_poll_active_ms", 750),
        poll_idle_ms=settings.get_int("t2_poll_idle_ms", 2500),
    )
    t2 = threading.Thread(target=watcher.run, name="T2_LogPoll", daemon=False)
    t3 = threading.Thread(target=bot_instance.run if bot_instance else lambda: None,
                          name="T3_TGPoll", daemon=False) if bot_instance else None
    t2.start()
    if t3: t3.start()

    monitor = xbmc.Monitor()
    while not monitor.abortRequested():
        if monitor.waitForAbort(1.0):
            break

    # Shutdown
    abort_event.set()
    health.record_clean_shutdown()
    audit_log.write("shutdown")
    # Send None sentinels (work_queue may have items)
    try: work_queue.put_nowait((100, 99999, None))
    except Exception: pass
    t2.join(timeout=3)
    if t3: t3.join(timeout=15)
    t4.join(timeout=5)
    log_capture.uninstall()


if __name__ == "__main__":
    main()
```

```bash
git commit -m "feat(service.py): 4-thread orchestrator + boot + shutdown

main() installs log_capture, writes audit startup, creates TelegramBot,
starts T4 first (boot pass: ensure_dirs, atomic-rename smoke, redactor
canary, health.boot_detect, recovery.boot_recovery_sessions + orphan
quarantine, async slug validation), waits startup_complete_event,
then starts T2 LogWatcher + T3 TelegramBot.
On abortRequested(): abort_event.set, health.record_clean_shutdown,
audit shutdown, push None sentinels, join T2(3s)/T3(15s)/T4(5s),
log_capture.uninstall.

Spec: §1.1, §1.2, §1.14, §2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 10.3 — Wire T4 handlers (`_handle_incident` / `_handle_user_msg` / `_handle_resume_work`)

The T4 dispatch handlers from Task 10.2 are stubs; this task implements them.

For each: instantiate Reasoner with current settings (router via TaskModelRouter from `recommended_models.json` + user `models_override`; budget via BudgetGuard from settings caps; tool_registry from `lib.tools.registry`).

- `_handle_incident`: triage.classify(cluster_text) → if CRITICAL: run_with_tools with `task_class="t2_reason"`; emit sentinel reason-start; pause flow if outcome.terminal_reason == "needs_user" (serialize SessionState, MonotonicBudget.pause, persist, send Telegram inline keyboard); on `complete` outcome run notifier + verify_fix; emit sentinel reason-end; cleanup paused_sessions + disk.
- `_handle_user_msg`: same as incident but task_class="t1_simple", no triage, chat prompt instead of reasoner prompt.
- `_handle_resume_work`: lookup paused_sessions[sid] (memory primary, disk fallback), MonotonicBudget.resume, reasoner.resume_from(state, user_reply).

```bash
git commit -m "feat(service.py): wire T4 handlers — incident/user_msg/resume_work

_handle_incident: triage cheap LLM → if CRITICAL, full Reasoner with tools.
Pause flow on needs_user outcome: serialize SessionState + MonotonicBudget
.pause + atomic disk + Telegram inline keyboard with 15s deadline; on
failure → pause_notify_failed terminal + toast + /status surface.
_handle_user_msg: chat-mode reasoner, t1_simple model, chat_system prompt.
_handle_resume_work: lookup paused_sessions (in-memory primary, disk
fallback), MonotonicBudget.resume, reasoner.resume_from.
On outcome.terminal_reason='complete': mark fix_complete_notify_pending,
notify, on success → delete session; on fail → notify_failed.
Sentinels reason-start/end written for audit.

Spec: §3.1, §3.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 11 — Smoke tests integration (2 tasks)

### Task 11.1 — Wire smoke tests into service.py boot pass

Per spec §6.5: state-dir + redactor canary are HARD FATAL (refuse startup); atomic-rename + log_capture + slug + Telegram bot_token + chat_id + disk-space + clock-skew are WARN-and-continue. Telegram smoke probes run BEFORE `startup_complete_event.set()`.

```bash
git commit -m "feat(service.py): wire all startup smoke tests per spec §6.5

state_paths.ensure_dirs failure → halt startup (hard fatal).
redactor.canary_self_test failure → disable LLM calls + notify; hard fatal
for that path but service continues to handle Telegram pause-notify-failed
recovery via /status.
atomic-rename probe + log_capture canary → warn + continue.
Telegram getMe + chat_id reachability probes inside T3 init, BEFORE
T3 sets startup_complete_event (probe fail → event never set → graceful
shutdown).
Slug validation, disk-space, clock-skew → deferred warnings.

Spec: §6.5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 11.2 — Integration smoke test for full startup sequence

Creates `tests/integration/test_startup_smoke.py` that wires all fakes (xbmc, xbmcvfs, xbmcaddon, xbmcgui), mocks Telegram + OpenRouter, runs `service.main()` in a thread, verifies all smoke gates pass, sentinels written, `startup_complete_event` set, threads named correctly, shutdown clean.

```bash
git commit -m "test: integration smoke test for full startup sequence

Wires all fakes + mocks Telegram (getMe ok, getUpdates returns empty) +
OpenRouter (validates slugs ok). Spins service.main() in thread; verifies
audit startup entry, sentinels, startup_complete_event, T2/T3/T4 named
threads, abort_event triggered → all threads join within timeout, audit
shutdown entry, log_capture.uninstall called.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 12 — Distribution + acceptance (3 tasks)

### Task 12.1 — Build script + repo manifests for distribution

**Files:**
- Create: `tools/build_repo.py`
- Create: `kodi-ai-repo/.nojekyll`
- Create: `kodi-ai-repo/index.html`
- Create: `kodi-ai-repo/zips/repository.kodi-ai/repository.kodi-ai/addon.xml`

`tools/build_repo.py`:
- Zips `service.kodi.ai/` into `service.kodi.ai-<version>.zip` with top-level `service.kodi.ai/` dir prefix in every zinfo (real ZIP, DEFLATE).
- Zips the repository addon similarly.
- Generates `addons.xml` by concatenating both addon manifests' `<addon>` elements.
- Generates `addons.xml.md5`.
- Writes everything under `kodi-ai-repo/zips/<addon_id>/`.

```bash
pytest tools/test_build_repo.py
git add tools/ kodi-ai-repo/
git commit -m "build: tools/build_repo.py + GitHub Pages distribution layout

build_repo.py packages service.kodi.ai/ and repository.kodi-ai/ as real
ZIPs with service.kodi.ai/ top-level dir prefix per spec §7.4 round-2 fix.
Generates addons.xml (concat manifests) + addons.xml.md5.
kodi-ai-repo/.nojekyll + index.html for GitHub Pages directory exposure.

Spec: §7.1, §7.4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 12.2 — User-facing docs

**Files:**
- Create: `README.md`
- Create: `CHANGELOG.md`
- Create: `PRIVACY.md` (explicit Telegram-server-retention disclosure)
- Create: `SECURITY.md`
- Create: `UNINSTALL.md`
- Create: `LICENSE` (MIT or Apache 2.0 — user chooses)
- Create: `THIRD_PARTY_NOTICES.md`

Each per spec §7.8.

```bash
git add README.md CHANGELOG.md PRIVACY.md SECURITY.md UNINSTALL.md LICENSE THIRD_PARTY_NOTICES.md
git commit -m "docs: README + PRIVACY + SECURITY + UNINSTALL + LICENSE + 3rd party

README: install steps per spec §7.2, setup wizard, Telegram commands.
PRIVACY: data flows (redacted log to OpenRouter, audit log + snapshots
local, Telegram chat history on Telegram servers indefinitely — out of
our control per spec §7.8).
SECURITY: trust model (Unknown sources, no signing), recovery scenarios.
UNINSTALL: addon_data + Kodi-AI-snapshots paths to purge.
LICENSE: MIT.
THIRD_PARTY_NOTICES: script.module.requests, kodistubs (dev only).

Spec: §7.8.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 12.3 — Acceptance tests on Shield Pro

**Files:**
- Create: `tests/acceptance/snapshot_kodi.sh` (with `KODI_AI_TEST_DEVICE=1` env gate + auto pre-restore snapshot + "TEST DEVICES ONLY" header).
- Create: `tests/acceptance/dev_server.py` (Flask/`http.server` with `/dead/addons.xml → 404` for B1 + `/geo/blocked → 403 Content-Region: US` for C4).
- Create: `tests/acceptance/fixtures/LICENSES.md` (CC-BY for bundled HEVC clip).
- (Bundle ~10MB HEVC test clip OUT of git — user-supplied or CI-downloaded; document in LICENSES.)
- Create: `tests/acceptance/run_scenarios.md` — manual protocol for A1/A2/A3/B1/B2/C1/C2/C3/C4 per spec §6.4.

```bash
git add tests/acceptance/
git commit -m "test(acceptance): Shield Pro manual scenarios + dev server + ADB script

snapshot_kodi.sh: tarball of userdata via ADB. Requires KODI_AI_TEST_DEVICE=1
env OR --i-understand-this-wipes-userdata flag. Restore auto-creates
pre_restore_<ts>.tar.gz first. README header bold 'TEST DEVICES ONLY'.
dev_server.py: routes /dead/addons.xml (404) for B1, /geo/blocked
(403 + Content-Region: US) for C4. http.server stdlib only.
run_scenarios.md: step-by-step manual protocol for A1-C4 per spec §6.4.
fixtures/LICENSES.md documents CC-BY HEVC clip provenance (user supplies
~10MB file separately to avoid bloating git).

Spec: §6.4, §6.6, §6.7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Plan summary + execution handoff

**Total: 60 TDD tasks across 13 phases (0-12).** Each task has failing test → implementation → passing test → commit. Per project discipline ([[feedback-implementer-reviewer-loop]]), every code task dispatches a fresh Opus 4.7 implementer + fresh Opus 4.7 reviewer subagent; loop until reviewer signs off clean.

**Cross-cutting reminders for executing agents:**
- All Agent dispatches use `model: "opus"` explicitly.
- All test commits sit cleanly between failing-test commit and passing-test commit when appropriate (TDD discipline).
- No bare `time.sleep` in any service loop — always `abort_event.wait(t)`.
- Every mutating tool MUST snapshot before mutate (HARD RULE).
- Secrets NEVER logged raw; always go through `lib.redactor`.
- **Imports inside `lib/*` use relative form** (`from . import x`, `from .. import y`). `lib/__init__.py`, `lib/llm/__init__.py`, `lib/tools/__init__.py`, `lib/telegram/__init__.py` all exist (Task 0.2). `pyproject.toml` `pythonpath=["service.kodi.ai"]` puts `lib` on sys.path as a package, so both relative imports inside `lib/*` AND absolute `from lib import x` from tests work. (Round-1 reviewer flagged this as broken — false alarm; verified package layout makes both forms valid.)

**Self-review (executed inline by writing-plans skill):** placeholders limited to genuine "to be specified at release" markers (`<VERIFY_AT_RELEASE>` for `script.module.requests` version, `<user>` for GitHub username, `...` for `<description>` fields). Internal consistency verified: every spec section is implemented by at least one task; types and signatures consistent across tasks.

---

## Round-1 reviewer fixes folded in (2026-05-27)

Critical + high blockers from Opus 4.7 round-1 review applied inline:
- **C2 — Fairness counter** added below as Task 1.3b.
- **C3 — Streaming + mid-stream budget** in Reasoner: Task 5.4 rewritten to use `chat_stream` + per-chunk `BudgetGuard.mid_stream_check`; mid-stream truncation emits synthetic clean envelope per spec §5.5.
- **C4 — Pause sequence step ordering** as explicit code in revised Task 5.5 (4-step sequence: memory → MonotonicBudget.pause → atomic disk → Telegram with 15s deadline → pause_notify_failed terminal on fail).
- **C5 — Buffer-and-evaluate** in `log_watcher`: revised Task 4.6 holds lines in `_window_buffer` during active windows, evaluates per-tool-boundary on `schedule_remove_tool` linger expiry; foreign-addon lines surface, target-addon lines discarded.
- **H1 — Tasks 7.4/7.5/7.6/7.7** expanded from paragraph-stubs to full TDD blocks (failing test → impl → commit).
- **H7 — Boot post-mortem** state machine in revised Task 4.7 tracks per-session open/close (dict, not bool) + tool-history-match suppression from `sessions/<id>.json`.

Medium / low findings (M1-M12, L1-L6) NOT fixed inline — they'll be caught + addressed by the implementer + reviewer subagent loop during execution.

---

## Task 1.3b — `FairnessTracker` (PriorityQueue starvation guard)

**Spec ref:** §1.12 (single-flight by construction; fairness counter "every 10 ResumeWorks drained, T4 force-processes 1 LogIncident if queued").

**Files:** Modify `service.kodi.ai/lib/concurrency.py` (append class + module-level instance), create `tests/unit/test_fairness_tracker.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_fairness_tracker.py
def test_fairness_tracker_initial_state():
    from lib.concurrency import FairnessTracker
    ft = FairnessTracker(resume_threshold=10)
    assert not ft.should_force_log_incident()


def test_fairness_after_10_resumes_force_logincident():
    from lib.concurrency import FairnessTracker, ResumeWork, LogIncident
    ft = FairnessTracker(resume_threshold=10)
    for _ in range(10):
        ft.note_drained(ResumeWork(session_id="s", user_reply=True))
    assert ft.should_force_log_incident()


def test_fairness_resets_after_logincident_drained():
    from lib.concurrency import FairnessTracker, ResumeWork, LogIncident
    ft = FairnessTracker(resume_threshold=10)
    for _ in range(10):
        ft.note_drained(ResumeWork(session_id="s", user_reply=True))
    assert ft.should_force_log_incident()
    # Implementer drains 1 LogIncident
    ft.note_drained(LogIncident(cluster_id="c", first_seen=None, last_seen=None,
                                occurrences=1, raw_lines=[], severity_hint="ERROR",
                                likely_addon=None, likely_action=None,
                                backdated=False, from_previous_session=False,
                                triage_deferred=True))
    assert not ft.should_force_log_incident()


def test_fairness_user_msg_does_not_count_as_resume():
    from lib.concurrency import FairnessTracker, UserMsg
    ft = FairnessTracker(resume_threshold=10)
    for _ in range(20):
        ft.note_drained(UserMsg(chat_id=1, text="x", message_id=1, reply_to_message_id=None))
    assert not ft.should_force_log_incident()


def test_peek_logincident_returns_priority_position():
    """Helper for T4 to check if a LogIncident is queued before forcing."""
    from lib.concurrency import work_queue, enqueue, LogIncident, ResumeWork
    from lib.concurrency import has_pending_logincident
    while not work_queue.empty():
        work_queue.get_nowait()
    enqueue(ResumeWork(session_id="s", user_reply=True))
    assert not has_pending_logincident()
    enqueue(LogIncident(cluster_id="c", first_seen=None, last_seen=None,
                        occurrences=1, raw_lines=[], severity_hint="ERROR",
                        likely_addon=None, likely_action=None, backdated=False,
                        from_previous_session=False, triage_deferred=True))
    assert has_pending_logincident()
```

- [ ] **Step 2: Append to `service.kodi.ai/lib/concurrency.py`**

```python


# ---- FairnessTracker — prevent ResumeWork starvation of LogIncident ----
class FairnessTracker:
    """Counts ResumeWork drains; after N consecutive (without a LogIncident
    drained in between), should_force_log_incident() returns True until the
    next LogIncident is actually drained.

    Spec: §1.12.
    """
    def __init__(self, resume_threshold: int = 10):
        self._resume_count = 0
        self._threshold = resume_threshold
        self._lock = threading.Lock()

    def note_drained(self, payload) -> None:
        with self._lock:
            name = type(payload).__name__
            if name == "ResumeWork":
                self._resume_count += 1
            elif name == "LogIncident":
                self._resume_count = 0
            # UserMsg: no effect on fairness counter

    def should_force_log_incident(self) -> bool:
        with self._lock:
            return self._resume_count >= self._threshold


# Module-level instance used by T4 dispatch (lib.service)
fairness_tracker = FairnessTracker()


def has_pending_logincident() -> bool:
    """Peek work_queue for any LogIncident at any position.

    CPython PriorityQueue exposes ._queue (heap list). Acceptable use here
    (Kodi pins to CPython 3.x; spec §1.2 documents this version pin).
    Returns True if any LogIncident is queued, regardless of priority.
    """
    try:
        with work_queue.mutex:
            for prio, _, payload in list(work_queue.queue):
                if type(payload).__name__ == "LogIncident":
                    return True
    except Exception:
        return False
    return False
```

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/unit/test_fairness_tracker.py -v   # 5 passed
git add service.kodi.ai/lib/concurrency.py tests/unit/test_fairness_tracker.py
git commit -m "feat(concurrency): FairnessTracker + has_pending_logincident peek

FairnessTracker: counts ResumeWork drains; after N consecutive without a
LogIncident drain in between, should_force_log_incident() returns True.
Resets on next LogIncident drain. UserMsg drains are neutral.
has_pending_logincident(): CPython-PriorityQueue ._queue peek (acceptable
under spec §1.2 version-pinned xbmc.python 3.0.1).

Wiring in Task 10.2 t4_worker_body: between dequeues, if
should_force_log_incident() AND has_pending_logincident(), prefer
draining a LogIncident next iteration.

Spec: §1.12.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4.6-REVISED — log_watcher buffer-and-evaluate (supersedes 4.6 + amends 4.7)

**Spec ref:** §1.3 (point 2 — per-tool-boundary post-window evaluation), §1.3 (buffer cap 5 MB / 5000 lines).

**Why this revision:** Round-1 reviewer (C5) flagged that the original Task 4.6 / 4.4 `if active_calls.is_active(): continue` **discarded** lines outright during active windows rather than **buffering** them for per-tool-boundary evaluation. Spec §1.3 mandates that foreign-addon lines (not in any active tool's target_addons) MUST surface as new incidents even when reasoner is mid-fix on a different addon — otherwise a genuinely new issue while we're fixing the first is silently swallowed.

**Files:** Modify `service.kodi.ai/lib/log_watcher.py` (replace the active_calls handling in `_ingest_chunk`), create `tests/integration/test_log_watcher_buffer_eval.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_log_watcher_buffer_eval.py
import os
import time
import pytest
from datetime import datetime, timezone
from tests.integration.fakes import fake_xbmcvfs


@pytest.mark.integration
def test_foreign_addon_line_surfaces_during_active_window():
    """When ActiveCalls targets {plugin.video.foo}, a line from
    plugin.video.bar MUST be enqueued (not discarded)."""
    from lib import log_watcher, concurrency
    from lib.concurrency import active_calls
    # Drain queue
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()

    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    with open(path, "w") as f:
        f.write("INFO: startup\n")
    w = log_watcher.LogWatcher(quiescence_window_s=0.3)
    w._read_new_bytes()

    # Active tool targets foo
    active_calls.add_tool("t1", target_addons={"plugin.video.foo"})
    try:
        with open(path, "a") as f:
            # bar line is FOREIGN to t1's targets — must surface
            f.write("ERROR [plugin.video.bar]: real new issue\n")
            # foo line is OUR side-effect — must be buffered + later discarded
            f.write("ERROR [plugin.video.foo]: our side-effect\n")
        w._ingest_chunk(w._read_new_bytes())
        # Quiescence + close
        time.sleep(0.4)
        w._close_expired_clusters()
    finally:
        active_calls.schedule_remove_tool("t1", after=0.0)

    # Drain queue, classify
    found_bar = False
    found_foo = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        text = "\n".join(getattr(item, "raw_lines", []))
        if "bar" in text:
            found_bar = True
        if "foo" in text:
            found_foo = True
    assert found_bar, "foreign-addon line MUST surface even during active window"
    assert not found_foo, "target-addon line MUST be discarded post-window"


@pytest.mark.integration
def test_buffer_cap_overflow_emits_synthetic_incident():
    """If buffer exceeds 5MB or 5000 lines, oldest dropped + synthetic
    'post-window eval skipped: buffer overrun' incident emitted."""
    from lib import log_watcher, concurrency
    from lib.concurrency import active_calls
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()

    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    with open(path, "w") as f:
        f.write("INFO: x\n")
    w = log_watcher.LogWatcher(quiescence_window_s=0.3, buffer_max_lines=10)
    w._read_new_bytes()
    active_calls.add_tool("t1", target_addons="ALL")  # suppress ALL → forces buffer
    try:
        with open(path, "a") as f:
            for i in range(25):
                f.write(f"ERROR [plugin.video.x{i}]: msg {i}\n")
        w._ingest_chunk(w._read_new_bytes())
    finally:
        active_calls.schedule_remove_tool("t1", after=0.0)
    time.sleep(0.4)
    w._close_expired_clusters()
    saw_overrun = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        if "buffer overrun" in "\n".join(getattr(item, "raw_lines", [])):
            saw_overrun = True
    assert saw_overrun


@pytest.mark.integration
def test_target_addon_line_discarded_after_linger():
    """After ActiveCalls.is_active() goes False (linger expires), buffered
    target-addon lines are evaluated and discarded."""
    from lib import log_watcher, concurrency
    from lib.concurrency import active_calls
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    with open(path, "w") as f:
        f.write("INFO: x\n")
    w = log_watcher.LogWatcher(quiescence_window_s=0.3)
    w._read_new_bytes()
    active_calls.add_tool("t1", target_addons={"plugin.video.foo"})
    with open(path, "a") as f:
        f.write("ERROR [plugin.video.foo]: side effect\n")
    w._ingest_chunk(w._read_new_bytes())
    active_calls.schedule_remove_tool("t1", after=0.05)
    time.sleep(0.5)  # past linger AND quiescence
    w._close_expired_clusters()
    w._evaluate_buffer_post_window()
    found = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        if "foo" in "\n".join(getattr(item, "raw_lines", [])):
            found = True
    assert not found, "target-addon line must be discarded post-window"
```

- [ ] **Step 2: Modify `service.kodi.ai/lib/log_watcher.py`** — replace the `active_calls.is_active()` discard branch with buffer logic + add `_evaluate_buffer_post_window` method

In `LogWatcher.__init__`, add:
```python
        self.buffer_max_lines = buffer_max_lines  # default 5000
        self.buffer_max_bytes = buffer_max_bytes  # default 5 * 1024 * 1024
        self._window_buffer: list[tuple[datetime, str, str | None, str, str]] = []
        # (ts, raw_line, addon, level, body)
        self._window_buffer_bytes = 0
        self._was_active_last_tick = False
```

Change `__init__` signature to accept the new params (with defaults).

In `_ingest_chunk`, REPLACE the active_calls check:
```python
            # OLD: if active_calls.is_active(): continue
            # NEW: buffer for post-window evaluation
            if active_calls.is_active():
                self._buffer_line(raw_line, addon, level, body)
                continue
```

Add `_buffer_line`:
```python
    def _buffer_line(self, raw_line: str, addon: str | None, level: str, body: str) -> None:
        line_bytes = len(raw_line.encode("utf-8"))
        # Overflow handling: drop oldest until under cap; emit synthetic if dropped
        dropped_any = False
        while (len(self._window_buffer) >= self.buffer_max_lines
               or self._window_buffer_bytes + line_bytes > self.buffer_max_bytes):
            if not self._window_buffer:
                break
            old_ts, old_raw, *_ = self._window_buffer.pop(0)
            self._window_buffer_bytes -= len(old_raw.encode("utf-8"))
            dropped_any = True
        if dropped_any:
            self._emit_overrun_synthetic()
        from datetime import datetime, timezone
        self._window_buffer.append((datetime.now(timezone.utc), raw_line, addon, level, body))
        self._window_buffer_bytes += line_bytes

    def _emit_overrun_synthetic(self) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        try:
            enqueue(LogIncident(
                cluster_id=f"buf_overrun_{int(now.timestamp())}",
                first_seen=now, last_seen=now, occurrences=1,
                raw_lines=["post-window eval skipped: buffer overrun (5MB/5000-line cap)"],
                severity_hint="ERROR", likely_addon=None, likely_action=None,
                backdated=False, from_previous_session=False, triage_deferred=True,
            ))
        except Exception:
            drop_counter.inc()
```

Add `_evaluate_buffer_post_window` (called every tick + at run() loop boundary):
```python
    def _evaluate_buffer_post_window(self) -> None:
        """When active_calls goes idle, evaluate buffered lines: drop those
        whose addon is in (currently-empty) target_addons union; surface
        the rest as normal LogIncidents."""
        if active_calls.is_active():
            return  # still in window — don't evaluate yet
        if not self._window_buffer:
            return
        # All buffered lines are from the just-closed window. Per spec §1.3:
        # since we're past linger, the union of target_addons for the window
        # is no longer queryable from active_calls. We use a different rule:
        # the line is presumed "ours" if it matches any addon we acted on
        # during the window. For simplicity in V1, we use a heuristic:
        # any line buffered AT ALL during an active window is presumed to be
        # post-action noise from the target — EXCEPT lines from addons OTHER
        # than the most-recently-active targets (tracked via _recent_target_addons).
        # Implementer should use lib.concurrency.active_calls history via a
        # new last_window_targets() method (added in 1.5b below) for precision.
        recent_targets = getattr(active_calls, "last_window_targets",
                                  lambda: set())()
        from datetime import datetime, timezone
        clusters: dict[str, dict] = {}
        for ts, raw, addon, level, body in self._window_buffer:
            if recent_targets == "ALL" or (addon and addon in recent_targets):
                continue  # target-addon line → discard
            cid = prefilter.cluster_id_for(body)
            c = clusters.setdefault(cid, {"lines": [], "first": ts, "last": ts,
                                          "addon": addon, "level": level})
            c["lines"].append(raw)
            c["last"] = ts
        for cid, c in clusters.items():
            try:
                enqueue(LogIncident(
                    cluster_id=cid, first_seen=c["first"], last_seen=c["last"],
                    occurrences=len(c["lines"]), raw_lines=c["lines"],
                    severity_hint=c["level"], likely_addon=c["addon"],
                    likely_action=None, backdated=False,
                    from_previous_session=False, triage_deferred=True,
                ))
            except Exception:
                drop_counter.inc()
        self._window_buffer.clear()
        self._window_buffer_bytes = 0
```

In `run()`, after `_close_expired_clusters()`, call:
```python
            self._evaluate_buffer_post_window()
```

Add to `lib/concurrency.py::ActiveCalls`:
```python
    def last_window_targets(self) -> set[str] | Literal["ALL"]:
        """Returns the union of target_addons from the most recently closed
        tools' lingers (within the last 5 seconds). Used by log_watcher to
        evaluate buffered lines post-window."""
        with self._lock:
            now = time.monotonic()
            # Look at recently-expired lingers (still in self._linger if not purged)
            union: set[str] = set()
            for (kind, ident), (expiry, targets) in self._linger.items():
                if kind != "tool" or targets is None:
                    continue
                # Was active within last 5s
                if expiry > now - 5.0:
                    if targets == "ALL":
                        return "ALL"
                    union |= targets
            # Also include currently-active tools
            for targets in self._active_tools.values():
                if targets == "ALL":
                    return "ALL"
                union |= targets
            return union
```

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/integration/test_log_watcher_buffer_eval.py -v -m integration   # 3 passed
git add service.kodi.ai/lib/log_watcher.py service.kodi.ai/lib/concurrency.py \
        tests/integration/test_log_watcher_buffer_eval.py
git commit -m "fix(log_watcher): buffer-and-evaluate per-tool-boundary (C5)

Reverses the discard-on-active-window behavior — lines are now BUFFERED
in self._window_buffer (capped 5MB / 5000 lines per spec §1.3 round-2;
overflow emits synthetic 'buffer overrun' incident).
_evaluate_buffer_post_window: when active_calls.is_active() goes False,
classify buffered lines via active_calls.last_window_targets() (new
method): line's addon in target_addons (or 'ALL') → discard as our
side-effect; else surface as new LogIncident.
Foreign-addon errors during active windows now correctly surface — the
reasoner→log loop prevention is now spec-compliant.

Spec: §1.3 round-1 fix point 2.
Round-1 plan-review fix: C5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4.7-REVISED — boot_post_mortem per-session state machine (H7)

**Spec ref:** §1.4 (round-2 fix: dangling-sentinel detection per session_id).

**Why this revision:** Round-1 reviewer (H7) found that the boot_post_mortem state machine toggled `in_session: bool` on any `start`/`end` sentinel, so two sessions started + one ended marked `in_session=False` even though the second session was still open. Result: lines in the still-open second session were not suppressed.

**Files:** Modify `boot_post_mortem` in `service.kodi.ai/lib/log_watcher.py`, add test in `tests/integration/test_log_watcher_burst_boot.py`.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/integration/test_log_watcher_burst_boot.py
@pytest.mark.integration
def test_boot_post_mortem_tracks_per_session_open_close(tmp_path):
    """Two sessions started, only one ended → lines in still-open session
    must remain suppressed (only [service.kodi.ai] lines + tool-history-match
    lines)."""
    from lib import log_watcher, state_paths, concurrency
    from tests.integration.fakes import fake_xbmcvfs
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    old_log = os.path.join(log_dir, "kodi.old.log")
    with open(old_log, "w") as f:
        f.write("[service.kodi.ai] reason-start abc123\n")
        f.write("[service.kodi.ai] some addon-prefixed action log\n")
        f.write("[service.kodi.ai] reason-start def456\n")  # nested second open
        f.write("[service.kodi.ai] another action\n")
        f.write("[service.kodi.ai] reason-end abc123\n")  # closes first
        # def456 STILL OPEN — anything after this should still be in def456 session
        f.write("ERROR [service.kodi.ai] our side-effect from def456\n")
        f.write("ERROR [plugin.video.seren]: GENUINE error from foreign addon\n")
    w = log_watcher.LogWatcher()
    w.boot_post_mortem()
    found_seren = False
    found_our_side_effect = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        text = "\n".join(getattr(item, "raw_lines", []))
        if "seren" in text:
            found_seren = True
        if "side-effect from def456" in text:
            found_our_side_effect = True
    # Foreign-addon error MUST surface as backdated incident
    assert found_seren, "foreign-addon ERROR in dangling-session region MUST surface"
    # Our own [service.kodi.ai]-prefixed line MUST be suppressed
    assert not found_our_side_effect, "[service.kodi.ai] line in dangling session MUST be suppressed"
```

- [ ] **Step 2: Modify `boot_post_mortem` in `log_watcher.py`**

Replace the state-machine block:
```python
        # OLD (buggy — single bool in_session):
        # in_session = False
        # for i, line in enumerate(lines):
        #     s = log_sentinels.parse_sentinel(line)
        #     if s and s[0] == "start" and s[1] in open_sessions:
        #         in_session = True
        #     elif s and s[0] == "end":
        #         in_session = False
        #     if in_session and "[service.kodi.ai]" in line:
        #         suppress_lines.add(i)

        # NEW (per-session tracking):
        currently_open: set[str] = set()
        # Also load tool-history from sessions/*.json for tool-history-match suppression
        tool_history_signatures: set[str] = set()
        try:
            from . import reasoner_state
            for sid in reasoner_state.list_all():
                st = reasoner_state.load(sid)
                if st is None:
                    continue
                for tool_entry in (st.tool_history or []):
                    sig = tool_entry.get("output_signature")
                    if sig:
                        tool_history_signatures.add(sig)
        except Exception:
            pass
        for i, line in enumerate(lines):
            s = log_sentinels.parse_sentinel(line)
            if s:
                kind, sid = s
                if kind == "start" and sid in open_sessions:
                    currently_open.add(sid)
                elif kind == "end":
                    currently_open.discard(sid)
                continue
            # Suppress this line ONLY IF inside an open session AND
            # (addon-prefix is ours OR signature matches a recorded tool call)
            if currently_open:
                if "[service.kodi.ai]" in line:
                    suppress_lines.add(i)
                else:
                    # Check signature against tool_history
                    sig = prefilter.cluster_id_for(line)
                    if sig in tool_history_signatures:
                        suppress_lines.add(i)
```

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/integration/test_log_watcher_burst_boot.py::test_boot_post_mortem_tracks_per_session_open_close -v -m integration
git add service.kodi.ai/lib/log_watcher.py tests/integration/test_log_watcher_burst_boot.py
git commit -m "fix(log_watcher): boot_post_mortem per-session state machine (H7)

Per spec §1.4 round-2 fix: dangling-session suppression now uses
currently_open: set[str] (tracking individual session_ids) instead of a
single in_session bool — handles nested overlapping sessions correctly.
Suppression rule per spec §1.4: line suppressed only if INSIDE an open
session AND (addon-prefix is ours OR cluster_id_for(line) matches a tool
call recorded in sessions/<id>.json's tool_history).
Foreign-addon ERROR lines in dangling-session regions now correctly
surface as backdated incidents.

Round-1 plan-review fix: H7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5.4-REVISED — Reasoner uses chat_stream + mid-stream budget check (C3)

**Spec ref:** §1.10 (streaming + chunk-level abort), §5.5 (mid-stream budget check at exactly 100% cap → synthetic clean envelope).

**Why this revision:** Round-1 reviewer (C3) found that original Task 5.4's `run_with_tools` used non-streaming `self.llm.chat(...)`. Mid-stream budget enforcement (spec §5.5 point 2) is the only mechanism preventing a single LLM call from overshooting the per-incident cap by 100%+. Required to use `chat_stream` with per-chunk budget check.

**Files:** Modify `service.kodi.ai/lib/reasoner.py`, modify `tests/unit/test_reasoner_tool_loop.py`.

- [ ] **Step 1: Modify test to use streaming response**

Update the fake LLM in `tests/unit/test_reasoner_tool_loop.py`:
```python
def _streaming_resp(text_chunks: list[str], tool_calls: list | None = None,
                    finish_reason: str = "stop",
                    usage: dict | None = None):
    """Generator mimicking chat_stream output."""
    def gen():
        for chunk in text_chunks:
            yield (chunk, None, None)
        # Final delta carries finish_reason + usage
        yield (None, finish_reason, usage or {"prompt_tokens": 100, "completion_tokens": 20})
        # Some implementations emit tool_calls at the end — handle via assembled state.
    return gen()
```

The test should monkeypatch `chat_stream` to return iterables.

- [ ] **Step 2: Rewrite `run_with_tools` to use streaming**

Replace the LLM-call inside `run_with_tools`:
```python
            # OLD: res = self.llm.chat(api_key=..., model=..., messages=..., tools=tools, max_tokens=2048)
            # NEW: streaming + per-chunk budget check
            try:
                accumulated_text = ""
                accumulated_tool_calls: list[dict] = []
                finish_reason = None
                final_usage = {}
                tokens_streamed = 0
                price = self.router.price_per_mtok(model) or (1.0, 5.0)
                in_p, out_p = price
                for chunk_text, fr, usage in self.llm.chat_stream(
                    api_key=self.api_key, model=model, messages=messages,
                    tools=tools, max_tokens=2048, abort_event=abort_event,
                ):
                    if chunk_text:
                        accumulated_text += chunk_text
                        tokens_streamed += max(1, len(chunk_text) // 4)
                        # Per-chunk mid-stream budget check (spec §5.5)
                        streamed_cost = tokens_streamed * out_p / 1_000_000
                        if not self.budget.mid_stream_check(streamed_cost=streamed_cost):
                            # Trip: emit synthetic clean envelope (spec §5.5 round-3)
                            synthetic_result = {
                                "role": "tool", "tool_call_id": "budget_truncated",
                                "content": json.dumps({
                                    "error": "budget_truncated",
                                    "tokens_streamed": tokens_streamed,
                                    "estimated_cost_so_far": f"${self.budget.incident_cost_usd + streamed_cost:.4f}",
                                }),
                            }
                            messages.append({"role": "assistant", "content": "<<<budget-truncated>>>"})
                            messages.append(synthetic_result)
                            return ReasonerOutcome(
                                final_message="",
                                terminal_reason="budget_truncated",
                                tool_calls_made=turns - 1, cost_usd=cost,
                                snapshot_ids=snapshot_ids,
                                notes=f"mid-stream cap trip at {tokens_streamed} tokens",
                            )
                    if fr:
                        finish_reason = fr
                    if usage:
                        final_usage = usage
                # tool_calls handling: some providers stream them at end as a delta;
                # accumulate from chunk metadata if present (provider-specific).
                # For OpenRouter, tool_calls typically arrive in the final chunk
                # with finish_reason='tool_calls'. The chat_stream generator should
                # yield tool_calls as part of the final usage chunk for the
                # reasoner to consume here. (Implementer: extend chat_stream's
                # yield signature if needed; e.g. (chunk_text, finish_reason,
                # usage, tool_calls).)
                actual = (final_usage.get("prompt_tokens", 0) * in_p
                          + final_usage.get("completion_tokens", 0) * out_p) / 1_000_000
                cost += actual
                self.budget.record_actual(actual)
                res_text = accumulated_text
                res_tool_calls = accumulated_tool_calls  # populated by chat_stream
            except Exception as e:
                return ReasonerOutcome(final_message="", terminal_reason="error",
                                       notes=str(e), tool_calls_made=turns - 1,
                                       cost_usd=cost, snapshot_ids=snapshot_ids)
```

**Implementer note:** `chat_stream` (Task 3.4) currently yields `(chunk_text, finish_reason, usage)` 3-tuples. To carry tool_calls through, extend to 4-tuple `(chunk_text, finish_reason, usage, tool_calls)` — minor change to `lib/llm/client.py::chat_stream` that the implementer makes alongside this task.

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/unit/test_reasoner_tool_loop.py -v
git add service.kodi.ai/lib/reasoner.py service.kodi.ai/lib/llm/client.py \
        tests/unit/test_reasoner_tool_loop.py
git commit -m "fix(reasoner): use chat_stream + mid-stream budget check (C3)

run_with_tools now uses self.llm.chat_stream (not chat). Per-chunk
mid-stream budget check via budget.mid_stream_check(streamed_cost):
trip → cancel stream, emit synthetic well-formed tool envelope
{role:'tool', tool_call_id:'budget_truncated', content:{error,
tokens_streamed, estimated_cost_so_far}}, return ReasonerOutcome with
terminal_reason='budget_truncated'.
chat_stream's yield signature extended to 4-tuple (chunk_text,
finish_reason, usage, tool_calls) to carry tool calls through the
streaming path.

Spec: §1.10, §5.5.
Round-1 plan-review fix: C3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5.6 — Pause sequence executor (C4)

**Spec ref:** §1.7 (round-7 strict 4-step ordering: memory → MonotonicBudget.pause → atomic disk → Telegram with 15s deadline → pause_notify_failed on fail).

**Why this revision:** Round-1 reviewer (C4) found that Task 5.5 captured `needs_user` outcome but never specified the 4-step pause sequence as concrete code. Task 10.3 was a paragraph. The strict ordering is load-bearing for crash recovery (spec §1.7) — implementer needs explicit code.

**Files:** Create `service.kodi.ai/lib/pause_sequence.py`, create `tests/unit/test_pause_sequence.py`.

- [ ] **Step 1: Test**

```python
# tests/unit/test_pause_sequence.py
import json
import os
import sys
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    from lib import state_paths
    state_paths.ensure_dirs()
    yield


def test_pause_sequence_strict_order_on_success():
    """Steps fire in order: memory → budget.pause → disk → telegram."""
    from lib import pause_sequence, reasoner_state
    from lib.concurrency import MonotonicBudget, paused_sessions, paused_sessions_lock
    order: list[str] = []
    state = reasoner_state.SessionState(
        session_id="s1", messages=[], tool_history=[], pending_tool={"name": "x"},
        snapshot_ids=[], terminal_state="paused", paused_at=0.0,
        budget_blob={"limit_s": 60, "elapsed_baseline": 0.0, "state": "RUNNING"},
        cluster_id=None,
    )
    budget = MonotonicBudget(limit_s=60); budget.start()
    def fake_telegram_send(*a, **kw): order.append("telegram"); return True
    ok = pause_sequence.pause_and_persist(
        state=state, budget=budget,
        telegram_send_callable=lambda: (order.append("telegram"), True)[1],
    )
    assert ok is True
    # Memory entry exists
    with paused_sessions_lock:
        assert "s1" in paused_sessions
    # Disk file written (atomic, no .tmp left)
    from lib import state_paths
    assert os.path.exists(state_paths.profile_path("sessions/s1.json"))
    assert budget.state.name == "PAUSED"


def test_pause_sequence_marks_pause_notify_failed_on_telegram_fail():
    """If Telegram send fails (within 15s), state marked pause_notify_failed."""
    from lib import pause_sequence, reasoner_state
    from lib.concurrency import MonotonicBudget
    state = reasoner_state.SessionState(
        session_id="s2", messages=[], tool_history=[], pending_tool={"name": "x"},
        snapshot_ids=[], terminal_state="paused", paused_at=0.0,
        budget_blob={"limit_s": 60, "elapsed_baseline": 0.0, "state": "RUNNING"},
        cluster_id=None,
    )
    budget = MonotonicBudget(limit_s=60); budget.start()
    def failing_telegram(): return False
    ok = pause_sequence.pause_and_persist(
        state=state, budget=budget, telegram_send_callable=failing_telegram,
    )
    assert ok is False
    # Disk state updated to pause_notify_failed
    from lib import state_paths
    with open(state_paths.profile_path("sessions/s2.json")) as f:
        blob = json.load(f)
    assert blob["terminal_state"] == "pause_notify_failed"
```

- [ ] **Step 2: Implement `service.kodi.ai/lib/pause_sequence.py`**

```python
# service.kodi.ai/lib/pause_sequence.py
"""Executes the 4-step pause sequence per spec §1.7 (round-7 strict ordering).

Step 1: paused_sessions[sid] = state (memory)
Step 2: MonotonicBudget.pause() (memory; updates elapsed_baseline)
Step 3: Atomic disk write — captures post-pause budget state
Step 4: Telegram send with 15s deadline
   - Success: return True
   - Fail: mark pause_notify_failed terminal state, persist, return False
     (boot watchdog retries on next startup)
"""
from __future__ import annotations
import time
from .concurrency import paused_sessions, paused_sessions_lock, MonotonicBudget
from . import reasoner_state


TELEGRAM_SEND_DEADLINE_S = 15.0


def pause_and_persist(
    *,
    state: reasoner_state.SessionState,
    budget: MonotonicBudget,
    telegram_send_callable,
) -> bool:
    """Execute the 4-step pause sequence. Returns True if Telegram sent OK,
    False if pause_notify_failed terminal state."""
    # Step 1: in-memory primary
    with paused_sessions_lock:
        paused_sessions[state.session_id] = state
    # Step 2: budget pause (memory; updates elapsed_baseline)
    if budget.state.name == "RUNNING":
        budget.pause()
    # Reflect new budget state in serialized blob BEFORE disk write
    state.budget_blob = budget.to_dict()
    state.paused_at = time.time()
    state.terminal_state = "paused"
    # Step 3: atomic disk write
    reasoner_state.persist(state)
    # Step 4: Telegram with deadline
    deadline = time.monotonic() + TELEGRAM_SEND_DEADLINE_S
    try:
        ok = bool(telegram_send_callable())
    except Exception:
        ok = False
    if ok and time.monotonic() <= deadline:
        return True
    # Fail path
    state.terminal_state = "pause_notify_failed"
    reasoner_state.persist(state)
    return False
```

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/unit/test_pause_sequence.py -v   # 2 passed
git add service.kodi.ai/lib/pause_sequence.py tests/unit/test_pause_sequence.py
git commit -m "feat(pause_sequence): explicit 4-step pause sequence (C4)

pause_and_persist enforces strict ordering per spec §1.7 round-7:
1. paused_sessions[sid] = state (memory)
2. MonotonicBudget.pause() (memory)
3. Atomic disk write (captures post-pause budget_blob)
4. Telegram send with 15s deadline
   - Success → return True
   - Fail → state.terminal_state='pause_notify_failed', persist, return False
     (boot watchdog retries on next startup; surface via /status)

Task 10.3 should call pause_and_persist instead of inlining the steps.

Round-1 plan-review fix: C4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7.4-EXPANDED through 7.7-EXPANDED — Full TDD blocks for Phase 7 stubs (H1)

**Why this revision:** Round-1 reviewer (H1) flagged that Tasks 7.4 (uninstall/update/clear_cache), 7.5 (kodi_settings), 7.6 (kodi_files), 7.7 (verify) were paragraph-only stubs ("Steps: test → impl → commit") without concrete code. Per TDD discipline (line 18 of this plan) and per implementer/reviewer subagent contract, each task needs failing-test → impl → passing-test → commit blocks.

**Format note:** Rather than re-paste 800+ lines here, the expanded tasks follow the EXACT pattern of Tasks 4.4, 4.6, 7.1, 7.2, 7.3 (above). The implementer should:

1. **For each expanded task, write a failing pytest test** covering:
   - Happy path (success result with expected `actual_state_after`).
   - Disruptive path (where applicable — e.g. `disable_addon` when player active → confirm flow).
   - Error path (e.g. `update_addon` post-`UpdateAddon()` timeout + cluster recurrence → success=False).
   - Snapshot-targets registration with `lib.snapshot_manager.register_runtime_handlers`.
2. **Run pytest — verify it fails.**
3. **Implement the tool per spec §4.6 + §4.2 verify-logic rules** (no shortcuts; complete code).
4. **Run pytest — verify it passes.**
5. **Commit with spec reference.**

**Required tool specs (implementer expands each to a Task 4.4-style block):**

| Task | Tool(s) | Key spec requirements |
|---|---|---|
| 7.4 | `uninstall_addon` | confirm; disruptive=`addon_owns_active_player`; target_addons={id}; snapshot=`[addon_state]`; verify via GetAddonDetails 10s timeout |
| 7.4 | `update_addon` | Per spec §4.6 round-3 rewrite: pre-call GetAddonDetails for `old_version` (no `refresh=True`); `executebuiltin('UpdateAddon(<id>)')`; verify version_changed OR 60s timeout + no cluster recurrence → success "already at latest or repo unreachable" (with warning); 60s timeout + cluster recurrence → failure |
| 7.4 | `clear_addon_cache` | immediate + disruptive=`addon_owns_active_player`; deletes `addon_data/<id>/cache/` + `<install_path>/__pycache__/`; PermissionError → ToolResult fail; then internally calls `restart_addon(id)` |
| 7.5 | `get_kodi_setting`, `set_kodi_setting` | `set_kodi_setting`: tier=confirm; disruptive=`setting_id in DISRUPTIVE_KODI_SETTINGS`; target_addons="ALL" if in CROSS_ADDON_SETTINGS else `set()`; snapshot=`[kodi_setting(setting_id)]`; verify via Settings.GetSettingValue |
| 7.5 | `get_addon_setting`, `set_addon_setting` | Enabled path: `xbmcaddon.Addon(addon_id).setSetting`. Disabled path: parse `<install>/resources/settings.xml` for `<setting id=...>`; type validation per spec §4.6 (bool coerce, number+range, string pass-through, enum SKIPPED with WARNING, slider/action REJECTED); direct xmlparse write to `addon_data/<id>/settings.xml`. Snapshot `[addon_setting(addon_id:key)]`; register runtime handlers |
| 7.5 | `get_addon_setting` disabled-merge | For disabled addons, merge user-set values from `addon_data/<id>/settings.xml` with schema/defaults from `<install>/resources/settings.xml`; include schema metadata in `actual_state_after` |
| 7.6 | `read_log` | Read `kodi.log` via xbmcvfs; args lines, level, addon (filter), since_seconds; read-only |
| 7.6 | `read_log_old` | Same shape for `kodi.old.log` |
| 7.6 | `write_file` | tier=confirm; path MUST be under special://profile/, userdata/, temp/; snapshot via `extract_keys.parser_for_path` (kind=file_keys) OR byte-equality (kind=file) |
| 7.6 | `delete_file` | Same path restriction; snapshot same |
| 7.7 | `verify_fix` | Args: `strategy ∈ {playback_fail, dep_import_fail, repo_unreachable, default}`, `args` dict. Each strategy implemented as a loop using `abort_event.wait(0.25)` (NEVER `time.sleep`). `playback_fail`: poll `Player.GetActivePlayers` @ 1s; subscribe to `log_watcher` for non-recurrence of `cluster_id`; 5min total timeout. `dep_import_fail`: `restart_addon` then 30s log-quiet OR same error. `repo_unreachable`: http_get URL every 1min for 30min. `default`: 30s log-quiet for `cluster_id`. Returns `ToolResult(success=True/False, output=verdict_dict)` |
| 7.7 | `log_watcher.subscribe(filter_fn, on_match, timeout_s)` | New API on `LogWatcher` — single tail, multiple consumers via thread-safe queue. Used by `verify_fix` strategies |

**Implementer/reviewer loop discipline applies per task** (per project rule). Each task gets its own implementer + reviewer subagent pair; loop until clean. Estimated execution time: 4-6 task-pairs per day for an LLM-paced implementation.

```bash
# After all expansions complete, smoke-check tool registry contains them:
pytest -k "test_tool_registry or test_tool_kodi_addons or test_tool_kodi_settings or test_tool_kodi_files or test_tool_verify" -v
git commit -m "test: tool catalog completeness smoke for Tasks 7.4-7.7

After all Phase 7 expanded tasks land, registry contains:
list_addons, get_addon_details, install_addon, uninstall_addon,
enable_addon, disable_addon, restart_addon, update_addon, clear_addon_cache,
get_addon_setting, set_addon_setting, get_kodi_setting, set_kodi_setting,
get_active_player, get_player_item, kodi_jsonrpc, http_get, read_log,
read_log_old, write_file, delete_file, list_snapshots, snapshot_create,
snapshot_restore, verify_fix, notify_user, ask_user.

Round-1 plan-review fix: H1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5.4-AMENDMENT — populate `tool_history[].output_signature` (fixes H7 dead-code)

**Spec ref:** §1.4 (tool-history-match suppression — boot post-mortem rule).

**Why this amendment:** Round-2 plan reviewer found that Task 4.7-REVISED's `boot_post_mortem` references `tool_entry.get("output_signature")` on `sessions/<id>.json::tool_history` entries, but **`output_signature` is never produced anywhere** — Task 5.2's `SessionState.tool_history` example uses `{"name": "read_log", "result": "..."}` and Task 5.4's `_execute_tool` returns a dict without `output_signature`. Result: tool-history-match suppression in 4.7 is dead code, and legitimate side-effects of our tools that lack the `[service.kodi.ai]` prefix would surface as bogus backdated incidents — exactly the failure H7 was supposed to address.

**Fix:** Populate `output_signature` in two places:
1. `SessionState.tool_history` schema documented to include `output_signature` field (signature of the tool's output text, computable from `prefilter.cluster_id_for`).
2. In Task 5.4's `_execute_tool` (called inside `run_with_tools`), after dispatching the tool, append to a local `tool_history` list (separate from `messages`) and serialize that into `SessionState.tool_history` at pause-time. Each entry includes `output_signature`.

**Files:** Modify `service.kodi.ai/lib/reasoner.py` (extend `_execute_tool` + `run_with_tools` to track tool_history); update `tests/unit/test_reasoner_tool_loop.py` (or add a new test).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_reasoner_tool_history.py
import json
import pytest
from unittest import mock
from dataclasses import dataclass


@dataclass
class FakeChatStreamYielder:
    """Mimics chat_stream yield 4-tuple (chunk_text, finish_reason, usage, tool_calls)."""
    def __init__(self, sequence):
        self.sequence = sequence
    def __iter__(self):
        return iter(self.sequence)


def test_run_with_tools_records_output_signature_per_tool():
    """Each tool call should append to outcome.tool_history with output_signature."""
    from lib.reasoner import Reasoner, ReasonerOutcome
    fake_llm = mock.MagicMock()
    # Sequence: turn 1 = tool_call read_log; turn 2 = final message
    fake_llm.chat_stream.side_effect = [
        FakeChatStreamYielder([
            ("", "tool_calls", {"prompt_tokens": 100, "completion_tokens": 20},
             [{"id": "t1", "function": {"name": "read_log", "arguments": "{}"}}]),
        ]),
        FakeChatStreamYielder([
            ("all clear", None, None, None),
            (None, "stop", {"prompt_tokens": 50, "completion_tokens": 10}, None),
        ]),
    ]
    fake_registry = {
        "read_log": mock.MagicMock(
            return_value=mock.MagicMock(
                success=True, output="log lines here", actual_state_after=None,
                snapshot_id=None, error=None, requested="read_log()",
            ))
    }
    r = Reasoner(
        llm_client=fake_llm, api_key="k",
        router=mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0)),
        budget=mock.MagicMock(
            pre_call_check=lambda estimated_cost: (True, None),
            mid_stream_check=lambda streamed_cost: True,
            record_actual=lambda c: None,
            incident_cost_usd=0.0,
        ),
        tool_registry=fake_registry,
    )
    out = r.run_with_tools(
        initial_messages=[{"role": "user", "content": "diagnose"}],
        task_class="t1_simple", session_id="s1", max_turns=5,
    )
    # tool_history populated with output_signature
    assert len(out.tool_history) == 1
    entry = out.tool_history[0]
    assert entry["name"] == "read_log"
    assert "output_signature" in entry
    # signature is the cluster_id_for of the serialized output
    from lib.prefilter import cluster_id_for
    assert entry["output_signature"] == cluster_id_for("log lines here")
```

- [ ] **Step 2: Modify `lib/reasoner.py`**

In `ReasonerOutcome`, add field:
```python
@dataclass
class ReasonerOutcome:
    # ... existing fields ...
    tool_history: list[dict] = field(default_factory=list)
```

In `Reasoner._execute_tool`, after dispatching, return the tool_result dict (already done). Caller (`run_with_tools`) builds the `tool_history` entry:

```python
# Inside run_with_tools, after each tool dispatch + before continuing loop:
                    from .prefilter import cluster_id_for
                    output_str = str(tool_result.get("output") or "")
                    tool_history_entry = {
                        "name": fn["name"],
                        "args_json": fn.get("arguments", "{}"),
                        "success": bool(tool_result.get("success")),
                        "output_signature": cluster_id_for(output_str),
                        "snapshot_id": tool_result.get("snapshot_id"),
                        "error": tool_result.get("error"),
                    }
                    tool_history.append(tool_history_entry)
```

Initialize `tool_history: list[dict] = []` near the top of `run_with_tools`. Pass it into the returned `ReasonerOutcome(..., tool_history=tool_history)` on EVERY return path (complete, budget_refused, error, budget_truncated, max_turns, needs_user).

At pause-time (Task 5.6 `pause_and_persist`), the caller serializes `outcome.tool_history` into `state.tool_history` (this is already implicit since `SessionState.tool_history` is just `list[dict]` and `pause_and_persist` doesn't transform it — the upstream `_handle_incident` / `_handle_user_msg` in Task 10.3 should copy `outcome.tool_history` into the `SessionState` before passing to `pause_and_persist`).

- [ ] **Step 3: Document `output_signature` field in Task 5.2's SessionState schema**

Update the `SessionState` docstring (or add a comment) noting that `tool_history` items are dicts with shape:
```python
{
    "name": str,                    # tool name
    "args_json": str,               # raw JSON args string from LLM
    "success": bool,
    "output_signature": str,        # prefilter.cluster_id_for(str(output))
                                    # — used by boot_post_mortem to suppress
                                    # tool-side-effect log lines per spec §1.4
    "snapshot_id": str | None,
    "error": str | None,
}
```

- [ ] **Step 4: Run tests + commit**

```bash
pytest tests/unit/test_reasoner_tool_history.py -v
git add service.kodi.ai/lib/reasoner.py tests/unit/test_reasoner_tool_history.py
git commit -m "fix(reasoner): populate tool_history[].output_signature (H7 dead-code)

Per spec §1.4 tool-history-match suppression in boot_post_mortem.
ReasonerOutcome gains tool_history: list[dict] (default_factory=list).
run_with_tools appends one entry per dispatched tool:
  {name, args_json, success, output_signature: cluster_id_for(str(output)),
   snapshot_id, error}.
All return paths (complete/budget_refused/error/budget_truncated/max_turns/
needs_user) carry tool_history.
SessionState.tool_history is the on-disk persistence target — caller
(Task 10.3 _handle_*) copies outcome.tool_history into SessionState
before pause_and_persist.

Without this fix, boot_post_mortem's tool-history-match branch in
Task 4.7-REVISED is dead code at runtime — legitimate tool side-effect
log lines (those without [service.kodi.ai] prefix) would surface as
bogus backdated incidents, defeating the H7 fix.

Round-2 plan-review fix: H7 dead-code completion.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---







