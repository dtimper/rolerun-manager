from __future__ import annotations

import threading
import time

from app.realtime.bridge import CitraBridge, EmulatorBridge, EmulatorBridgeInfo
from app.realtime.xy_adapter import XYMultiRealTimeAdapter, XYRealTimeAdapter
from app.ui import RoleRunManager


class _Context:
    def __init__(self, calls):
        self.calls = calls

    def __enter__(self):
        self.calls.append("enter")
        return self

    def __exit__(self, *_args):
        self.calls.append("exit")


def test_citra_bridge_prepare_opens_gdb_context_so_client_can_send_continue():
    calls = []
    bridge = CitraBridge(lambda: _Context(calls))
    bridge.prepare_connection()
    assert calls == ["enter", "exit"]


class _Bridge(EmulatorBridge):
    def __init__(self, key: str, *, fail: bool = False):
        self.info = EmulatorBridgeInfo(key, key.title(), "test")
        self.fail = fail
        self.prepared = 0

    def open(self):
        return _Context([])

    def prepare_connection(self) -> None:
        self.prepared += 1
        if self.fail:
            raise RuntimeError("not running")


def test_xy_multi_prepares_citra_without_selecting_or_losing_azahar_route():
    azahar = _Bridge("azahar")
    citra = _Bridge("citra")
    multi = XYMultiRealTimeAdapter((
        XYRealTimeAdapter(object(), object(), bridge=azahar, adapter_key="xy-azahar"),
        XYRealTimeAdapter(object(), object(), bridge=citra, adapter_key="xy-citra"),
    ))
    multi.prepare_connection()
    assert azahar.prepared == 1
    assert citra.prepared == 1
    assert multi.active_adapter is None


def test_ui_bootstrap_does_not_require_a_snapshot_or_live_state():
    done = threading.Event()

    class _Core:
        def prepare_connection(self):
            done.set()

    manager = RoleRunManager.__new__(RoleRunManager)
    manager._oras_live_active = False
    manager._xy_transport_prepare_in_progress = False
    manager.realtime_core = _Core()
    manager._active_azahar_realtime_key = lambda: "xy"
    manager.after = lambda _delay, callback: callback()

    manager._kick_xy_transport_prepare()
    assert done.wait(1.0)
    deadline = time.time() + 1.0
    while manager._xy_transport_prepare_in_progress and time.time() < deadline:
        time.sleep(0.01)
    assert manager._xy_transport_prepare_in_progress is False
