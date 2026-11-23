# Proactive Decisions And Devices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give HomeBot proactive handoff notifications, persistent chat buttons, and a read-only home-network device list with locally stored labels.

**Architecture:** The existing loopback bridge gains `/handoff` and `/devices`. A new `network.py` reads the ARP table through an injectable provider; `devices.py` stores MAC/IP labels in `state/devices.json`. Telegram replies carry a persistent reply keyboard; `PendingAsk.source` separates agent questions from device questions.

**Tech Stack:** Python 3.13 stdlib, Telegram Bot API reply keyboards, `unittest` with fake ARP/transport.

**Spec:** `E:\Projects\HomeBot\docs\superpowers\specs\2026-11-24-proactive-and-devices-design.md`

## Global Constraints

- Windows, Python 3.13.17, standard library only, no pip installs.
- Bridge stays on `127.0.0.1`; key required; no LAN changes, no router admin.
- Scan only `NETWORK_SUBNET`, at most 254 addresses, no real network in tests.
- MAC is the primary device key; IP is fallback.
- User labels override config labels; config never overwrites them.
- Before asking the user, send `/notify` with a summary; before re-asking, read `/answers`.
- Comments in code — Russian.

## Review Focus

1. Ответ уже дан: перед новым вопросом читать `/answers`, не дублировать вопрос. Тест в Task 2 на идемпотентность `/handoff`.
2. Подпись устройства переживает перезапуск и смену IP: MAC — ключ. Тест `test_label_follows_mac_after_ip_change` в Task 1.
3. Выдуманное имя не выдаётся за факт: неизвестные помечаются `known=False`. Тест `test_unknown_devices_marked` в Task 1.
4. Постоянные кнопки есть у всех ответов бота, а не только у `/start`. Тест `test_keyboard_attached_to_replies` в Task 2.
5. Вопрос агента и вопрос про устройства не смешиваются: `source` в `PendingAsk`, `/nextdown` берёт только `agent`. Тест `test_nextdown_ignores_device_asks` в Task 2.

---

### Task 1: Сканер и реестр устройств

**Files:**
- Create: `homebot/network.py`, `homebot/devices.py`, `tests/test_network.py`, `tests/test_devices.py`
- Modify: `homebot/config.py`, `.env.example`

**Interfaces:**
- Consumes: `Config`, `Store` paths.
- Produces: `Device(ip, mac, hostname, alive, known, label, source)`; `scan_network(subnet, arp_provider, resolver, timeout) -> list[Device]`; `DeviceRegistry(state_dir)` with `known(ip_or_mac)`, `remember(ip, mac, label, source)`, `unknowns(devices)`, `all_devices()`; `Config.ask_ttl_minutes` already exists, new `network_subnet: str`.

- [ ] **Step 1: Write failing tests**

`tests/test_network.py`: `test_parses_arp_output` (three lines with MAC/IP, one invalid) and `test_unreachable_hosts_excluded`. `tests/test_devices.py`: `test_remember_and_reload`, `test_label_follows_mac_after_ip_change`, `test_unknown_devices_marked`, `test_user_label_overrides_config`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s .` — expected FAIL, modules missing.

- [ ] **Step 3: Implement `network.py` and `devices.py`**

`scan_network` uses injectable `arp_provider()` returning text; parse Windows `arp -a`, resolve hostnames with injectable `resolver(ip)`, mark `known=False` by default. `DeviceRegistry` writes atomic JSON keyed by MAC with `ip`, `label`, `source`, `updated_at`; `remember` merges by MAC; config defaults loaded at construction only when key absent.

- [ ] **Step 4: Add `NETWORK_SUBNET` config**

`load_config` reads `NETWORK_SUBNET` with default `192.168.1.0/24`; add key to `.env.example`. Run tests; expect PASS. Commit `feat: add network scanner and device registry`.

### Task 2: Переходы, кнопки и команды

**Files:**
- Modify: `homebot/service.py`, `homebot/bridge.py`, `homebot/telegram.py`, `homebot/models.py`
- Test: `tests/test_service.py`, `tests/test_bridge.py`

**Interfaces:**
- Consumes: Task 1 `DeviceRegistry`, `scan_network`, `Config`; existing `HomeBotService`.
- Produces: `HomeBotService.handoff(body) -> {"ok": True, "ask_id": str}`; `build_main_keyboard() -> dict`; commands `/devices`, `/info`, `/nextdown`, `/label <ip> <имя>`; `PendingAsk.source`.

- [ ] **Step 1: Write the failing tests**

`tests/test_service.py`: `test_handoff_sends_notify_and_ask`, `test_handoff_idempotent`, `test_keyboard_attached_to_replies`, `test_nextdown_ignores_device_asks`, `test_label_command_updates_registry`. `tests/test_bridge.py`: `test_handoff_endpoint`.

- [ ] **Step 2: Run tests to verify they fail**

Expected FAIL — methods/route missing.

- [ ] **Step 3: Implement service changes**

`handoff` validates `summary/question/options/task_id`, returns existing `ask_id` when that id is active; calls `notify` and `ask(source="agent")`. `handle_command` adds four commands, attaches `build_main_keyboard()` to every reply, and `/devices` uses `scan_network` with 30-second cache in the service. `/nextdown` finds the newest active ask with `source="agent"` and resends its buttons.

- [ ] **Step 4: Implement bridge route and Telegram keyboard**

`POST /handoff` calls `service.handoff(body)`, returns 200. `build_main_keyboard` builds `ReplyKeyboardMarkup` with one row of four buttons and `resize_keyboard=True`. `setMyCommands` is best-effort at startup when sending enabled.

- [ ] **Step 5: Run tests and commit**

Expected all PASS. Commit `feat: add handoff, device commands and chat keyboard`.

### Task 3: Документация и живая проверка

**Files:**
- Modify: `README.md`, `E:\OpenCodeModel\CONTEXT.md`

- [ ] **Step 1: Run full suite** — expected PASS.
- [ ] **Step 2: Update README** — button usage, `/devices`, `/label`, `/handoff` contract, no typing needed.
- [ ] **Step 3: Live test** — press each button in desktop Telegram, run `/devices`, label one unknown device, restart tray and verify the label survived. Report results to `CONTEXT.md`.
- [ ] **Step 4: Commit** `docs: describe bot modes and device labels`.
