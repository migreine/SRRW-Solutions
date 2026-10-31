"""Per-test output folder under runs/_pytest/ (never /tmp; works the same on Windows).

Import the fixture into a test module with `from tests.fixtures.paths import out_dir`.
"""

import shutil
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTEST_RUNS = REPO_ROOT / "runs" / "_pytest"


@pytest.fixture
def out_dir(request) -> Path:
    path = PYTEST_RUNS / f"{request.node.name[:40]}-{uuid.uuid4().hex[:8]}"
    for ch in "[]/\\:":
        path = path.with_name(path.name.replace(ch, "_"))
    path.mkdir(parents=True, exist_ok=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)
    try:
        PYTEST_RUNS.rmdir()  # only succeeds once empty
    except OSError:
        pass
