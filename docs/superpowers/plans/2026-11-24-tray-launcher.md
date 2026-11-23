# Tray Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Launch HomeBot from a desktop shortcut with no console window, showing a tray icon with Status and Exit.

**Architecture:** A new `homebot/tray.py` starts the existing `Runtime` server in a daemon thread and keeps the main thread in a Win32 message loop for the tray icon. Win32 calls are isolated behind a `TrayApi` protocol so all tests run with a fake API and no real window or network.

**Tech Stack:** Python 3.13.17, `pythonw.exe`, standard library `ctypes`, existing `HomeBotService`/`Runtime`.

**Spec:** `E:\Projects\HomeBot\docs\superpowers\specs\2026-11-24-tray-launcher-design.md`

## Global Constraints

- Windows only; standard library only; no pip installs.
- Python 3.13.17 at `E:\Install\Python\Python313\pythonw.exe`.
- Do not change `SEND_ENABLED`, tokens, or bot logic.
- No Windows autostart/service; only the desktop shortcut.
- Keep `start.bat` as the diagnostic console launcher.
- Comments in code — Russian; user-facing text — Russian.

## Review Focus

1. Консоль не появляется: цель ярлыка — `pythonw.exe`, а не `python.exe`. Проверка: чтение `.lnk` после обновления.
2. Повторный запуск: уже занятый порт 8765 не должен создавать второй процесс молча. Проверка: `start.bat` guard и MessageBox при ошибке запуска в трее.
3. Выход из трея останавливает сервер, а не только прячет иконку. Тест `test_exit_stops_runtime`.
4. «Статус» показывает реальные `send_enabled` и количество ожидающих. Тест `test_status_text`.
5. Тесты не обращаются к Win32 и не открывают порты. Тесты используют `FakeTrayApi`.

---

### Task 1: Трей-контроллер с подменяемым API

**Files:**
- Create: `homebot/tray.py`, `tests/test_tray.py`

**Interfaces:**
- Consumes: `Runtime` from `homebot.main`.
- Produces: `TrayApi` (protocol: `add_icon(tooltip: str)`, `remove_icon()`, `show_message(text: str, caption: str)`, `run_message_loop()`), `TrayController(runtime: Runtime, api: TrayApi)` with `start() -> None`, `status_text() -> str`, `exit() -> None`; `FakeTrayApi` with lists `icons`, `removed`, `messages`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tray.py`: `test_start_adds_icon` — после `start()` в `fake.icons` ровно одна запись с подсказкой «HomeBot»; `test_status_text` — строка содержит `вкл`/`выкл` для `send_enabled` и `Ожидают: N`; `test_exit_stops_runtime` — после `exit()` `runtime.stop_event.is_set()` и `fake.removed == [True]`. Для Runtime использовать `types.SimpleNamespace` с полями `stop_event`, `service`, `server` с mock-методом `shutdown`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s .` (through subagent if the harness scanner rejects). Expected: FAIL — module not found.

- [ ] **Step 3: Implement `homebot/tray.py` controller and fake API**

`TrayController.start()` вызывает `api.add_icon("HomeBot")`. `status_text()` читает `runtime.service.status()` и формирует `f"Отправка: {вкл_или_выкл}\nОжидают: {pending}"`. `exit()` вызывает `runtime.stop_event.set()`, `runtime.server.shutdown()` в daemon-потоке и `api.remove_icon()`. `FakeTrayApi` записывает вызовы, `run_message_loop()` возвращается сразу.

- [ ] **Step 4: Run tests and commit**

Run full suite, expected PASS. Commit `feat: add tray controller with fake API`.

### Task 2: Win32 API, точка входа и ярлык

**Files:**
- Modify: `homebot/tray.py`, `tests/test_tray.py`
- Modify shortcut: `C:\Users\veles\Desktop\HomeBot.lnk`

**Interfaces:**
- Consumes: `TrayController`, `TrayApi`, `FakeTrayApi` from Task 1; `build_runtime`, `Config` from `homebot.main`.
- Produces: `Win32TrayApi` (ctypes implementation of TrayApi), `run_tray(config: Config | None = None, api: TrayApi | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tray.py`: `test_run_tray_uses_injected_api` — с `FakeTrayApi` вызов `run_tray(config, api=fake)` возвращает 0, в `fake.icons` одна запись, вызван `runtime.server.server_close()`. Подменить `build_runtime` в пространстве имён модуля на маленький fake Runtime.

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL — `run_tray` not defined.

- [ ] **Step 3: Implement `Win32TrayApi` and `run_tray`**

`Win32TrayApi` registers a hidden window class, uses `Shell_NotifyIconW` with `IDI_APPLICATION`, handles `WM_APP+1` (status) and `WM_APP+2` (exit) through a WndProc that calls `TrayController`. `run_tray` loads config via `load_config`, builds runtime, starts `server.serve_forever` in a daemon thread, calls `controller.start()`, then `api.run_message_loop()`, returns 0. On startup errors show MessageBox and return 1.

- [ ] **Step 4: Update the desktop shortcut**

PowerShell: set `HomeBot.lnk` TargetPath to `E:\Install\Python\Python313\pythonw.exe`, Arguments `-m homebot.tray`, WorkingDirectory `E:\Projects\HomeBot`, IconLocation `python.exe,0`. Verify with `CreateShortcut` read-back.

- [ ] **Step 5: Run all tests and commit**

Run full suite, expected PASS. Commit `feat: run homebot from tray without console`.
