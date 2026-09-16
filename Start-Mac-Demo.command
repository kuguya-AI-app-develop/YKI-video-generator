#!/bin/zsh
set -eu
cd "$(dirname "$0")"
if ! command -v uv >/dev/null 2>&1; then
  print '请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/'
  read '?按回车关闭'
  exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  print '请先安装 FFmpeg，例如 brew install ffmpeg'
  read '?按回车关闭'
  exit 1
fi
uv venv --python 3.12 .venv --allow-existing
uv pip install --python .venv/bin/python Pillow==12.3.0
.venv/bin/python -m app serve --mode demo --open
