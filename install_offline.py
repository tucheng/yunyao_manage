#!/usr/bin/env python3
"""完全离线安装 pip 和项目依赖，无需网络"""
import os
import sys
import zipfile
import subprocess
import shutil
import glob
import importlib.util

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WHEELS_DIR = os.path.join(BASE_DIR, 'wheels')

def install_pip():
    """从 wheel 文件离线安装 pip"""
    pip_wheels = glob.glob(os.path.join(WHEELS_DIR, 'pip-*.whl'))
    if not pip_wheels:
        print("❌ 找不到 pip wheel 文件")
        sys.exit(1)
    pip_wheel = pip_wheels[0]
    print(f"📦 发现 pip wheel: {os.path.basename(pip_wheel)}")

    # 获取 Python 的 site-packages 路径
    site_packages = subprocess.check_output(
        [sys.executable, '-c', 'import site; print(site.getsitepackages()[0])'],
        text=True
    ).strip()

    # 直接把 wheel 解压到 site-packages
    print(f"📂 安装 pip 到 {site_packages} ...")
    with zipfile.ZipFile(pip_wheel, 'r') as zf:
        zf.extractall(site_packages)
    print("✅ pip 安装完成")

def main():
    print("=== 离线安装所有依赖 ===")
    
    # 1. 安装 pip（如果还没有的话）
    result = subprocess.run([sys.executable, '-m', 'pip', '--version'], 
                          capture_output=True, text=True)
    if result.returncode != 0:
        install_pip()
    
    # 2. 验证 pip 可用
    result = subprocess.run([sys.executable, '-m', 'pip', '--version'], 
                          capture_output=True, text=True)
    print(f"📋 pip 版本: {result.stdout.strip()}")
    
    # 3. 离线安装项目依赖
    print("📦 安装项目依赖...")
    result = subprocess.run([
        sys.executable, '-m', 'pip', 'install',
        '--break-system-packages',
        '--no-index',
        '--find-links', WHEELS_DIR,
        '-r', os.path.join(BASE_DIR, 'requirements.txt')
    ], cwd=BASE_DIR)
    
    if result.returncode != 0:
        print(f"❌ 依赖安装失败 (code {result.returncode})")
        sys.exit(result.returncode)
    
    # 4. 验证
    print("\n✅ 所有依赖安装完成！")
    print("=== 验证后端路由 ===")
    sys.path.insert(0, BASE_DIR)
    try:
        from main import app
        print(f"✅ 后端加载成功: {len(app.routes)} 个路由")
    except Exception as e:
        print(f"⚠️ 路由验证跳过: {e}")
        print("但依赖已装好，后续可以手动验证")

if __name__ == '__main__':
    main()
