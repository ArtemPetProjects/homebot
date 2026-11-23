# PURPOSE: запуск HomeBot без консоли: иконка в трее и фоновый сервер.
import threading
from typing import Protocol, runtime_checkable


@runtime_checkable
class TrayApi(Protocol):
    def add_icon(self, tooltip: str) -> None: ...

    def remove_icon(self) -> None: ...

    def show_message(self, text: str, caption: str) -> None: ...

    def run_message_loop(self) -> None: ...


class FakeTrayApi:
    def __init__(self):
        self.icons: list[str] = []
        self.removed: list[bool] = []
        self.messages: list[tuple[str, str]] = []

    def add_icon(self, tooltip: str) -> None:
        self.icons.append(tooltip)

    def remove_icon(self) -> None:
        self.removed.append(True)

    def show_message(self, text: str, caption: str) -> None:
        self.messages.append((text, caption))

    def run_message_loop(self) -> None:
        return


class TrayController:
    def __init__(self, runtime, api: TrayApi):
        self.runtime = runtime
        self.api = api

    def start(self) -> None:
        self.api.add_icon("HomeBot")

    def status_text(self) -> str:
        status = self.runtime.service.status()
        mode = "вкл" if status.get("send_enabled") else "выкл"
        return f"Отправка: {mode}\nОжидают: {status.get('pending', 0)}"

    def show_status(self) -> None:
        self.api.show_message(self.status_text(), "HomeBot")

    def exit(self) -> None:
        self.runtime.stop_event.set()
        # shutdown() блокируется до выхода serve_forever — вызываем в отдельном потоке.
        threading.Thread(target=self.runtime.server.shutdown, daemon=True).start()
        self.api.remove_icon()
