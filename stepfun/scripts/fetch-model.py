#!/usr/bin/env python3
"""Download pinned public model assets and record actual byte counts / SHA256."""
import hashlib
import json
import pathlib
import subprocess
import time

MODEL = 'Xenova/all-MiniLM-L6-v2'
REVISION = '751bff37182d3f1213fa05d7196b954e230abad9'
ROOT = pathlib.Path(__file__).resolve().parents[1]
files = ['config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'onnx/model.onnx', 'onnx/model_quantized.onnx']
manifest = {'model': MODEL, 'revision': REVISION, 'files': []}
for name in files:
    destination = ROOT / 'public/models' / MODEL / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f'https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}'
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + '.part')
        subprocess.run(['curl', '-fL', '--retry', '3', '--max-time', '600', '-o', str(temporary), url], check=True)
        temporary.rename(destination)
    manifest['files'].append({'path': name, 'url': url, 'bytes': destination.stat().st_size, 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()})
shared = sum(item['bytes'] for item in manifest['files'] if not item['path'].endswith('.onnx'))
weights = {item['path']: item['bytes'] for item in manifest['files'] if item['path'].endswith('.onnx')}
manifest['fp32TotalBytes'] = shared + weights['onnx/model.onnx']
manifest['int8TotalBytes'] = shared + weights['onnx/model_quantized.onnx']
manifest['compressionRatio'] = manifest['fp32TotalBytes'] / manifest['int8TotalBytes']
manifest['measuredAtUnix'] = time.time()
(ROOT / 'results/model-sizes.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
