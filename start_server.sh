#!/usr/bin/env bash
unset PYTHONPATH
unset PYTHONHOME
cd /c/tuc_work/yunyao_manage
exec /c/tuc_work/yunyao_manage/venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
