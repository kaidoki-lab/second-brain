@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title 第二の脳 ローカルAIを育てる

echo ============================================
echo   ローカルAI に第二の脳を覚えさせます
echo ============================================
echo.

where python > nul 2>&1
if errorlevel 1 (
  echo [エラー] python が見つかりません。
  pause
  exit /b 1
)

rem 初回だけ元のモデル名を引数で渡す（例: grow.bat qwen2.5:7b）。2回目以降は不要。
python run.py init > nul 2>&1
if "%~1"=="" (
  python run.py grow
) else (
  python run.py grow --base "%~1"
)

echo.
pause
endlocal
