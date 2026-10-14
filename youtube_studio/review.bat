@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title YouTube STUDIO 確認画面

echo  確認画面を開きます。スマホやSOT21からは下に出るアドレスを開いてください。
echo.
python run.py review --open
pause
endlocal
