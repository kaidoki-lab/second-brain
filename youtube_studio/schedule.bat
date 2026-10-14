@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title YouTube STUDIO 毎日の自動実行

rem 毎日 5:00 に auto.bat を実行するよう Windows のタスクスケジューラに登録する。
rem 時刻を変えるとき: schedule.bat 07:30   やめるとき: schedule.bat off
set "AT=%~1"
if /i "%AT%"=="off" (
  schtasks /delete /tn "YouTubeStudio" /f
  echo  毎日の自動実行をやめました。
  pause
  exit /b 0
)
if "%AT%"=="" set "AT=05:00"

schtasks /create /tn "YouTubeStudio" /sc daily /st %AT% /f ^
  /tr "\"%~dp0auto.bat\" quiet"
if errorlevel 1 (
  echo [エラー] 登録できませんでした。
  pause
  exit /b 1
)
echo.
echo  毎日 %AT% に1本作って、確認待ちに入れます。
echo  PCの電源が入っている必要があります。
echo  確認は review.bat（またはスマホ・SOT21）から。
pause
endlocal
