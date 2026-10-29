"""Six-item acceptance: each CLI action runs in a separate OS process."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from sdd.common import digest, now, write_json

ROOT = Path(__file__).resolve().parent


def run(args):
    directory = args.run_dir.resolve()
    if directory.exists():
        raise ValueError(
            "Use a fresh --run-dir; existing evidence is never overwritten"
        )
    project, evidence, data = (
        directory / "project",
        directory / "evidence",
        directory / "data",
    )
    shutil.copytree(
        ROOT / "sample", project, ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copyfile(ROOT / "snapshots/orders.before.py", project / "orders.py")
    evidence.mkdir()
    task = json.loads((project / "task.json").read_text())
    test_hash = digest((project / task["tests"]).read_text())
    before_hash = digest((project / "orders.py").read_text())

    def execute(name, command, cwd=ROOT, expected=0):
        result = subprocess.run(
            command, cwd=cwd, text=True, capture_output=True, timeout=240
        )
        write_json(
            evidence / (name + ".json"),
            {
                "time": now(),
                "command": command,
                "cwd": str(cwd),
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "source_sha256": digest((project / "orders.py").read_text()),
                "tests_sha256": test_hash,
            },
        )
        if result.returncode != expected:
            raise RuntimeError(
                f"{name}: expected exit {expected}, got {result.returncode}; see {evidence / (name + '.json')}"
            )
        return result

    def cli(name, *parts):
        return json.loads(
            execute(
                name,
                [sys.executable, "-m", "sdd", "--run-dir", str(data), *map(str, parts)],
            ).stdout
        )

    def tests(name, group, expected=0):
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-v",
            "-k",
            group,
        ]
        return execute(name, command, project, expected)

    before = tests("01-target-before", "TargetTests", 1)
    assert "AssertionError" in before.stderr and "ERROR:" not in before.stderr
    tests("02-regression-before", "RegressionTests")
    cli("03-import", "import", "--project", project)
    assert cli("04-empty-state", "resume", "--task-id", task["id"])["value"] is None
    progress = {
        "completed": [
            "Imported real project documents; baseline target tests fail as expected"
        ],
        "todo": [task["description"], "Run target and regression tests"],
        "verification": [
            {
                "phase": "before",
                "target_exit": 1,
                "regression_exit": 0,
                "source_sha256": before_hash,
            }
        ],
    }
    write_json(directory / "state.json", progress)
    cli(
        "05-save-progress",
        "save",
        "--task-id",
        task["id"],
        "--state",
        directory / "state.json",
    )
    context_path = directory / "context-before.json"
    context = cli(
        "06-context-before",
        "context",
        "--task",
        project / "task.json",
        "--out",
        context_path,
    )
    assert context["progress"] == progress
    sources = context["specifications"] + context["code"] + context["tests"]
    assert set(task["required_sources"]).issubset({d["path"] for d in sources})
    assert "specs/unrelated.md" not in {d["path"] for d in sources}
    for source in sources:
        assert digest((project / source["path"]).read_text()) == source["sha256"]
    if args.recorded:
        record = json.loads((ROOT / "evidence/minimax-development.json").read_text())
        text = record["response"]["text"].strip()
        if text.startswith("```"):
            text = "\n".join(text.splitlines()[1:-1])
        replacement = json.loads(text)
        after = (ROOT / "snapshots/orders.after.py").read_text()
        assert replacement == {"path": task["target"], "content": after}
        assert record["before_sha256"] == before_hash and record[
            "after_sha256"
        ] == digest(after)
        original_context = json.loads(record["request"]["messages"][0]["content"])
        assert original_context["snapshot_hash"] == context["snapshot_hash"]
        write_json(
            evidence / "07-recorded-minimax-reuse.json",
            {
                "mode": "recorded",
                "live_call": False,
                "source": "evidence/minimax-development.json",
                "id": record["response"]["id"],
                "model": record["response"]["model"],
                "after_sha256": digest(after),
            },
        )
        (project / task["target"]).write_text(after)
    else:
        parts = ["generate", "--project", project, "--context", context_path]
        if args.claude_config:
            parts += ["--claude-config", args.claude_config]
        cli("07-live-minimax", *parts)
    after_hash = digest((project / "orders.py").read_text())
    assert before_hash != after_hash
    assert digest((project / task["tests"]).read_text()) == test_hash
    tests("08-target-after", "TargetTests")
    tests("09-regression-after", "RegressionTests")
    execute(
        "10-all-after",
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        project,
    )
    progress = {
        "completed": [
            "MiniMax implementation applied",
            "All target and regression tests passed",
        ],
        "todo": ["Review ORD-001 and ORD-002 evidence for delivery"],
        "verification": [
            {
                "phase": "after",
                "target_exit": 0,
                "regression_exit": 0,
                "source_sha256": after_hash,
                "tests_sha256": test_hash,
            }
        ],
    }
    write_json(directory / "state.json", progress)
    saved = cli(
        "11-save-outcome",
        "save",
        "--task-id",
        task["id"],
        "--state",
        directory / "state.json",
    )
    restored = cli("12-restart-resume", "resume", "--task-id", task["id"])
    assert restored["pid"] != saved["pid"]
    assert restored["value"] == progress and restored["address"] == saved["address"]
    cli("13-import-after", "import", "--project", project)
    context_after = cli(
        "14-context-after-restart", "context", "--task", project / "task.json"
    )
    assert (
        context_after["progress"] == progress
        and context_after["next_action"] == progress["todo"][0]
    )
    spec = project / "specs/orders.md"
    updated = (
        spec.read_text().replace("规格 v1", "规格 v2")
        + "\n## ORD-003 新规格标记\nstatus 筛选仍维持确定的输入顺序；本次更新必须进入上下文。\n"
    )
    spec.write_text(updated)
    cli("15-reimport-updated-spec", "import", "--project", project)
    revised = cli("16-context-updated-spec", "context", "--task", project / "task.json")
    actual = next(
        d for d in revised["specifications"] if d["path"] == "specs/orders.md"
    )
    assert actual["content"] == updated and actual["sha256"] == digest(updated)
    assert (
        revised["snapshot_hash"] != context_after["snapshot_hash"]
        and "规格 v1" not in actual["content"]
    )
    summary = {
        "time": now(),
        "mode": "recorded" if args.recorded else "live-minimax",
        "passed": True,
        "checks": {
            "runnable": True,
            "minimax_provenance": True,
            "context_and_spec_update": True,
            "real_seekdb": True,
            "powercontext_restart_reuse": True,
            "effective_change": True,
        },
        "before_source_sha256": before_hash,
        "after_source_sha256": after_hash,
        "unchanged_tests_sha256": test_hash,
        "save_pid": saved["pid"],
        "resume_pid": restored["pid"],
    }
    write_json(directory / "acceptance.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--claude-config", type=Path)
    parser.add_argument(
        "--recorded",
        action="store_true",
        help="Reproduce the submitted MiniMax code, no new model call",
    )
    run(parser.parse_args())
