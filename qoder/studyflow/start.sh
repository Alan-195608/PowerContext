#!/bin/bash
# 研途 StudyFlow 启动脚本
# 支持独立部署，不依赖特定本机目录结构

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
LOCKFILE="${SCRIPT_DIR}/.venv-ready"

# PowerContext 固定版本（对应上游 commit dab240063bfcfa7917898dc44da4baadb3747bd0）
POWERCONTEXT_VERSION="1.2.0"

echo "==================================="
echo "  研途 StudyFlow — 学习科研进度助手"
echo "==================================="
echo ""

# 优先级：
# 1. POWERCONTEXT_PYTHON 环境变量（开发者覆盖）
# 2. 本地 .venv（自动安装）
# 3. 邻近 powercontext/.venv（开发环境兼容）

if [ -n "$POWERCONTEXT_PYTHON" ] && [ -x "$POWERCONTEXT_PYTHON" ]; then
    PYTHON="$POWERCONTEXT_PYTHON"
    echo "使用 POWERCONTEXT_PYTHON：$PYTHON"
elif [ -f "${VENV_DIR}/bin/python3" ]; then
    PYTHON="${VENV_DIR}/bin/python3"
    echo "使用本地虚拟环境：$PYTHON"
elif [ -f "${SCRIPT_DIR}/../../powercontext/.venv/bin/python3" ]; then
    PYTHON="${SCRIPT_DIR}/../../powercontext/.venv/bin/python3"
    echo "使用邻近 powercontext 虚拟环境：$PYTHON"
else
    echo "未找到 PowerContext Python 环境，正在创建本地虚拟环境..."
    echo ""

    if ! command -v python3 &>/dev/null; then
        echo "错误：未找到 python3，请先安装 Python 3.11+"
        exit 1
    fi

    PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

    if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
        echo "错误：需要 Python 3.11+，当前版本：$PY_VERSION"
        exit 1
    fi

    python3 -m venv "$VENV_DIR"
    echo "虚拟环境已创建：$VENV_DIR"
    echo ""
    echo "正在安装 powercontext[builtin]==${POWERCONTEXT_VERSION}..."
    "${VENV_DIR}/bin/pip" install --upgrade pip -q
    "${VENV_DIR}/bin/pip" install "powercontext[builtin]==${POWERCONTEXT_VERSION}" -q
    PYTHON="${VENV_DIR}/bin/python3"
    echo "安装完成"
    echo ""
fi

# 验证 powercontext 可导入
if ! "$PYTHON" -c "import powercontext" 2>/dev/null; then
    echo "错误：powercontext 模块不可导入"
    echo "请检查 Python 环境：$PYTHON"
    exit 1
fi

PC_VERSION=$("$PYTHON" -c "import powercontext; print(getattr(powercontext, '__version__', 'unknown'))" 2>/dev/null || echo "unknown")
echo "PowerContext 版本：$PC_VERSION"
echo ""
echo "PowerContext 数据库目录：${SCRIPT_DIR}/data/"
echo "服务地址：http://127.0.0.1:8765"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

exec "$PYTHON" "$SCRIPT_DIR/server.py"
