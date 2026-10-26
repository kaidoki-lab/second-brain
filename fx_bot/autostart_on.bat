@echo off
chcp 65001 > nul
cd /d "%~dp0"
rem Windows にサインインしたとき mt5_session_bo.bat を自動で起動する（スタートアップにショートカットを置く）
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\fxbot_session_bo.lnk'); $s.TargetPath='%~dp0mt5_session_bo.bat'; $s.WorkingDirectory='%~dp0'; $s.Save()"
if errorlevel 1 (
  echo [エラー] 登録できませんでした
) else (
  echo 登録しました。次回サインイン時から自動で起動します（やめるときは autostart_off.bat）
  echo ※ MT5 は bot が自動で起動します。PC の再起動後はサインインするまで動きません
)
pause
