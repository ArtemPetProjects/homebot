# Исправление: кнопка «Устройства» не возвращала вывод на телефоне

Дата: 25.11.2026. Изолированный worktree: `C:\Users\veles\AppData\Local\Temp\opencode\fix-homebot-devices`, HEAD до правок `a4c3bee` (detached). Живой репозиторий `E:\Projects\HomeBot`, другие worktree, `.env`, токены и state-логи с секретами не трогались. Пуш не выполнялся.

## Причины (по диагнозу `homebot-devices-diag.md`)

1. `subprocess.STARTUPINFO`/`creationflags` — Windows-only, на Termux дают `AttributeError` до отправки ответа.
2. `_scan_devices()` в `/devices` без `try/except`: исключение прерывает обработку, ответ не отправляется.
3. Ответы на команды не сохранялись в outbox: разовый сбой `sendMessage` = потеря ответа без повтора.
4. `drain_outbox()` вызывался только при старте и всегда слал в `config.chat_id`, теряя клавиатуру.

## Исправления

- **F1.** `homebot/network.py`: `_hidden_subprocess_kwargs()` возвращает `{}` при `os.name != "nt"`; это убирает `AttributeError` и в `ping_probe()`, и в ARP-провайдере.
- **F1.** `homebot/service.py`: `handle_command("/devices")` оборачивает `_scan_devices()` в `try/except`, добавляет строку «Сканирование на этом устройстве недоступно» и всё равно отправляет ответ с клавиатурой.
- **F2.** `homebot/service.py`: новый `_send_reply(chat_id, text, reply_markup=None)` пишет запись `kind="reply"` с `chat_id` и клавиатурой в outbox, отправляет, при успехе вызывает `mark_delivered`; при сбое запись остаётся на повтор. Используется для `/devices`, `/nextdown`, `/status` и остальных текстовых команд, сообщений агенту и подтверждения кнопки.
- **F2.** `drain_outbox()` шлёт в `record.get("chat_id", config.chat_id)` и передаёт сохранённый `reply_markup`; лимит 3 попытки сохранён.
- **F2b.** `homebot/poller.py`: `service.drain_outbox()` вызывается в каждом цикле `run()` (в том числе в режиме ожидания), ошибки логируются по типу исключения.

## TDD: RED → GREEN

Базовый прогон до правок: `python -m unittest discover -s tests -v` → **91 тест, OK, exit 0**.

`python -m pytest --version` → **exit 1**, `No module named pytest` (pytest в этой среде не установлен). Для стабильного запуска добавлен `verify.py` — локальный раннер на `unittest`-дискавери с exit code 0/1; все последующие прогоны — `python verify.py` (при необходимости через `cmd /c` из-за ограничений сканера shell).

| Цикл | Что проверял | RED | GREEN |
| --- | --- | --- | --- |
| A (F1 network) | не-Windows kwargs и отсутствие Windows-аргументов в `ping_probe` | 93 теста: 2 failures | 93 теста, OK |
| B (F1 /devices) | ответ при падении `_scan_devices()` | 94 теста: 1 error (`RuntimeError` из сканера) | 94 теста, OK |
| C (F2 outbox) | запись ответа с `chat_id`/клавиатурой, очередь при сбое отправки, повтор в нужный чат | 97 тестов: 1 failure + 2 errors | 97 тестов, OK |
| D (F2b poller) | повтор недоставленного ответа, пока поллер жив | 98 тестов: 1 failure | 98 тестов, OK |

Финальная проверка: `python verify.py` → **98 тестов, OK, exit code 0**.

## Изменённые файлы

- `homebot/network.py`
- `homebot/service.py`
- `homebot/poller.py`
- `tests/test_network.py` (2 новых теста)
- `tests/test_service.py` (4 новых теста)
- `tests/test_poller.py` (1 новый тест)
- `verify.py` (локальный раннер без внешних зависимостей)
- `FIX-HOMEBOT.md` (этот отчёт)

## Коммит

`7847b4e` — `fix: keep device replies on Android and retry outbox` (detached HEAD в изолированном worktree, без пуша).

## Вне scope

Не менялись F3/F4 из диагноза: двойной опрос ПК/телефона и настройки `ALLOW_LAN`/`STANDBY_PC_URL`, раскатка актуального кода на телефон по USB. Для реального подтверждения нужно подключить телефон и нажать «Устройства», сверив новый ответ и запись `kind="reply"` в outbox телефона.
