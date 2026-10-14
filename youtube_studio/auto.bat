@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title YouTube STUDIO 自動制作

rem 毎日の自動実行（schedule.bat が登録する）。手でダブルクリックしても同じ。
rem 再生数を取り込み → 企画 → 1本作って確認待ちへ。結果は logs\auto.log にも残す。
if not exist logs mkdir logs
echo [%date% %time%] 開始 >> logs\auto.log
python run.py auto >> logs\auto.log 2>&1
set "RC=%errorlevel%"
echo [%date% %time%] 終了 (コード %RC%) >> logs\auto.log
if "%~1"=="" (
  powershell -NoProfile -Command "Get-Content -Encoding UTF8 -Tail 8 logs\auto.log"
  pause
)
exit /b %RC%
