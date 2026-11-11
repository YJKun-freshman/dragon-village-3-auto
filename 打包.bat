@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo 找不到 Python。
  pause
  exit /b 1
)
%PY% -c "import cv2, numpy, customtkinter" >nul 2>nul || %PY% -m pip install -r requirements.txt
%PY% build.py
pause
