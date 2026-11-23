# Home Bot — локальный бот уведомлений агента

Отдельная небольшая программа на Windows, которая принимает события от агента по локальному
HTTP и доставляет их в Telegram. Подтверждения с вариантами ответа приходят обратно агентам
через inline-кнопки. Не часть APK дневника калорий, автозапуск и служба Windows не ставятся.

## Безопасность

- HTTP-сервер слушает **только `127.0.0.1`**. Запуск на `0.0.0.0` или LAN-адресе конфиг отклоняет.
- Каждый запрос требует заголовок `X-HomeBot-Key`; сравнение константное (`hmac.compare_digest`).
- Тело запроса ограничено 64 КБ, принимается только `Content-Type: application/json`.
- Внешний доступ — только исходящие HTTPS-запросы к `api.telegram.org`.
- Токен бота, ID чата и локальный ключ хранятся в `.env`, который не коммитится и не печатается.
- По умолчанию `SEND_ENABLED=0`: программа **вообще не обращается к Telegram**, включая опрос.
- Порт открыт, только пока запущен процесс. Автозапуск не 설정лен.

## Установка

1. Откройте `.env` в блокноте. Заполните только два поля:
   - `TELEGRAM_BOT_TOKEN=` — токен бота от @BotFather;
   - `TELEGRAM_CHAT_ID=` — ID чата, куда слать сообщения.
   `LOCAL_API_KEY` уже сгенерирован локально, его менять не нужно. **`SEND_ENABLED` оставьте `0`.**
2. Запустите `run.bat`. Проверка: `Invoke-RestMethod -Method Get -Headers @{'X-HomeBot-Key'='<ключ>'} http://127.0.0.1:8765/health`.
   В ответе должно быть `"ok": True` и `"send_enabled": False`.

## Как агент шлёт события

Ключ берётся из `.env`, в примерах ниже подставьте своё значение.

```powershell
$h = @{ 'X-HomeBot-Key' = '<ключ>'; 'Content-Type' = 'application/json' }

# Уведомление: kind = started | done | waiting | info
Invoke-RestMethod -Method Post -Headers $h -Uri 'http://127.0.0.1:8765/notify' `
  -Body '{"kind":"done","text":"Сборка завершена","task_id":"build-1"}'

# Запрос подтверждения с вариантами ответа (от 2 до 8)
Invoke-RestMethod -Method Post -Headers $h -Uri 'http://127.0.0.1:8765/ask' `
  -Body '{"id":"ask-1","text":"Продолжить?","options":["Да","Нет"]}'

# Получение ответов агента
Invoke-RestMethod -Method Get -Headers $h -Uri 'http://127.0.0.1:8765/answers?since=0'

# Состояние
Invoke-RestMethod -Method Get -Headers $h -Uri 'http://127.0.0.1:8765/status'
```

`since` — номер последнего полученного ответа (`seq`). Ответы приходят с полями `id`, `option`,
`seq`, `ts`. Если пользователь не ответил за `ASK_TTL_MINUTES`, приходит `option: "__timeout__"`.
В `dry-run` сразу приходит `option: "__undelivered__"`.

## Режим отправки

Пока `SEND_ENABLED=0`, все сообщения пишутся только в `state/outbox-dryrun.jsonl` и локальный лог.
Включение реальной отправки — **только по прямому указанию пользователя**: выставьте
`SEND_ENABLED=1`, перезапустите `run.bat`, проверьте `getMe` и отправьте одно тестовое сообщение.
Откат — снова `SEND_ENABLED=0` и перезапуск.

## Команды бота в Telegram

`/start`, `/help`, `/status`, `/ping`. Команда `/info` со списком команд и их описанием будет
добавлена позже, вместе с просмотром устройств домашнего роутера.

Команды принимаются только из чата с `TELEGRAM_CHAT_ID`.

## Файлы состояния

`state/answers.jsonl`, `state/pending.json`, `state/telegram_offset.json`,
`state/outbox.jsonl`, `state/outbox-dryrun.jsonl`. Все записи переживают перезапуск, запись
атомарная. Удалять эти файлы при работающем процессе нельзя.

## Тесты

```
cd E:\Projects\HomeBot
python -m unittest discover -s .
```

Ни один тест не обращается к сети: используется подменный транспорт Telegram.
