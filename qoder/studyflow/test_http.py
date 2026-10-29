#!/usr/bin/env python3
"""HTTP endpoint tests for StudyFlow server.

Uses tempfile for data isolation — never touches the real data/ directory.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse

BASE = "http://127.0.0.1:8765"
PASS = 0
FAIL = 0


def req(method, path, body=None, expect_status=200):
    url = BASE + path
    parsed = urllib.parse.urlsplit(url)
    safe_url = urllib.parse.urlunsplit((
        parsed.scheme, parsed.netloc,
        urllib.parse.quote(parsed.path, safe="/"),
        urllib.parse.urlencode(urllib.parse.parse_qs(parsed.query), doseq=True),
        parsed.fragment,
    ))
    data = json.dumps(body).encode("utf-8") if body else None
    headers = {"Content-Type": "application/json"} if data else {}
    r = urllib.request.Request(safe_url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=10)
        status = resp.status
        result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        status = e.code
        result = json.loads(e.read().decode("utf-8"))
    return status == expect_status, status, result


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name}  {detail}")


def find_python():
    venv = "/tmp/studyflow-clean-venv/bin/python3"
    if os.path.exists(venv):
        return venv
    powercontext_venv = os.path.join(
        os.path.dirname(__file__), "..", "..", "powercontext", ".venv", "bin", "python3"
    )
    if os.path.exists(powercontext_venv):
        return powercontext_venv
    return sys.executable


def start_server(data_dir):
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
    python = find_python()
    env = os.environ.copy()
    env["STUDYFLOW_DATA_DIR"] = data_dir
    proc = subprocess.Popen(
        [python, script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    for _ in range(40):
        try:
            urllib.request.urlopen(BASE + "/api/topics", timeout=2)
            return proc
        except Exception:
            time.sleep(0.5)
    stdout, stderr = proc.communicate(timeout=5)
    print("SERVER STDERR:", stderr.decode()[-2000:])
    proc.kill()
    raise RuntimeError("Server failed to start within 20s")


def stop_server(proc):
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def main():
    global PASS, FAIL

    print("=" * 60)
    print("StudyFlow HTTP Endpoint Tests")
    print("=" * 60)

    tmpdir = tempfile.mkdtemp(prefix="studyflow-test-")
    data_dir = os.path.join(tmpdir, "data")
    created_at_1 = ""

    try:
        print(f"\nTemp data dir: {data_dir}")
        print("\n--- Starting server (first run) ---")
        proc = start_server(data_dir)
        print("Server started")

        # Test 1: GET /api/topics (empty)
        print("\n--- Test: GET /api/topics (empty) ---")
        ok, status, result = req("GET", "/api/topics")
        check("status 200", ok, f"got {status}")
        check("ok=True", result.get("ok") is True)
        check("topics is list", isinstance(result.get("topics"), list))

        # Test 2: POST /api/record - missing topic
        print("\n--- Test: POST /api/record missing topic ---")
        ok, status, result = req("POST", "/api/record", {"progress": "test"}, expect_status=400)
        check("status 400", ok, f"got {status}")
        check("error message", "error" in result)

        # Test 3: POST /api/record - empty content
        print("\n--- Test: POST /api/record empty content ---")
        ok, status, result = req("POST", "/api/record", {"topic": "Test"}, expect_status=400)
        check("status 400", ok, f"got {status}")
        check("error message", "error" in result)

        # Test 4: POST /api/record - valid
        print("\n--- Test: POST /api/record valid ---")
        ok, status, result = req("POST", "/api/record", {
            "topic": "测试主题A",
            "progress": "完成了第一项学习",
            "difficulty": "有些概念不太清楚",
            "next_step": "继续深入学习",
            "notes": "测试笔记",
        })
        check("status 200", ok, f"got {status}: {result}")
        check("ok=True", result.get("ok") is True)
        check("has created_at", "created_at" in result)
        created_at_1 = result.get("created_at", "")
        check("created_at is ISO format", "T" in created_at_1, f"got {created_at_1}")
        print(f"  created_at = {created_at_1}")

        # Test 5: POST another record to same topic
        print("\n--- Test: POST second record same topic ---")
        time.sleep(0.1)
        ok, status, result = req("POST", "/api/record", {
            "topic": "测试主题A",
            "progress": "完成了第二项学习",
            "difficulty": "遇到了新问题",
            "next_step": "解决问题",
        })
        check("status 200", ok, f"got {status}: {result}")

        # Test 6: POST record to different topic
        print("\n--- Test: POST record to different topic ---")
        ok, status, result = req("POST", "/api/record", {
            "topic": "测试主题B",
            "progress": "主题B的第一条记录",
            "notes": "这是另一个主题",
        })
        check("status 200", ok, f"got {status}: {result}")

        # Test 7: GET /api/topics (should have 2)
        print("\n--- Test: GET /api/topics (2 topics) ---")
        ok, status, result = req("GET", "/api/topics")
        check("status 200", ok, f"got {status}")
        topics = result.get("topics", [])
        check("2 topics", len(topics) == 2, f"got {len(topics)}: {topics}")
        topic_titles = {t["title"] for t in topics}
        check("contains 测试主题A", "测试主题A" in topic_titles)
        check("contains 测试主题B", "测试主题B" in topic_titles)

        # Test 8: GET /api/recall topic A
        print("\n--- Test: GET /api/recall topic A ---")
        ok, status, result = req("GET", "/api/recall?topic=测试主题A")
        check("status 200", ok, f"got {status}: {result}")
        check("ok=True", result.get("ok") is True)
        records = result.get("records", [])
        check("2 records for topic A", len(records) == 2, f"got {len(records)}")
        if records:
            check("records have memory_id", all("memory_id" in r for r in records))
            check("records have created_at", all("created_at" in r for r in records))
            check("records sorted desc", records[0]["created_at"] >= records[-1]["created_at"])

        # Test 9: Topic isolation
        print("\n--- Test: Topic isolation ---")
        ok, status, result = req("GET", "/api/recall?topic=测试主题B")
        check("status 200", ok, f"got {status}")
        records_b = result.get("records", [])
        check("1 record for topic B", len(records_b) == 1, f"got {len(records_b)}")
        if records_b:
            check("topic B correct content",
                  records_b[0]["content"]["progress"] == "主题B的第一条记录")

        # Test 10: Missing topic param
        print("\n--- Test: GET /api/recall missing topic ---")
        ok, status, result = req("GET", "/api/recall", expect_status=400)
        check("status 400", ok, f"got {status}")

        # Test 11: Weekly report
        print("\n--- Test: GET /api/weekly ---")
        ok, status, result = req("GET", "/api/weekly")
        check("status 200", ok, f"got {status}: {result}")
        check("has markdown", "markdown" in result)
        check("has record_count", "record_count" in result)
        check("has citations", "citations" in result)
        md = result.get("markdown", "")
        check("markdown has header", "# 研途周报" in md)
        check("markdown has citations section", "引用来源" in md)
        check("markdown has memory_id citations", "memory_id:" in md)
        check("record_count is 3", result.get("record_count") == 3, f"got {result.get('record_count')}")

        # Test 12: Weekly filtered
        print("\n--- Test: GET /api/weekly filtered ---")
        ok, status, result = req("GET", "/api/weekly?topic=测试主题A")
        check("status 200", ok, f"got {status}")
        check("record_count is 2", result.get("record_count") == 2, f"got {result.get('record_count')}")

        # Test 13: Path traversal
        print("\n--- Test: Path traversal protection ---")
        ok, status, result = req("GET", "/static/../server.py", expect_status=404)
        check("status 404 for traversal", ok, f"got {status}")

        # Test 14: Invalid JSON
        print("\n--- Test: Invalid JSON body ---")
        url = BASE + "/api/record"
        r = urllib.request.Request(url, data=b"not json", headers={"Content-Type": "application/json"}, method="POST")
        try:
            resp = urllib.request.urlopen(r, timeout=10)
            status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        check("status 400 for invalid JSON", status == 400, f"got {status}")

        # Test 15: Static files
        print("\n--- Test: Static files ---")
        try:
            resp = urllib.request.urlopen(BASE + "/static/styles.css", timeout=5)
            check("styles.css 200", resp.status == 200)
            check("content-type is css", "text/css" in resp.headers.get("Content-Type", ""))
        except Exception as e:
            check("styles.css 200", False, str(e))

        try:
            resp = urllib.request.urlopen(BASE + "/static/app.js", timeout=5)
            check("app.js 200", resp.status == 200)
        except Exception as e:
            check("app.js 200", False, str(e))

        # Test 16: Multiline text
        print("\n--- Test: Multiline text ---")
        multiline = "第一行\n第二行\n第三行"
        ok, status, result = req("POST", "/api/record", {
            "topic": "多行测试",
            "progress": multiline,
        })
        check("store multiline 200", ok, f"got {status}: {result}")

        ok, status, result = req("GET", "/api/recall?topic=多行测试")
        check("recall multiline 200", ok, f"got {status}")
        records = result.get("records", [])
        if records:
            check("multiline preserved", records[0]["content"]["progress"] == multiline,
                  f"got {repr(records[0]['content']['progress'])}")

        # Test 17: Deterministic suggestions
        print("\n--- Test: Deterministic suggestions ---")
        ok, status, result = req("GET", "/api/recall?topic=测试主题A")
        check("status 200", ok, f"got {status}")
        suggestions = result.get("suggestions", [])
        check("has suggestions", len(suggestions) > 0)
        check("has summary", "summary" in result and len(result["summary"]) > 0)

        # Test 18: 404 for unknown API
        print("\n--- Test: 404 for unknown API ---")
        ok, status, result = req("GET", "/api/nonexistent", expect_status=404)
        check("status 404", ok, f"got {status}")

        # Stop first server
        print("\n--- Stopping server (first run) ---")
        stop_server(proc)
        print("Server stopped")

        # Test 19: Persistence - restart and check data survives
        print("\n--- Test: Persistence after restart ---")
        proc2 = start_server(data_dir)
        try:
            ok, status, result = req("GET", "/api/topics")
            check("status 200 after restart", ok, f"got {status}")
            topics = result.get("topics", [])
            check("topics persist after restart", len(topics) >= 2, f"got {len(topics)}")
            topic_titles = {t["title"] for t in topics}
            check("测试主题A persists", "测试主题A" in topic_titles)

            ok, status, result = req("GET", "/api/recall?topic=测试主题A")
            check("recall works after restart", ok, f"got {status}")
            records = result.get("records", [])
            check("records persist after restart", len(records) == 2, f"got {len(records)}")
            if records:
                all_times = [r["created_at"] for r in records]
                check("created_at preserved after restart",
                      created_at_1 in all_times,
                      f"expected {created_at_1}, got {all_times}")
        finally:
            stop_server(proc2)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Summary
    print("\n" + "=" * 60)
    total = PASS + FAIL
    print(f"Results: {PASS}/{total} passed, {FAIL} failed")
    print("=" * 60)

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
