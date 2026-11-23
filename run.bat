@echo off
REM PURPOSE: запуск локального бота уведомлений агента.
cd /d "%~dp0"
python -m homebot.main
