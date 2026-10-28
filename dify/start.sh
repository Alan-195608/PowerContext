#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo '请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/'; exit 1; }
if [[ ! -x .venv/bin/powercontext ]]; then
  uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python 'powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@dab240063bfcfa7917898dc44da4baadb3747bd0'
fi
export POWERCONTEXT_HOME="$PWD/.runtime/powercontext"
export POWERCONTEXT_URL=http://127.0.0.1:18765
mkdir -p .runtime
.venv/bin/powercontext server run --no-env-file --port 18765 > .runtime/powercontext.log 2>&1 &
pc_pid=$!
trap 'kill "$pc_pid" 2>/dev/null || true' EXIT
.venv/bin/python - <<'PY'
import time
from urllib.request import urlopen
for _ in range(120):
    try:
        with urlopen('http://127.0.0.1:18765/health/live', timeout=1):
            break
    except OSError:
        time.sleep(0.5)
else:
    raise SystemExit('PowerContext 启动失败，查看 .runtime/powercontext.log')
PY
printf '便利店后端：http://127.0.0.1:18766\n另开终端运行：python3 play.py\n'
.venv/bin/python game.py
