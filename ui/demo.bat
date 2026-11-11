@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo 找不到 Python，請先安裝 Python 3.11 以上版本。
  pause
  exit /b 1
)
%PY% -c "import customtkinter" >nul 2>nul || (
  echo 第一次執行，正在安裝 customtkinter……
  %PY% -m pip install "customtkinter>=5.2"
)
%PY% -m ui.demo
if errorlevel 1 pause
