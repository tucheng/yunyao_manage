"""云窑后端启动器 - 预绑定 socket 后传给 uvicorn"""
import socket
import os

PORT = 8008

os.environ.pop('PYTHONPATH', None)

# 1. 创建并绑定 socket（SO_REUSEADDR 确保能抢到）
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('0.0.0.0', PORT))
sock.listen(128)
print(f'Bound to port {PORT}, passing fd to uvicorn')

# 2. 把 socket 传给 uvicorn
import uvicorn

config = uvicorn.Config(
    "main:app",
    host="0.0.0.0",
    port=PORT,
    log_level="info",
)
config.setup()
# 用预绑定的 socket 替换
server = uvicorn.Server(config)
server.servers = []
import asyncio
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# 直接使用我们绑定的 socket
server.sockets = [sock]
loop.run_until_complete(server.serve())
