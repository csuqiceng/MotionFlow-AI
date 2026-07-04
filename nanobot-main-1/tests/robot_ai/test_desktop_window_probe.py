from pathlib import Path

import robot_desktop
from robot_ai.bridge import RobotApi


ROOT = Path(__file__).resolve().parents[2]


class FakeWindow:
    def __init__(self) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class FakeEvent:
    def __init__(self) -> None:
        self.callbacks = []

    def __iadd__(self, callback):
        self.callbacks.append(callback)
        return self


class FakeWebview:
    def __init__(self) -> None:
        self.window = FakeWindow()
        self.created: dict | None = None
        self.started = False
        self.start_callback = None

    def create_window(self, title, *, html, js_api, width, height):
        self.created = {
            "title": title,
            "html": html,
            "js_api": js_api,
            "width": width,
            "height": height,
        }
        return self.window

    def start(self, callback=None):
        self.started = True
        self.start_callback = callback
        if callback:
            callback()


class FakeReadyWindow(FakeWindow):
    def __init__(self) -> None:
        super().__init__()
        self.events = type("Events", (), {"_pywebviewready": FakeEvent()})()


class FakeReadyWebview(FakeWebview):
    def __init__(self) -> None:
        super().__init__()
        self.window = FakeReadyWindow()


def test_launch_desktop_window_creates_pywebview_window() -> None:
    fake = FakeWebview()

    window = robot_desktop.launch_desktop_window(webview_module=fake, start=False)

    assert window is fake.window
    assert fake.created["title"] == "Robot AI"
    assert fake.created["html"] == robot_desktop.HTML
    assert isinstance(fake.created["js_api"], RobotApi)
    assert fake.created["width"] == 980
    assert fake.created["height"] == 720
    assert fake.started is False


def test_launch_desktop_window_can_start_and_auto_close_probe() -> None:
    fake = FakeWebview()

    window = robot_desktop.launch_desktop_window(
        webview_module=fake,
        start=True,
        auto_close=True,
    )

    assert window is fake.window
    assert fake.started is True
    assert fake.window.destroyed is False


def test_launch_desktop_window_delays_auto_close_when_timer_is_injected() -> None:
    fake = FakeWebview()
    timers = []

    class FakeTimer:
        def __init__(self, delay_sec, callback) -> None:
            self.delay_sec = delay_sec
            self.callback = callback
            self.started = False

        def start(self) -> None:
            self.started = True

    def timer_factory(delay_sec, callback):
        timer = FakeTimer(delay_sec, callback)
        timers.append(timer)
        return timer

    window = robot_desktop.launch_desktop_window(
        webview_module=fake,
        start=True,
        auto_close=True,
        auto_close_delay_sec=1.5,
        timer_factory=timer_factory,
    )

    assert window is fake.window
    assert fake.started is True
    assert fake.window.destroyed is False
    assert timers[0].delay_sec == 1.5
    assert timers[0].started is True

    timers[0].callback()

    assert fake.window.destroyed is True


def test_launch_desktop_window_waits_for_pywebviewready_before_probe_close() -> None:
    fake = FakeReadyWebview()
    timers = []

    class FakeTimer:
        def __init__(self, delay_sec, callback) -> None:
            self.delay_sec = delay_sec
            self.callback = callback

        def start(self) -> None:
            timers.append(self)

    window = robot_desktop.launch_desktop_window(
        webview_module=fake,
        start=True,
        auto_close=True,
        auto_close_delay_sec=2.0,
        timer_factory=FakeTimer,
    )

    assert window is fake.window
    assert fake.start_callback is None
    assert len(fake.window.events._pywebviewready.callbacks) == 1
    assert timers == []

    fake.window.events._pywebviewready.callbacks[0]()

    assert timers[0].delay_sec == 2.0
    timers[0].callback()
    assert fake.window.destroyed is True


def test_desktop_window_probe_script_exists() -> None:
    script = ROOT / "tools" / "probe_robot_desktop_window.py"

    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "launch_desktop_window" in text
    assert "--auto-close" in text
