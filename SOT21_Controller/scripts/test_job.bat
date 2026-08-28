@echo off
chcp 65001 > nul
echo SOT21 TEST BAT
echo time     : %DATE% %TIME%
echo host     : %COMPUTERNAME%
echo result   : OK
exit /b 0
