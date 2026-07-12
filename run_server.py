"""启动服务器前先释放端口 8008"""
import socket
import subprocess
import sys
import os

PORT = 8008

# 先强制绑定释放端口
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.settimeout(1)
try:
    s.bind(('0.0.0.0', PORT))
    s.close()
except OSError:
    pass

# 用项目 venv 的 python 启动 uvicorn
venv_python = os.path.join(os.path.dirname(__file__), '.venv', 'Scripts', 'python.exe')
os.environ.pop('PYTHONPATH', None)

subprocess.run([
    venv_python, '-m', 'uvicorn',
    'main:app',
    '--host', '0.0.0.0',
    '--port', str(PORT),
], env={**os.environ, 'PYTHONPATH': ''})
