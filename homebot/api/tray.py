# PURPOSE: запуск HomeBot без консоли: иконка в трее и фоновый сервер.
import ctypes
import logging
import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

from homebot.config import Config, load_config

from .main import build_runtime

logger = logging.getLogger("homebot.tray")


@runtime_checkable
class TrayApi(Protocol):
    def add_icon(self, tooltip: str) -> None: ...

    def remove_icon(self) -> None: ...

    def show_message(self, text: str, caption: str) -> None: ...

    def show_menu(self) -> None: ...

    def run_message_loop(self) -> None: ...


class FakeTrayApi:
    def __init__(self):
        self.icons: list[str] = []
        self.removed: list[bool] = []
        self.messages: list[tuple[str, str]] = []
        self.menus: list[bool] = []

    def add_icon(self, tooltip: str) -> None:
        self.icons.append(tooltip)

    def remove_icon(self) -> None:
        self.removed.append(True)

    def show_message(self, text: str, caption: str) -> None:
        self.messages.append((text, caption))

    def show_menu(self) -> None:
        self.menus.append(True)

    def run_message_loop(self) -> None:
        return


class TrayController:
    def __init__(self, runtime, api: TrayApi):
        self.runtime = runtime
        self.api = api
        self._exited = False

    def start(self) -> None:
        self.api.add_icon("HomeBot")

    def status_text(self) -> str:
        status = self.runtime.service.status()
        mode = "вкл" if status.get("send_enabled") else "выкл"
        return f"Отправка: {mode}\nОжидают: {status.get('pending', 0)}"

    def show_status(self) -> None:
        self.api.show_message(self.status_text(), "HomeBot")

    def handle_icon_message(self, message: int, lparam: int) -> None:
        # Windows присылает мышиные события в параметре lparam канала иконки.
        if message != WM_STATUS:
            return
        if lparam in (0x0205, 0x0204):  # WM_RBUTTONUP / WM_RBUTTONDBLCLK
            self.api.show_menu()
        elif lparam in (0x0201, 0x0203):  # WM_LBUTTONUP / WM_LBUTTONDBLCLK
            self.show_status()

    def exit(self) -> None:
        if self._exited:
            return
        self._exited = True
        self.runtime.stop_event.set()
        # shutdown() блокируется до выхода serve_forever — вызываем в отдельном потоке.
        threading.Thread(target=self.runtime.server.shutdown, daemon=True).start()
        self.api.remove_icon()


# --- Win32-реализация трея (только Windows, стандартная библиотека) ---
NIM_ADD = 0
NIM_DELETE = 2
NIF_MESSAGE = 1
NIF_ICON = 2
NIF_TIP = 4
WM_APP = 0x8000
WM_STATUS = WM_APP + 1
WM_EXIT = WM_APP + 2
IDI_APPLICATION = 32512

_controller: TrayController | None = None


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _Msg(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_ulong),
        ("pt", _Point),
    ]


class _NotifyIconData(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("hwnd", ctypes.c_void_p),
        ("uID", ctypes.c_uint32),
        ("uFlags", ctypes.c_uint32),
        ("uCallbackMessage", ctypes.c_uint32),
        ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * 128),
    ]


_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t
)


def _wndproc(hwnd, message, wparam, lparam):
    global _controller
    user32 = ctypes.windll.user32
    if message == WM_STATUS and _controller is not None:
        _controller.handle_icon_message(message, lparam)
        return 0
    if message == WM_EXIT and _controller is not None:
        _controller.exit()
        return 0
    if message == 0x0111:  # WM_COMMAND
        command = wparam & 0xFFFF
        if command == 1 and _controller is not None:
            _controller.show_status()
        elif command == 2 and _controller is not None:
            _controller.exit()
        return 0
    return user32.DefWindowProcW(hwnd, message, wparam, lparam)


