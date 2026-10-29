"""Integration behavior against actual seekdb and actual PowerContext, no mocks."""

import json
import shutil
from pathlib import Path

import pytest

from sdd.common import digest
from sdd.context import build
from sdd.model import credentials
from sdd.state import state
from sdd.store import ingest, retrieve

ROOT = Path(__file__).resolve().parents[1]


def test_reimport_removes_deleted_sources_and_uses_updated_content(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "spec.md").write_text("orders status v1")
    (project / "old.py").write_text("# orders status obsolete")
    data = tmp_path / "data"
    ingest(data, project)
    assert {d["path"] for d in retrieve(data, "orders")} == {"spec.md", "old.py"}
    (project / "old.py").unlink()
    (project / "spec.md").write_text("orders status v2 changed")
    ingest(data, project)
    docs = retrieve(data, "orders")
    assert len(docs) == 1 and docs[0]["content"] == "orders status v2 changed"
    assert docs[0]["sha256"] == digest(docs[0]["content"])
    assert retrieve(data, "zzzz%'; DROP TABLE sdd_documents; --") == []
    assert retrieve(data, "orders")[0]["sha256"] == digest("orders status v2 changed")


def test_missing_required_evidence_fails_instead_of_inventing_sources(tmp_path):
    project = tmp_path / "project"
    shutil.copytree(ROOT / "sample", project)
    task = json.loads((project / "task.json").read_text())
    (project / "specs/orders.md").unlink()
    ingest(tmp_path / "data", project)
    with pytest.raises(ValueError, match="specs/orders.md"):
        build(tmp_path / "data", task)


def test_powercontext_exact_restore_isolates_tasks_and_allows_repeat_save(tmp_path):
    a = {"completed": ["a"], "todo": ["continue a"], "verification": ["passed"]}
    b = {"completed": ["b"], "todo": ["continue b"], "verification": []}
    assert state(tmp_path, "task-a")["value"] is None
    saved = state(tmp_path, "task-a", a)
    state(tmp_path, "task-b", b)
    repeated = state(tmp_path, "task-a", a)
    assert state(tmp_path, "task-a")["value"] == a
    assert state(tmp_path, "task-b")["value"] == b
    assert (
        saved["address"]["scope_id"] != state(tmp_path, "task-b")["address"]["scope_id"]
    )
    assert repeated["value"] == a
    # The address file contains no business state; state is read from the PC service.
    pointer = json.loads((tmp_path / "state-address.json").read_text())
    assert all(set(item) == {"scope_id", "citation"} for item in pointer.values())


def test_credentials_never_send_to_non_minimax_host(tmp_path, monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
    config = tmp_path / "claude.json"
    config.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://example.invalid/anthropic",
                    "ANTHROPIC_AUTH_TOKEN": "test-secret",
                    "ANTHROPIC_MODEL": "MiniMax-test",
                }
            }
        )
    )
    with pytest.raises(ValueError, match="official HTTPS MiniMax"):
        credentials(config)
