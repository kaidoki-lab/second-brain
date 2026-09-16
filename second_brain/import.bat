@echo off
setlocal
cd /d "%~dp0"
title 第二の脳 データ取り込み

echo ============================================
echo   第二の脳 にデータを取り込みます
echo ============================================
echo.

set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=input.txt"

if not exist "%TARGET%" (
  echo [エラー] ファイルが見つかりません: %TARGET%
  echo.
  echo   取り込みたいテキストファイルを、このフォルダに
  echo   input.txt という名前で置いてください。
  echo   （または、ファイルをこの import.bat にドラッグ＆ドロップ）
  echo.
  pause
  exit /b 1
)

where python > nul 2>&1
if errorlevel 1 (
  echo [エラー] python が見つかりません。
  pause
  exit /b 1
)

python run.py init > nul 2>&1
python run.py load --file "%TARGET%"

echo.
echo  start.bat で起動して、ブラウザで確認してください。
echo.
pause
endlocal
