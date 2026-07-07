"""启动云窑后端，避免被 Hermes agent 的 site-packages 干扰"""
import sys

# 在导入任何三方库前先清理路径
sys.path = [p for p in sys.path if 'hermes' not in p.lower()]

import uvicorn
uvicorn.run("main:app", host="0.0.0.0", port=8003)
