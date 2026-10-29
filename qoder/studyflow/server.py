#!/usr/bin/env python3
"""研途 StudyFlow — 基于 OceanBase PowerContext 的学习科研进度助手。

使用 Python 标准库 http.server 提供 HTTP 服务，通过 PowerContext 内置运行时
（SQLite 后端）持久化学习记录。每个学习主题对应一个 PowerContext Scope，
每条学习记录作为 Memory Entry 存储。建议与周报由确定性规则从真实存储生成。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from powercontext.builtin.runtime import (
    BuiltinConfig,
    BuiltinRuntime,
    RememberMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.scope import ScopeDraft

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("STUDYFLOW_DATA_DIR", str(BASE_DIR / "data")))
STATIC_DIR = BASE_DIR / "static"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("studyflow")

MARKER = "studyflow:record"


def build_entry_payload(progress: str, difficulty: str, next_step: str, notes: str, created_at: str) -> str:
    payload = {
        "marker": MARKER,
        "created_at": created_at,
        "progress": progress.strip(),
        "difficulty": difficulty.strip(),
        "next_step": next_step.strip(),
        "notes": notes.strip(),
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_entry_payload(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
        if isinstance(data, dict) and data.get("marker") == MARKER:
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def deterministic_suggestions(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"suggestions": [], "summary": "暂无记录，请先添加学习记录。"}

    all_difficulties = []
    all_next_steps = []
    all_progress = []

    for rec in records:
        content = rec["content"]
        if content.get("difficulty"):
            all_difficulties.append({"text": content["difficulty"], "created_at": rec["created_at"], "memory_id": rec["memory_id"]})
        if content.get("next_step"):
            all_next_steps.append({"text": content["next_step"], "created_at": rec["created_at"], "memory_id": rec["memory_id"]})
        if content.get("progress"):
            all_progress.append({"text": content["progress"], "created_at": rec["created_at"], "memory_id": rec["memory_id"]})

    suggestions = []
    if all_next_steps:
        suggestions.append(f"继续上次计划：{all_next_steps[0]['text']}")
    if all_difficulties:
        suggestions.append(f"回顾并解决困难：{all_difficulties[0]['text']}")
    if all_progress:
        suggestions.append(f"复习近期进展：{all_progress[0]['text']}")
    if len(records) < 3:
        suggestions.append("建议增加更多学习记录以形成完整知识链")

    latest_date = records[0]["created_at"][:10]
    summary = f"共 {len(records)} 条记录，最新记录于 {latest_date}。"
    if all_difficulties:
        summary += f" 累计 {len(all_difficulties)} 条困难记录。"
    if all_next_steps:
        summary += f" 累计 {len(all_next_steps)} 条待办计划。"

    return {"suggestions": suggestions, "summary": summary}


def generate_weekly_markdown(records: list[dict[str, Any]], topic: str | None, days: int) -> dict[str, Any]:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    filtered = [r for r in records if r["created_at"] >= cutoff]
    filtered.sort(key=lambda r: r["created_at"])

    if not filtered:
        period_start = cutoff[:10]
        period_end = datetime.now().strftime("%Y-%m-%d")
        return {
            "markdown": f"# 研途周报\n\n**{period_start} ~ {period_end}**\n\n本周暂无学习记录。",
            "record_count": 0,
            "citations": [],
        }

    by_topic: dict[str, list[dict]] = {}
    for rec in filtered:
        by_topic.setdefault(rec["topic"], []).append(rec)

    citation_lines = []
    sections = []
    period_start = filtered[0]["created_at"][:10]
    period_end = filtered[-1]["created_at"][:10]

    sections.append(f"# 研途周报\n\n**周期：{period_start} ~ {period_end}**\n")
    sections.append(f"本周共记录 **{len(filtered)}** 条学习/科研进展，涉及 **{len(by_topic)}** 个主题。\n")

    target_topics = {topic} if topic else set(by_topic.keys())
    for t in sorted(target_topics & set(by_topic.keys())):
        recs = by_topic[t]
        lines = [f"## 主题：{t}\n"]

        progresses = [r["content"].get("progress", "") for r in recs if r["content"].get("progress")]
        if progresses:
            lines.append("### 进展\n")
            for p in progresses:
                lines.append(f"- {p}")
            lines.append("")

        difficulties = [r["content"].get("difficulty", "") for r in recs if r["content"].get("difficulty")]
        if difficulties:
            lines.append("### 困难\n")
            for d in difficulties:
                lines.append(f"- {d}")
            lines.append("")

        next_steps = [r["content"].get("next_step", "") for r in recs if r["content"].get("next_step")]
        if next_steps:
            lines.append("### 下一步计划\n")
            for n in next_steps:
                lines.append(f"- {n}")
            lines.append("")

        for rec in recs:
            citation_lines.append(
                f"- memory_id: `{rec['memory_id']}` | 时间: {rec['created_at'][:19]} | 主题: {rec['topic']}"
            )

        sections.append("\n".join(lines))

    sections.append("---\n")
    sections.append("## 引用来源\n")
    sections.append("\n".join(citation_lines))
    sections.append("\n\n---\n")
    sections.append("*本报告由研途 StudyFlow 基于 PowerContext 存储记录确定性生成，未使用 LLM。*\n")

    return {
        "markdown": "\n".join(sections),
        "record_count": len(filtered),
        "citations": citation_lines,
    }


async def ensure_scope(runtime: BuiltinRuntime, topic: str) -> str:
    idem_key = f"studyflow:topic:{topic}"
    if runtime.scopes is None:
        raise RuntimeError("Scope registry unavailable")

    from powercontext.builtin.scope.errors import ScopeIdempotencyConflictError

    try:
        scope = await runtime.scopes.create(
            ScopeDraft(
                title=topic,
                summary=f"研途 StudyFlow 学习主题：{topic}",
                idempotency_key=idem_key,
            )
        )
        return scope.scope_id
    except ScopeIdempotencyConflictError:
        # Scope already exists, find it by listing
        descriptors = await runtime.scopes.list()
        for desc in descriptors:
            if desc.title == topic:
                return desc.scope_id
        raise RuntimeError(f"Scope with idempotency_key {idem_key} exists but not found in list")


async def _list_scope_records(runtime: BuiltinRuntime, scope_id: str, topic: str) -> list[dict[str, Any]]:
    entries_page = await runtime.memory.for_scope(scope_id).list()
    records = []
    if entries_page and entries_page.entries:
        for entry_record in entries_page.entries:
            entry = entry_record.entry
            parsed = parse_entry_payload(entry.text)
            if parsed:
                records.append({
                    "memory_id": entry.entry_id,
                    "topic": topic,
                    "content": {
                        "progress": parsed.get("progress", ""),
                        "difficulty": parsed.get("difficulty", ""),
                        "next_step": parsed.get("next_step", ""),
                        "notes": parsed.get("notes", ""),
                    },
                    "created_at": parsed.get("created_at", ""),
                })
    records.sort(key=lambda r: r["created_at"], reverse=True)
    return records


async def api_store_record(runtime: BuiltinRuntime, topic: str, body: dict) -> dict:
    progress = body.get("progress", "").strip()
    difficulty = body.get("difficulty", "").strip()
    next_step = body.get("next_step", "").strip()
    notes = body.get("notes", "").strip()

    if not any([progress, difficulty, next_step, notes]):
        raise ValueError("记录内容不能为空，请至少填写一项")

    scope_id = await ensure_scope(runtime, topic)
    created_at = datetime.now().isoformat()
    text = build_entry_payload(progress, difficulty, next_step, notes, created_at)

    saved = await runtime.memory.for_scope(scope_id).remember(
        RememberMemoryRequest(
            entries=(MemoryEntryInput(kind="study", text=text),)
        )
    )
    return {
        "ok": True,
        "scope_id": scope_id,
        "memory_ref": saved.memory_ref.model_dump(mode="json"),
        "created_at": created_at,
    }


async def api_recall_topic(runtime: BuiltinRuntime, topic: str) -> dict:
    scope_id = await ensure_scope(runtime, topic)
    records = await _list_scope_records(runtime, scope_id, topic)
    suggestions = deterministic_suggestions(records)
    return {
        "ok": True,
        "topic": topic,
        "scope_id": scope_id,
        "records": records,
        "suggestions": suggestions["suggestions"],
        "summary": suggestions["summary"],
    }


async def api_list_topics(runtime: BuiltinRuntime) -> dict:
    if runtime.scopes is None:
        return {"ok": True, "topics": []}
    descriptors = await runtime.scopes.list()
    topics = []
    for desc in descriptors:
        if desc.summary and desc.summary.startswith("研途 StudyFlow 学习主题"):
            topics.append({
                "scope_id": desc.scope_id,
                "title": desc.title,
                "summary": desc.summary,
            })
    return {"ok": True, "topics": topics}


async def api_weekly_report(runtime: BuiltinRuntime, topic: str | None, days: int) -> dict:
    all_records = []
    if runtime.scopes is None:
        return generate_weekly_markdown([], topic, days)

    descriptors = await runtime.scopes.list()
    for desc in descriptors:
        if not (desc.summary and desc.summary.startswith("研途 StudyFlow 学习主题")):
            continue
        if topic and desc.title != topic:
            continue
        try:
            recs = await _list_scope_records(runtime, desc.scope_id, desc.title)
            all_records.extend(recs)
        except Exception:
            continue

    return generate_weekly_markdown(all_records, topic, days)


async def api_seed_samples(runtime: BuiltinRuntime) -> dict:
    samples = [
        {
            "topic": "深度学习基础",
            "progress": "完成了 CNN 卷积神经网络的基本原理学习，理解了卷积层、池化层的作用",
            "difficulty": "反向传播的链式求导过程还不够清晰，需要复习",
            "next_step": "动手实现一个简单的 CNN 分类器（MNIST）",
            "notes": "参考了李宏毅老师的课程笔记",
        },
        {
            "topic": "深度学习基础",
            "progress": "实现了 MNIST 手写数字分类，训练集准确率 98.5%",
            "difficulty": "过拟合问题：验证集准确率只有 95%，需要加入 dropout",
            "next_step": "学习正则化方法（dropout、batch normalization）",
            "notes": "代码已提交到 GitHub",
        },
        {
            "topic": "论文阅读 - Transformer",
            "progress": "阅读了 Attention Is All You Need 的前半部分，理解了 self-attention 机制",
            "difficulty": "Multi-head attention 的拼接和投影维度变化不太理解",
            "next_step": "继续阅读论文后半部分，理解位置编码和训练细节",
            "notes": "配合了 Jay Alammar 的图解 Transformer 博客",
        },
        {
            "topic": "论文阅读 - Transformer",
            "progress": "读完整篇论文，理清了 encoder-decoder 架构",
            "difficulty": "位置编码的数学推导还需要消化",
            "next_step": "用 PyTorch 从零实现一个 mini Transformer",
            "notes": "标注了需要复习的 3 个关键公式",
        },
    ]
    created = []
    for sample in samples:
        result = await api_store_record(runtime, sample["topic"], sample)
        created.append({"topic": sample["topic"], "scope_id": result["scope_id"]})
    return {
        "ok": True,
        "seeded": len(samples),
        "topics": list({s["topic"] for s in samples}),
        "note": "样例数据为虚构的学习记录，98.5% 等数据为示例，非作品实测结果",
    }


class StudyFlowHandler(BaseHTTPRequestHandler):
    runtime: BuiltinRuntime
    loop: asyncio.AbstractEventLoop

    def log_message(self, format: str, *args: Any) -> None:
        log.info(format, *args)

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, file_path: Path) -> None:
        content = file_path.read_bytes()
        content_type = "text/html; charset=utf-8"
        if file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length < 0 or length > 65536:
            raise ValueError("请求体不得超过 64 KiB")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("请求体必须为 JSON 对象")
        return body

    def _safe_static_path(self, url_path: str) -> Path | None:
        if not url_path.startswith("/static/"):
            return None
        relative = url_path[8:]
        try:
            file_path = (STATIC_DIR / relative).resolve(strict=False)
            static_resolved = STATIC_DIR.resolve()
            if not file_path.is_relative_to(static_resolved):
                log.warning("路径遍历尝试：%s", url_path)
                return None
            if file_path.exists() and file_path.is_file():
                return file_path
        except (ValueError, OSError):
            pass
        return None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._send_html(STATIC_DIR / "index.html")
            return

        static_path = self._safe_static_path(path)
        if static_path:
            self._send_html(static_path)
            return
        if path.startswith("/static/"):
            self._send_json({"error": "Not found"}, 404)
            return

        try:
            if path == "/api/topics":
                result = asyncio.run_coroutine_threadsafe(api_list_topics(self.runtime), self.loop).result()
                self._send_json(result)
            elif path == "/api/recall":
                topic = query.get("topic", [""])[0]
                if not topic:
                    self._send_json({"error": "缺少 topic 参数"}, 400)
                    return
                result = asyncio.run_coroutine_threadsafe(api_recall_topic(self.runtime, topic), self.loop).result()
                self._send_json(result)
            elif path == "/api/weekly":
                topic_list = query.get("topic", [])
                topic = topic_list[0] if topic_list else None
                try:
                    days = int(query.get("days", ["7"])[0])
                except (ValueError, IndexError):
                    self._send_json({"error": "days 参数必须为整数"}, 400)
                    return
                result = asyncio.run_coroutine_threadsafe(api_weekly_report(self.runtime, topic, days), self.loop).result()
                self._send_json(result)
            else:
                self._send_json({"error": "Not found"}, 404)
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception as e:
            log.exception("GET %s failed", path)
            self._send_json({"error": str(e)}, 500)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._read_body()
            if path == "/api/record":
                topic = body.get("topic", "")
                if not isinstance(topic, str) or not topic.strip():
                    self._send_json({"error": "缺少主题名称"}, 400)
                    return
                result = asyncio.run_coroutine_threadsafe(
                    api_store_record(self.runtime, topic.strip(), body), self.loop
                ).result()
                self._send_json(result)
            elif path == "/api/seed":
                result = asyncio.run_coroutine_threadsafe(api_seed_samples(self.runtime), self.loop).result()
                self._send_json(result)
            else:
                self._send_json({"error": "Not found"}, 404)
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except json.JSONDecodeError as e:
            self._send_json({"error": f"JSON 解析错误：{e}"}, 400)
        except Exception as e:
            log.exception("POST %s failed", path)
            self._send_json({"error": str(e)}, 500)


async def create_runtime() -> tuple[BuiltinRuntime, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_path = DATA_DIR / "runtime.db"
    scheduler_path = DATA_DIR / "scheduler.db"
    config = BuiltinConfig(
        database=SQLiteConfig(url=f"sqlite+aiosqlite:///{db_path}")
    )
    ctx = open_builtin_runtime(config, scheduler_path=scheduler_path)
    runtime = await ctx.__aenter__()
    return runtime, ctx


def main() -> None:
    log.info("研途 StudyFlow 启动中...")
    loop = asyncio.new_event_loop()

    # Start event loop in a separate thread
    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    loop_thread = threading.Thread(target=run_loop, daemon=True)
    loop_thread.start()

    # Create runtime in the event loop
    runtime, ctx = asyncio.run_coroutine_threadsafe(create_runtime(), loop).result()
    log.info("PowerContext 运行时已就绪，数据库：%s", DATA_DIR / "runtime.db")

    handler_class = StudyFlowHandler
    handler_class.runtime = runtime
    handler_class.loop = loop

    server = HTTPServer(("127.0.0.1", 8765), handler_class)
    log.info("服务已启动：http://127.0.0.1:8765")
    log.info("按 Ctrl+C 停止服务")

    def shutdown_handler(signum: int, frame: Any) -> None:
        log.info("收到停止信号，正在关闭...")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("正在关闭 PowerContext 运行时...")
        asyncio.run_coroutine_threadsafe(ctx.__aexit__(None, None, None), loop).result()
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        server.server_close()
        log.info("服务已停止")


if __name__ == "__main__":
    main()
