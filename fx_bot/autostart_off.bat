@echo off
chcp 65001 > nul
rem autostart_on.bat で置いたスタートアップのショートカットを外す
powershell -NoProfile -Command "$p=[Environment]::GetFolderPath('Startup')+'\fxbot_session_bo.lnk'; if (Test-Path $p) { Remove-Item $p; 'ショートカットを外しました' } else { '登録されていません' }"
pause
