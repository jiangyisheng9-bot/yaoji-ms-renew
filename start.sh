#!/bin/bash
# 妖姬马来手机号 — 启动脚本
cd "$(dirname "$0")"
export FLASK_APP=app.py
export FLASK_ENV=production

# 安装依赖
pip3 install flask --quiet 2>/dev/null

echo "🚀 妖姬马来手机号 — http://localhost:5002"
python3 app.py
