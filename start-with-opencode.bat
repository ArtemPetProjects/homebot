@echo off
chcp 65001 >nul
REM PURPOSE: запустить HomeBot в трее и затем OpenCode.
cd /d "%~dp0"
netstat -ano | findstr ":8765 " >nul
if %errorlevel%==1 (
  start "" "E:\Install\Python\Python313\pythonw.exe" -m homebot.tray
)
start "" "C:\Users\veles\AppData\Local\Programs\ai.opencode.desktop\OpenCode.exe"
