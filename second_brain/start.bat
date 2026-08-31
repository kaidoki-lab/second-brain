@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title 第二の脳

echo ============================================
echo   第二の脳
echo ============================================

where python > nul 2>&1
if errorlevel 1 (
  echo [エラー] python が見つかりません。
  echo         python.org から Python 3 をインストールし、
  echo         インストール時に "Add python.exe to PATH" にチェックを入れてください。
  pause
  exit /b 1
)

rem 初回だけデータベースと役割を用意する（2回目以降は何も起きない）
python run.py init > nul

echo.
echo  ブラウザが自動で開きます。開かない場合は次のURLを開いてください:
echo    http://127.0.0.1:8765
echo.
echo  終了するには、この黒い画面で Ctrl + C を押してください。
echo.

python run.py serve --open

endlocal
pause
