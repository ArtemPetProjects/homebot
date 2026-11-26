# План рефакторинга HomeBot (чистая архитектура)

## Цель
Перестроить Python-код HomeBot по чистой архитектуре, SOLID, GRASP, YAGNI:
- тонкий интерфейс (бот/HTTP/handlers) — слой `api`
- application use case — слой `application`
- доменные модели и правила — слой `domain`
- инфраструктурные адаптеры (Telegram, HTTP, файлы, сеть) — слой `infrastructure`

Сеть и бизнес-логикаcurrently смешаны в `service.py` и `network.py` — разнести.

## Слои (по обновлённому AGENTS.md)
`api` (не `interface`), `application`, `domain`, `infrastructure`.

## Состав слоёв

### domain (не зависит от requests/urllib/telegram/socket/subprocess)
- `domain/models.py` — `Event`, `Ask`, `Answer`, `PendingAsk` (entities/value objects), валидация
- `domain/devices.py` — `Device` (value object устройства), `DeviceInfo`, `DeviceRegistry` (домен реестра, без network)

### application (оркестрация через порты, не зависит от инфраструктуры)
- `application/ports.py` — интерфейсы/порты (Protocol): `TelegramGateway`, `NetworkScanner`, `Outbox`, `PendingRepository`, `AnswerRepository`, `OffsetStore`
- `application/use_cases.py` — `HomeBotUseCase` (бывший `HomeBotService`): координация уведомлений/запросов/ответов/команд через порты

### infrastructure (конкретные адаптеры)
- `infrastructure/telegram.py` — `TelegramTransport`, `HttpTelegramTransport`, `FakeTelegramTransport`, хелперы callback/клавиатур/форматирования
- `infrastructure/network.py` — `scan_network`, `raw_ping`, `ping_probe` (socket, subprocess)
- `infrastructure/router.py` — `RouterClient` (urllib)
- `infrastructure/router_crypto.py` — AES-CBC (перенос без изменений)
- `infrastructure/store.py` — `Store` (файловое хранилище, перенос без изменений)
- `infrastructure/inbox.py` — `Inbox` (файловый ящик, перенос без изменений)

### api (тонкий интерфейс, перевод HTTP/бот в use case)
- `api/bridge.py` — HTTP-сервер (тонкий контроллер -> use cases)
- `api/poller.py` — опрос Telegram
- `api/supervisor.py` — резервный режим
- `api/tray.py` — трей
- `api/main.py` — композиция/сборка, `build_runtime`, `main`

`homebot/config.py` — конфигурация (остаётся на месте).

## Сохраняем
- все публичные команды бота (/start, /help, /info, /ping, /status, /label, /devices, /nextdown, "Отправить агенту") и формат ответов
- протокол обмена с ботом и очередями (outbox, pending, answers, offset)

## Шаги
1. Baseline: `python -m pytest -q` = 98 passed (уже подтверждено)
2. Добавить `tests/test_architecture.py` (домен без импортов requests/urllib/telegram/socket/subprocess), подтвердить, что ловит нарушение
3. Разнести код по слоям, выделить порты и use case
4. Убрать дублирование/boilerplate, нет абстракций без потребителя
5. `python -m pytest -q` зелёно, архитектурный тест PASS
6. Локальный коммит `refactor(homebot): apply clean architecture and ports`
7. Удалить worktree, подтвердить в отчёте
