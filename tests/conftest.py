from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_role_run_log_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Keep every test away from the user's persistent RoleRun logs."""
    log_dir = tmp_path / "rolerun-logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    from app import config

    monkeypatch.setattr(config, "LOG_DIR", log_dir)
    for module_name, module in tuple(sys.modules.items()):
        if not module_name.startswith("app.") or module is None:
            continue
        if hasattr(module, "LOG_DIR"):
            monkeypatch.setattr(module, "LOG_DIR", log_dir)

    return log_dir
