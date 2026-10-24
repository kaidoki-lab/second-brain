@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title FX バックテスト

where python > nul 2>&1
if errorlevel 1 (
  echo [エラー] python が見つかりません。
  echo         python.org から Python 3 をインストールし、
  echo         インストール時に "Add python.exe to PATH" にチェックを入れてください。
  echo.
  pause
  exit /b 1
)

if not exist "data\sample_usdjpy_h1.csv" python run.py sample

echo.
python run.py backtest --csv data\sample_usdjpy_h1.csv --trades data\trades.csv
echo.
echo  本物のデータで試す方法は README.md を参照してください。
pause
endlocal
