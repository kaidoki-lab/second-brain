@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title 第二の脳

echo ============================================
echo   第二の脳 を起動します
echo ============================================
echo.

rem --- 置き場所の確認 -------------------------------------------------
if not exist "run.py" (
  echo [エラー] このフォルダに run.py がありません。
  echo.
  echo   このファイル ^(start.bat^) と run.py は同じフォルダに置いてください。
  echo   ZIPを展開したとき、フォルダが二重になっていることがあります。
  echo   正しい形:  C:\second-brain\second_brain\run.py
  echo.
  pause
  exit /b 1
)

rem --- Python の確認 --------------------------------------------------
where python > nul 2>&1
if errorlevel 1 (
  echo [エラー] python が見つかりません。
  echo         python.org から Python 3 をインストールし、
  echo         インストール時に "Add python.exe to PATH" にチェックを入れてください。
  echo.
  pause
  exit /b 1
)

rem --- 初回のみデータベースを用意（2回目以降は何も起きない）-----------
python run.py init > nul 2>&1
if errorlevel 1 (
  echo [エラー] 初期化に失敗しました。詳細:
  python run.py init
  echo.
  pause
  exit /b 1
)

echo  ブラウザが自動で開きます。
echo  開かない場合は、下に表示されるアドレスをブラウザに入力してください。
echo.

python run.py serve --open

echo.
echo  サーバーが終了しました。
pause
endlocal
