#!/bin/bash
# 云窑后端启动脚本（服务器用）
cd "$(dirname "$0")"
export PYTHONPATH="$PWD"
exec venv/bin/uvicorn main:app --host 127.0.0.1 --port 8003