class Win32TrayApi:
    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.shell32 = ctypes.windll.shell32
        self.hwnd = None
        self.icon = None
        self._wndproc_ref = _WNDPROC(_wndproc)
        # Дескрипторы на 64 бит нельзя возвращать как c_int — иначе обрезка.
        for name in ("CreateWindowExW", "LoadIconW", "CreatePopupMenu"):
            getattr(self.user32, name).restype = ctypes.c_void_p
        self.user32.DefWindowProcW.restype = ctypes.c_ssize_t
        self.user32.DefWindowProcW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        self.user32.RegisterClassW.restype = ctypes.c_uint16
        self.user32.RegisterClassW.argtypes = [ctypes.c_void_p]
        self.user32.CreateWindowExW.argtypes = [
            ctypes.c_uint32,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]

    def add_icon(self, tooltip: str) -> None:
        user32 = self.user32
        class_name = "HomeBotTrayWindow"
        wnd_class = type(
            "WNDCLASSW",
            (ctypes.Structure,),
            {
                "_fields_": [
                    ("style", ctypes.c_uint32),
                    ("lpfnWndProc", _WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", ctypes.c_void_p),
                    ("hIcon", ctypes.c_void_p),
                    ("hCursor", ctypes.c_void_p),
                    ("hbrBackground", ctypes.c_void_p),
                    ("lpszMenuName", ctypes.c_wchar_p),
                    ("lpszClassName", ctypes.c_wchar_p),
                ]
            },
        )()
        wnd_class.style = 0
        wnd_class.lpfnWndProc = self._wndproc_ref
        wnd_class.lpszClassName = class_name
        user32.RegisterClassW(ctypes.byref(wnd_class))
        hwnd_message = ctypes.c_void_p((-3) & 0xFFFFFFFFFFFFFFFF)
        self.hwnd = user32.CreateWindowExW(
            0, class_name, "HomeBot", 0, 0, 0, 0, 0, hwnd_message, None, None, None
        )
        if not self.hwnd:
            raise OSError("Не удалось создать скрытое окно для трея")
        self.icon = user32.LoadIconW(None, IDI_APPLICATION)
        data = _NotifyIconData()
        data.cbSize = ctypes.sizeof(_NotifyIconData)
        data.hwnd = self.hwnd
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_STATUS
        data.hIcon = self.icon
        data.szTip = tooltip
        self.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data))

    def remove_icon(self) -> None:
        if self.hwnd is None:
            return
        data = _NotifyIconData()
        data.cbSize = ctypes.sizeof(_NotifyIconData)
        data.hwnd = self.hwnd
        data.uID = 1
        self.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
        self.hwnd = None
        self.user32.PostQuitMessage(0)

    def show_menu(self) -> None:
        point = _Point()
        self.user32.GetCursorPos(ctypes.byref(point))
        menu = self.user32.CreatePopupMenu()
        self.user32.AppendMenuW(menu, 0, 1, "Статус")
        self.user32.AppendMenuW(menu, 0, 2, "Выход")
        self.user32.TrackPopupMenu(menu, 0, point.x, point.y, 0, self.hwnd, None)

    def show_message(self, text: str, caption: str) -> None:
        self.user32.MessageBoxW(None, text, caption, 0x40)

    def run_message_loop(self) -> None:
        message = _Msg()
        while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))


def run_tray(config: Config | None = None, api: TrayApi | None = None) -> int:
    global _controller
    if api is None:
        api = Win32TrayApi()
    if config is None:
        config = load_config(Path(__file__).resolve().parent.parent / ".env")
    try:
        # build_runtime называем через globals(), чтобы тесты могли подменить функцию.
        runtime = globals()["build_runtime"](config)
    except Exception as exc:
        logger.warning("Не удалось запустить бота: %s", type(exc).__name__)
        api.show_message(f"Не удалось запустить HomeBot: {exc}", "HomeBot")
        return 1
    server_thread = threading.Thread(
        target=runtime.server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True
    )
    server_thread.start()
    poller_thread = threading.Thread(target=runtime.poller.run, daemon=True)
    poller_thread.start()
    controller = TrayController(runtime, api)
    _controller = controller
    controller.start()
    try:
        api.run_message_loop()
    except KeyboardInterrupt:
        controller.exit()
    finally:
        controller.exit()
        poller_thread.join(timeout=5)
        server_thread.join(timeout=5)
        runtime.server.server_close()
        _controller = None
    return 0


if __name__ == "__main__":
    raise SystemExit(run_tray())
