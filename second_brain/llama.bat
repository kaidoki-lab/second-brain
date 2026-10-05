@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title 第二の脳 Llama を入れる

echo ============================================
echo   Llama を入れて、第二の脳を覚えさせます
echo ============================================
echo.
rem 使うモデル（引数で変更可）: llama.bat llama3.2:3b
set "MODEL=%~1"
if "%MODEL%"=="" set "MODEL=llama3.1:8b"

where python > nul 2>&1
if errorlevel 1 (
  echo [エラー] python が見つかりません。
  pause
  exit /b 1
)

rem --- Ollama の確認（無ければ winget で入れる）--------------------------
set "OLLAMA=ollama"
where ollama > nul 2>&1
if errorlevel 1 (
  if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
  ) else (
    echo  Ollama が入っていないので、インストールします...
    winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
      echo [エラー] 自動インストールに失敗しました。
      echo         https://ollama.com/download から入れてから、もう一度実行してください。
      pause
      exit /b 1
    )
    set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
  )
)

rem --- Ollama が動いていなければ起動する --------------------------------
"%OLLAMA%" list > nul 2>&1
if errorlevel 1 (
  echo  Ollama を起動しています...
  start "" /min "%OLLAMA%" serve
  timeout /t 5 /nobreak > nul
)

echo  モデル: %MODEL%
echo  初回はダウンロードに数分〜数十分かかります。
echo.
python run.py init > nul 2>&1
python run.py grow --base "%MODEL%" --pull
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

echo.
echo  完了しました。start.bat で起動し「ローカルAI」から話しかけてください。
echo.
pause
endlocal
