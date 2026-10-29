"""CLI input: project files/task/state JSON; output: JSON plus auditable run records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .common import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir", type=Path, required=True, help="Dedicated local data directory"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("import")
    ingest.add_argument("--project", type=Path, required=True)
    context = sub.add_parser("context")
    context.add_argument("--task", type=Path, required=True)
    context.add_argument("--out", type=Path)
    save = sub.add_parser("save")
    save.add_argument("--task-id", required=True)
    save.add_argument("--state", type=Path, required=True)
    resume = sub.add_parser("resume")
    resume.add_argument("--task-id", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--project", type=Path, required=True)
    generate.add_argument("--context", type=Path, required=True)
    generate.add_argument("--claude-config", type=Path)
    args = parser.parse_args()
    if args.command == "import":
        from .store import ingest

        result = ingest(args.run_dir, args.project)
    elif args.command == "context":
        from .context import build

        result = build(args.run_dir, json.loads(args.task.read_text()))
        if args.out:
            write_json(args.out, result)
    elif args.command in {"save", "resume"}:
        from .state import state

        result = state(
            args.run_dir,
            args.task_id,
            json.loads(args.state.read_text()) if args.command == "save" else None,
        )
    else:
        from .model import generate

        result = generate(
            args.run_dir,
            args.project,
            json.loads(args.context.read_text()),
            args.claude_config,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
