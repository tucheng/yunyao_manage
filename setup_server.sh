#!/bin/bash
set -e

cd /opt/yunyao

# 1. 建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 2. 离线安装所有依赖（从 wheels/）
pip install --no-index --find-links=wheels -r requirements.txt

# 3. 建数据库和用户
mysql -e "CREATE DATABASE IF NOT EXISTS yunyao CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -e "CREATE USER IF NOT EXISTS 'yunyao'@'localhost' IDENTIFIED BY 'Yunyao@2024';"
mysql -e "GRANT ALL PRIVILEGES ON yunyao.* TO 'yunyao'@'localhost';"
mysql -e "FLUSH PRIVILEGES;"
echo "数据库配置完成"

# 4. 验证
PYTHONPATH=/opt/yunyao venv/bin/python -c "from main import app; print('OK:', len(app.routes), 'routes')"

# 5. 配置 systemd
cat > /etc/systemd/system/yunyao.service << 'UNIT'
[Unit]
Description=Yunyao Backend API
After=network.target mysql.service

[Service]
WorkingDirectory=/opt/yunyao
Environment=PYTHONPATH=/opt/yunyao
ExecStart=/opt/yunyao/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8003
Restart=always
User=root

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable yunyao
systemctl start yunyao
echo "服务已启动"
