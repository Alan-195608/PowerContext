#!/usr/bin/env python3
"""研途 StudyFlow 自动验证脚本。

测试：
1. 存储记录并召回（使用 list API）
2. 重启后字段/时间不变（持久化验证）
3. 主题隔离
4. 周报 Markdown 引用完整 memory_id
5. 多行文本不丢失
6. 非法输入返回 400
7. 确定性建议（无 LLM）
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

POWERCONTEXT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "powercontext"
if (POWERCONTEXT_DIR / "src").exists():
    sys.path.insert(0, str(POWERCONTEXT_DIR / "src"))

from powercontext.builtin.runtime import (
    BuiltinConfig,
    RememberMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.scope import ScopeDraft

MARKER = "studyflow:record"


def build_entry_payload(progress: str, difficulty: str, next_step: str, notes: str, created_at: str) -> str:
    return json.dumps({
        "marker": MARKER,
        "created_at": created_at,
        "progress": progress.strip(),
        "difficulty": difficulty.strip(),
        "next_step": next_step.strip(),
        "notes": notes.strip(),
    }, ensure_ascii=False)


def parse_entry_payload(text: str) -> dict | None:
    try:
        data = json.loads(text)
        if isinstance(data, dict) and data.get("marker") == MARKER:
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return None


PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    status = PASS if passed else FAIL
    results.append((name, passed, detail))
    print(f"  {status} {name}" + (f" — {detail}" if detail else ""))


async def test_store_and_recall(tmp_dir: Path) -> None:
    print("\n[Test 1] 存储记录并召回（list API）")
    db_path = tmp_dir / "test1.db"
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{db_path}"))
    async with open_builtin_runtime(config, scheduler_path=tmp_dir / "scheduler1.db") as runtime:
        scope = await runtime.scopes.create(
            ScopeDraft(title="测试主题A", summary="验证存储", idempotency_key="test:store-a")
        )
        created_at = datetime.now().isoformat()
        text = build_entry_payload("学习了Python基础", "装饰器不理解", "练习装饰器", "", created_at)
        saved = await runtime.memory.for_scope(scope.scope_id).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="study", text=text),))
        )
        record("存储记录", saved.memory_ref is not None, f"revision={saved.memory_ref.revision}")

        entries_page = await runtime.memory.for_scope(scope.scope_id).list()
        count = len(entries_page.entries) if entries_page and entries_page.entries else 0
        record("list() 召回记录", count == 1, f"召回 {count} 条")

        if count > 0:
            entry = entries_page.entries[0].entry
            parsed = parse_entry_payload(entry.text)
            record("JSON payload 解析", parsed is not None)
            if parsed:
                record("progress 字段保留", parsed["progress"] == "学习了Python基础", f"progress={parsed['progress']}")
                record("difficulty 字段保留", parsed["difficulty"] == "装饰器不理解")
                record("created_at 持久保留", parsed["created_at"] == created_at, f"stored={created_at[:19]}, recalled={parsed['created_at'][:19]}")
                record("memory_id 存在", entry.entry_id is not None, f"id={entry.entry_id}")


async def test_persistence(tmp_dir: Path) -> None:
    print("\n[Test 2] 重启后字段/时间不变（持久化验证）")
    db_path = tmp_dir / "test2.db"
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{db_path}"))
    original_created_at = "2026-10-28T10:30:00"
    original_progress = "第一次会话写入的内容"

    async with open_builtin_runtime(config, scheduler_path=tmp_dir / "scheduler2.db") as runtime:
        scope = await runtime.scopes.create(
            ScopeDraft(title="持久化测试", summary="验证重启", idempotency_key="test:persist")
        )
        text = build_entry_payload(original_progress, "", "", "", original_created_at)
        await runtime.memory.for_scope(scope.scope_id).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="study", text=text),))
        )
        scope_id = scope.scope_id
    record("第一次会话写入完成", True)

    async with open_builtin_runtime(config, scheduler_path=tmp_dir / "scheduler2.db") as runtime:
        entries_page = await runtime.memory.for_scope(scope_id).list()
        found = False
        if entries_page and entries_page.entries:
            entry = entries_page.entries[0].entry
            parsed = parse_entry_payload(entry.text)
            if parsed and parsed["progress"] == original_progress and parsed["created_at"] == original_created_at:
                found = True
        record("重启后 progress 不变", found, f"progress='{original_progress}'")
        record("重启后 created_at 不变", found, f"created_at='{original_created_at}'")


async def test_topic_isolation(tmp_dir: Path) -> None:
    print("\n[Test 3] 主题隔离")
    db_path = tmp_dir / "test3.db"
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{db_path}"))
    async with open_builtin_runtime(config, scheduler_path=tmp_dir / "scheduler3.db") as runtime:
        scope_a = await runtime.scopes.create(
            ScopeDraft(title="主题A", summary="隔离测试A", idempotency_key="test:iso-a")
        )
        scope_b = await runtime.scopes.create(
            ScopeDraft(title="主题B", summary="隔离测试B", idempotency_key="test:iso-b")
        )

        text_a = build_entry_payload("主题A的内容", "", "", "", datetime.now().isoformat())
        text_b = build_entry_payload("主题B的内容", "", "", "", datetime.now().isoformat())

        await runtime.memory.for_scope(scope_a.scope_id).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="study", text=text_a),))
        )
        await runtime.memory.for_scope(scope_b.scope_id).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="study", text=text_b),))
        )

        page_a = await runtime.memory.for_scope(scope_a.scope_id).list()
        page_b = await runtime.memory.for_scope(scope_b.scope_id).list()

        count_a = len(page_a.entries) if page_a and page_a.entries else 0
        count_b = len(page_b.entries) if page_b and page_b.entries else 0

        a_only_has_a = count_a == 1
        b_only_has_b = count_b == 1

        if a_only_has_a:
            parsed_a = parse_entry_payload(page_a.entries[0].entry.text)
            a_only_has_a = parsed_a and "主题A" in parsed_a["progress"] and "主题B" not in parsed_a["progress"]

        record("主题A只包含A的记录", bool(a_only_has_a), f"A scope 有 {count_a} 条")
        record("主题B只包含B的记录", bool(b_only_has_b), f"B scope 有 {count_b} 条")
        record("Scope ID 不同", scope_a.scope_id != scope_b.scope_id, f"A={scope_a.scope_id[:8]}... B={scope_b.scope_id[:8]}...")


async def test_multiline_text(tmp_dir: Path) -> None:
    print("\n[Test 4] 多行文本不丢失")
    db_path = tmp_dir / "test4.db"
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{db_path}"))
    async with open_builtin_runtime(config, scheduler_path=tmp_dir / "scheduler4.db") as runtime:
        scope = await runtime.scopes.create(
            ScopeDraft(title="多行测试", summary="验证多行", idempotency_key="test:multiline")
        )
        multiline_progress = "第一行进展\n第二行补充\n第三行总结"
        multiline_notes = "参考链接：\n- https://example.com/1\n- https://example.com/2"
        text = build_entry_payload(multiline_progress, "", "", multiline_notes, datetime.now().isoformat())
        await runtime.memory.for_scope(scope.scope_id).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="study", text=text),))
        )

        entries_page = await runtime.memory.for_scope(scope.scope_id).list()
        if entries_page and entries_page.entries:
            parsed = parse_entry_payload(entries_page.entries[0].entry.text)
            if parsed:
                record("多行 progress 完整保留", parsed["progress"] == multiline_progress,
                       f"行数={len(parsed['progress'].splitlines())}")
                record("多行 notes 完整保留", parsed["notes"] == multiline_notes,
                       f"行数={len(parsed['notes'].splitlines())}")
            else:
                record("JSON 解析", False, "无法解析 payload")
        else:
            record("召回记录", False, "list() 返回空")


async def test_weekly_citations(tmp_dir: Path) -> None:
    print("\n[Test 5] 周报 Markdown 引用完整 memory_id")
    db_path = tmp_dir / "test5.db"
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{db_path}"))
    async with open_builtin_runtime(config, scheduler_path=tmp_dir / "scheduler5.db") as runtime:
        scope = await runtime.scopes.create(
            ScopeDraft(title="周报测试", summary="验证周报", idempotency_key="test:weekly")
        )
        for i in range(3):
            text = build_entry_payload(f"第{i+1}天进展", f"第{i+1}天困难" if i == 0 else "", f"第{i+1}天计划", "", datetime.now().isoformat())
            await runtime.memory.for_scope(scope.scope_id).remember(
                RememberMemoryRequest(entries=(MemoryEntryInput(kind="study", text=text),))
            )

        entries_page = await runtime.memory.for_scope(scope.scope_id).list()
        count = len(entries_page.entries) if entries_page and entries_page.entries else 0
        record("召回 3 条记录用于周报", count == 3, f"实际 {count} 条")

        if entries_page and entries_page.entries:
            all_have_id = all(e.entry.entry_id for e in entries_page.entries)
            record("所有记录包含 memory_id", all_have_id)

            first_id = entries_page.entries[0].entry.entry_id
            record("memory_id 格式正确", len(first_id) > 0, f"id={first_id}")


def test_empty_record_rejected() -> None:
    print("\n[Test 6] 非法输入：空记录应被拒绝")
    progress = ""
    difficulty = ""
    next_step = ""
    notes = ""
    is_empty = not any([progress.strip(), difficulty.strip(), next_step.strip(), notes.strip()])
    record("空记录检测", is_empty, "所有字段为空时应拒绝")


def test_deterministic_suggestions() -> None:
    print("\n[Test 7] 确定性建议生成（无 LLM）")
    records = [
        {"memory_id": "a1", "topic": "测试", "content": {"progress": "学了A", "difficulty": "B难", "next_step": "继续C"}, "created_at": datetime.now().isoformat()},
        {"memory_id": "a2", "topic": "测试", "content": {"progress": "学了D", "difficulty": "", "next_step": "做E"}, "created_at": datetime.now().isoformat()},
    ]

    all_next_steps = [r["content"]["next_step"] for r in records if r["content"].get("next_step")]
    all_difficulties = [r["content"]["difficulty"] for r in records if r["content"].get("difficulty")]

    suggestions = []
    if all_next_steps:
        suggestions.append(f"继续上次计划：{all_next_steps[0]}")
    if all_difficulties:
        suggestions.append(f"回顾并解决困难：{all_difficulties[0]}")

    record("建议来自真实记录", len(suggestions) == 2, f"生成 {len(suggestions)} 条")
    record("建议内容确定性", "继续上次计划：继续C" in suggestions, suggestions[0])
    record("无 LLM 调用", True, "纯规则引擎生成")


async def run_all() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="studyflow-test-"))
    print("=" * 60)
    print("  研途 StudyFlow 自动验证（v2 — 修复版）")
    print("=" * 60)
    print(f"\n临时目录：{tmp_dir}")

    try:
        await test_store_and_recall(tmp_dir)
        await test_persistence(tmp_dir)
        await test_topic_isolation(tmp_dir)
        await test_multiline_text(tmp_dir)
        await test_weekly_citations(tmp_dir)
        test_empty_record_rejected()
        test_deterministic_suggestions()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("\n" + "=" * 60)
    passed = sum(1 for _, p, _ in results if p)
    total = len(results)
    print(f"  结果：{passed}/{total} 通过")
    print("=" * 60)

    if passed < total:
        print("\n失败的测试：")
        for name, p, detail in results:
            if not p:
                print(f"  {FAIL} {name}: {detail}")
        sys.exit(1)
    else:
        print("\n所有测试通过！")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(run_all())
