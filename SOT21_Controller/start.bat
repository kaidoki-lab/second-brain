@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title SOT21 HOME CONTROL

echo ============================================
echo  SOT21 LAN CONTROLLER
echo ============================================

rem --- 1) Python の確認 -----------------------------------------------
where python > nul 2>&1
if errorlevel 1 (
  echo [ERROR] python が見つかりません。Python 3 をインストールしてください。
  pause
  exit /b 1
)

rem --- 2) 仮想環境の確認・作成 ----------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo [SETUP] 仮想環境を作成します...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] 仮想環境の作成に失敗しました。
    pause
    exit /b 1
  )
  set FRESH=1
)

set PY=.venv\Scripts\python.exe

rem --- 3) 必要ライブラリの確認 ----------------------------------------
"%PY%" -c "import flask, psutil" > nul 2>&1
if errorlevel 1 (
  echo [SETUP] 必要ライブラリをインストールします...
  "%PY%" -m pip install --upgrade pip > nul
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] ライブラリのインストールに失敗しました。
    pause
    exit /b 1
  )
)

rem --- 4) ファイアウォール: プライベートネットワークのみ TCP 5000 を許可 ---
netsh advfirewall firewall show rule name="SOT21 Controller" > nul 2>&1
if errorlevel 1 (
  echo [SETUP] ファイアウォール規則を追加します（プライベートのみ / 要管理者権限）
  netsh advfirewall firewall add rule name="SOT21 Controller" dir=in action=allow ^
    protocol=TCP localport=5000 profile=private > nul 2>&1
  if errorlevel 1 (
    echo [WARN] 規則を追加できませんでした。
    echo        管理者として実行するか、手動で TCP 5000 をプライベートのみ許可してください。
  )
)

rem --- 5) 起動 ---------------------------------------------------------
echo.
echo  SOT21 からは http://[このPCのIPv4]:5000 を開いてください。
echo  停止するには Ctrl+C を押してください。
echo.
"%PY%" app.py

endlocal
pause
