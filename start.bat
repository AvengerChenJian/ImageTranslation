@echo off
title 商品图翻译 - 服务运行中（请勿关闭此窗口）
cd /d %~dp0

echo 正在启动服务... http://127.0.0.1:8000
echo 关闭此窗口即可停止服务
echo.

python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

echo.
echo 服务已停止
pause
