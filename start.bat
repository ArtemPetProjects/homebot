@echo off
chcp 65001 >nul
REM PURPOSE: запуск HomeBot-посредника между агентом и Telegram с защитой от второго экземпляра.
cd /d "%~dp0"
netstat -ano | findstr ":8765 " >nul
if %errorlevel%==0 (
  echo HomeBot уже запущен — второй экземпляр не нужен.
  exit /b 0
)
echo Запуск HomeBot...
python -m homebot.main
echo HomeBot остановлен.
pause
