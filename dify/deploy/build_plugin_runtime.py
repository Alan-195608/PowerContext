"""Build a runtime around the unchanged official Plugin Daemon 0.5.3 binary.

Default: extract files from the official image using Docker. --layer can instead
use the verified ARM64 layer archive exported from a containerd content store.
No daemon source or executable is modified.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = "langgenius/dify-plugin-daemon:0.5.3-local"
TAG = "dify-loop-plugin-daemon:0.5.3"
ARM_LAYER = "1216f91ab6251f6414597a8ec3b09c730389f09b4449126482b1e36d5865896c"
parser = argparse.ArgumentParser()
parser.add_argument(
    "--layer",
    type=Path,
    help="Official ARM64 layer archive, SHA256 checked before extraction",
)
args = parser.parse_args()
target = ROOT / ".runtime/plugin-runtime"
(target / "app").mkdir(parents=True, exist_ok=True)
if args.layer:
    digest = hashlib.sha256(args.layer.read_bytes()).hexdigest()
    if digest != ARM_LAYER:
        raise SystemExit("Official layer SHA256 mismatch")
    with tarfile.open(args.layer, "r:gz") as archive:
        for name in ["app/main", "app/entrypoint.sh"]:
            source = archive.extractfile(name)
            if source is None:
                raise RuntimeError("Missing official file: " + name)
            (target / name).write_bytes(source.read())
            (target / name).chmod(0o755)
else:
    container = "dify-plugin-source-" + uuid.uuid4().hex[:10]
    subprocess.run(
        ["docker", "create", "--name", container, OFFICIAL],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    try:
        for name in ["main", "entrypoint.sh"]:
            subprocess.run(
                [
                    "docker",
                    "cp",
                    container + ":/app/" + name,
                    str(target / "app" / name),
                ],
                check=True,
            )
    finally:
        subprocess.run(
            ["docker", "rm", container], check=True, stdout=subprocess.DEVNULL
        )
shutil.copyfile(ROOT / "deploy/Dockerfile.plugin-daemon", target / "Dockerfile")
subprocess.run(
    ["docker", "build", "--network", "none", "-t", TAG, str(target)], check=True
)
metadata = {
    "runtime_image": TAG,
    "official_binary_source": OFFICIAL,
    "base_image": "langgenius/dify-api:1.13.0",
    "binary_modified": False,
    "main_sha256": hashlib.sha256((target / "app/main").read_bytes()).hexdigest(),
    "entrypoint_sha256": hashlib.sha256(
        (target / "app/entrypoint.sh").read_bytes()
    ).hexdigest(),
}
if args.layer:
    metadata["source_layer_sha256"] = ARM_LAYER
(ROOT / "evidence/dify").mkdir(parents=True, exist_ok=True)
(ROOT / "evidence/dify/plugin-runtime.json").write_text(json.dumps(metadata, indent=2))
print("Built", TAG)
