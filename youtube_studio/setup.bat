@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title YouTube STUDIO 準備

echo ============================================
echo   YouTube STUDIO の準備をします（最初の1回だけ）
echo ============================================
echo.

where python > nul 2>&1
if errorlevel 1 (
  echo [エラー] python が見つかりません。
  echo         python.org から Python 3 を入れ、"Add python.exe to PATH" にチェックしてください。
  pause
  exit /b 1
)

echo [1/4] Python の部品を入れます...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo [エラー] pip install に失敗しました。インターネット接続を確認してください。
  pause
  exit /b 1
)

echo [2/4] ffmpeg（動画を組み立てる道具）を確認します...
where ffmpeg > nul 2>&1
if errorlevel 1 (
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo [注意] ffmpeg を自動で入れられませんでした。https://ffmpeg.org から入れてください。
  ) else (
    echo  ffmpeg を入れました。この画面を閉じて開き直すと使えるようになります。
  )
)

echo [3/4] VOICEVOX（読み上げ音声）を確認します...
curl -s -o nul http://127.0.0.1:50021/version
if errorlevel 1 (
  echo  VOICEVOX が起動していません。入っていなければ入れます...
  winget install -e --id HiroshibaKazuyuki.VOICEVOX --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo [注意] 自動で入れられませんでした。公式サイトから入れてください:
    start "" https://voicevox.hiroshiba.jp/
  )
  echo  VOICEVOX を起動したままにしておくと、動画づくりに使われます。
)

echo [4/4] チャンネルのことを教えてください。
echo.
python run.py setup
echo.
python run.py check
echo.
echo  準備ができたら schedule.bat で「毎日1本」を自動にできます。
pause
endlocal
