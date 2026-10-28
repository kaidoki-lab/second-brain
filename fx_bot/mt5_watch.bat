@echo off
chcp 65001 > nul
setlocal
title fx_bot 見張り (watch)
cd /d "%~dp0"

where python > nul 2>&1
if errorlevel 1 (
  echo [エラー] python が見つかりません。mt5_demo.bat と同じ準備をしてください。
  pause
  exit /b 1
)

echo ============================================
echo   動いている bot の状態ファイル（data\ 以下の state_*.json）を1分ごとに見ます
echo   10分更新がない bot は「停止の疑い」、正常に止まった bot は「停止しました」と出します
echo   ログ: data\watch\  止めるときは Ctrl+C
echo ============================================
echo.
python run.py watch
echo.
echo 終了しました。
pause
endlocal
