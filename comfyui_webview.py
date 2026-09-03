#!/usr/bin/env python3
import argparse
import ctypes
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
import webview

class ComfyUIApp:

    def __init__(self, debug=False):
        self.debug = debug
        self.comfyui_url = "http://127.0.0.1:8188"
        self.host = "127.0.0.1"
        self.port = 8188
        self.window = None
        self.running = True
        self.connection_was_lost = False
        self.reloading = False
        self.restore_attempted = False
        self.last_saved_state = None
        self.last_snapshot_state = None
        self.close_confirmed = False
        self.comfyui_available = False
        self.max_retries = 10
        self.retry_delay = 1
        self.monitor_interval = 3
        self.state_check_interval = 3
        self.fullscreen = False
        self.window_hwnd = None
        self.zoom_level = 1.0
        self.zoom_step = 0.1
        self.zoom_min = 0.5
        self.zoom_max = 2.0
        self.base_path = Path(__file__).resolve().parent
        self.storage_path = (
            self.base_path / ".comfyui_webview"
        )
        self.snapshot_path = (
            self.storage_path / "session_snapshots"
        )
        self.storage_path.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.snapshot_path.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.log(
            f"Base directory: {self.base_path}"
        )
        self.log(
            f"Persistent storage: {self.storage_path}"
        )
    # ---------------------------------------------------------------
    # Logging
    # ---------------------------------------------------------------
    def log(self, message):
        if self.debug:
            print(
                f"[DEBUG] {message}",
                flush=True,
            )

    def info(self, message):
        print(
            message,
            flush=True,
        )

    def warning(self, message):
        print(
            f"Warning: {message}",
            flush=True,
        )
    # ---------------------------------------------------------------
    # ComfyUI connection
    # ---------------------------------------------------------------
    def check_connection(self, timeout=1.5):
        try:
            with socket.create_connection(
                (self.host, self.port),
                timeout=timeout,
            ):
                return True
        except OSError:
            return False

    def wait_for_comfyui(self):
        for attempt in range(
            self.max_retries
        ):
            if self.check_connection():
                self.comfyui_available = True
                self.log(
                    "ComfyUI available after "
                    f"{attempt + 1} check(s)."
                )
                return True
            self.log(
                "ComfyUI unavailable, retry "
                f"{attempt + 1}/{self.max_retries}."
            )
            time.sleep(
                self.retry_delay
            )
        self.comfyui_available = False
        self.warning(
            "ComfyUI is not available. "
            "Waiting page will retry automatically."
        )
        return False

    def get_queue_status(self):
        try:
            request = urllib.request.Request(
                f"{self.comfyui_url}/queue",
                headers={
                    "Cache-Control": "no-cache"
                },
            )
            with urllib.request.urlopen(
                request,
                timeout=2,
            ) as response:
                data = json.loads(
                    response.read().decode(
                        "utf-8"
                    )
                )
            running = len(
                data.get(
                    "queue_running",
                    [],
                )
            )
            pending = len(
                data.get(
                    "queue_pending",
                    [],
                )
            )
            return {
                "running": running,
                "pending": pending,
                "active": running > 0,
            }
        except (
            OSError,
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
        ):
            return {
                "running": 0,
                "pending": 0,
                "active": False,
            }
    # ---------------------------------------------------------------
    # Offline page
    # ---------------------------------------------------------------
    def get_error_page(self):
        return """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>ComfyUI - Offline</title>
<style>
body {
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Roboto,
        sans-serif;
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100vh;
    margin: 0;
    background: #f5f5f5;
}
.container {
    text-align: center;
    padding: 40px;
    background: white;
    border-radius: 8px;
    box-shadow:
        0 2px 10px rgba(0, 0, 0, .1);
    max-width: 500px;
}
h1 {
    color: #333;
}
p {
    color: #666;
    line-height: 1.6;
}
.error {
    color: #d32f2f;
    background: #ffebee;
    padding: 12px;
    border-radius: 4px;
    margin: 20px 0;
    font-family: monospace;
}
</style>
</head>
<body>
<div class="container">
<h1>ComfyUI is offline</h1>
<p>
Waiting for ComfyUI to become available.
</p>
<div class="error">
http://127.0.0.1:8188
</div>
<p id="status">
Checking automatically...
</p>
</div>
<script>
let checking = false;
async function checkComfyUI() {
    if (checking) {
        return;
    }
    checking = true;
    try {
        await fetch(
            "http://127.0.0.1:8188/",
            {
                cache: "no-store"
            }
        );
        document.getElementById(
            "status"
        ).textContent =
            "ComfyUI is ready. Loading...";
        location.href =
            "http://127.0.0.1:8188/";
    } catch (e) {
        document.getElementById(
            "status"
        ).textContent =
            "Still waiting...";
        checking = false;
    }
}
setInterval(
    checkComfyUI,
    3000
);
checkComfyUI();
</script>
</body>
</html>
"""
    # ---------------------------------------------------------------
    # Native window
    # ---------------------------------------------------------------
    def get_window_handle(self):
        if self.window is None:
            return None
        if self.window_hwnd:
            return self.window_hwnd
        try:
            native = self.window.native
            handle = native.Handle
            if hasattr(
                handle,
                "ToInt64",
            ):
                return handle.ToInt64()
            if isinstance(
                handle,
                int,
            ):
                return handle
        except Exception:
            pass
        try:
            native = self.window.native
            handle = native.handle
            if isinstance(
                handle,
                int,
            ):
                return handle
        except Exception:
            pass
        return None

    def on_before_show(self):
        if self.window is None:
            return
        try:
            hwnd = self.get_window_handle()
            if hwnd:
                self.window_hwnd = hwnd
                self.log(
                    f"Captured native HWND: {hwnd}"
                )
                self.remove_window_rounding()
        except Exception as e:
            self.log(
                "Could not capture native HWND: "
                f"{e}"
            )

    def remove_window_rounding(self):
        hwnd = self.get_window_handle()
        if not hwnd:
            self.log(
                "No HWND available for DWM settings."
            )
            return
        try:
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_DONOTROUND = 1
            value = ctypes.c_int(
                DWMWCP_DONOTROUND
            )
            result = (
                ctypes.windll.dwmapi
                .DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd),
                    DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )
            )
            self.log(
                "DWM corner setting applied. "
                f"result={result}"
            )
        except Exception as e:
            self.log(
                "Could not disable rounded corners: "
                f"{e}"
            )
    # ---------------------------------------------------------------
    # Fullscreen
    # ---------------------------------------------------------------
    def toggle_fullscreen(self):
        if (
            self.window is None
            or not self.running
        ):
            return False
        self.log(
            "F11 fullscreen requested."
        )
        try:
            self.window.toggle_fullscreen()
            self.fullscreen = (
                not self.fullscreen
            )
            self.log(
                "Fullscreen state changed to "
                f"{self.fullscreen}."
            )

            def reapply_dwm():
                time.sleep(0.20)
                if self.running:
                    self.remove_window_rounding()
            threading.Thread(
                target=reapply_dwm,
                daemon=True,
            ).start()
            return True
        except Exception as e:
            self.warning(
                "Could not toggle fullscreen: "
                f"{e}"
            )
            return False
    # ---------------------------------------------------------------
    # Native WebView2 zoom
    # ---------------------------------------------------------------
    def get_webview_control(self):
        if self.window is None:
            return None
        try:
            native = self.window.native
            control = getattr(
                native,
                "webview",
                None,
            )
            if control is not None:
                return control
        except Exception as e:
            self.log(
                "Could not get native WebView2 control: "
                f"{e}"
            )
        return None

    def set_native_zoom(self, level):
        if (
            self.window is None
            or not self.running
        ):
            return False
        level = max(
            self.zoom_min,
            min(
                self.zoom_max,
                float(level),
            ),
        )
        self.zoom_level = level
        try:
            native = self.window.native
            control = self.get_webview_control()
            if control is None:
                self.log(
                    "Native WebView2 control not available."
                )
                return False
            from System import Action

            def apply_zoom():
                try:
                    control.ZoomFactor = float(
                        level
                    )
                    self.log(
                        "WebView2 ZoomFactor set to "
                        f"{level:.2f}."
                    )
                except Exception as e:
                    self.log(
                        "Could not set WebView2 "
                        f"ZoomFactor: {e}"
                    )
            native.BeginInvoke(
                Action(apply_zoom)
            )
            return True
        except Exception as e:
            self.log(
                "Could not marshal WebView2 zoom "
                f"operation: {e}"
            )
            return False

    def zoom_in(self):
        self.log(
            "Native zoom-in requested."
        )
        new_level = min(
            self.zoom_max,
            self.zoom_level + self.zoom_step,
        )
        return self.set_native_zoom(
            new_level
        )

    def zoom_out(self):
        self.log(
            "Native zoom-out requested."
        )
        new_level = max(
            self.zoom_min,
            self.zoom_level - self.zoom_step,
        )
        return self.set_native_zoom(
            new_level
        )

    def zoom_reset(self):
        self.log(
            "Native zoom reset requested."
        )
        return self.set_native_zoom(
            1.0
        )
    # ---------------------------------------------------------------
    # Reload
    # ---------------------------------------------------------------
    def save_before_reload(self):
        if not self.running:
            return False
        self.log(
            "Saving workflow state before reload."
        )
        try:
            saved = (
                self.persist_workflow_tabs(
                    force=True
                )
            )
            if (
                saved
                and self.last_saved_state
            ):
                self.create_session_snapshot(
                    self.last_saved_state,
                    force=True,
                )
            return True
        except Exception as e:
            self.warning(
                "Could not save before reload: "
                f"{e}"
            )
            return False

    def hard_reload(self):
        if (
            self.window is None
            or not self.running
        ):
            return False
        self.log(
            "Hard reload requested."
        )
        try:
            self.save_before_reload()
            self.window.load_url(
                self.comfyui_url
            )
            return True
        except Exception as e:
            self.warning(
                "Could not perform hard reload: "
                f"{e}"
            )
            return False
    # ---------------------------------------------------------------
    # Keyboard handler
    # ---------------------------------------------------------------
    def install_keyboard_handler(self):
        if (
            self.window is None
            or not self.running
        ):
            return
        js = r"""
(() => {
    if (
        window.__ComfyUIWebViewKeyboardHandlerInstalled
    ) {
        return;
    }
    window.__ComfyUIWebViewKeyboardHandlerInstalled =
        true;
    const hotkeyState = {
        zoomIn: false,
        zoomOut: false,
        zoomReset: false,
        snapshot: false,
        loadSnapshot: false,
        hardReload: false,
        refresh: false
    };
    function getApi() {
        return (
            window.pywebview &&
            window.pywebview.api
        )
            ? window.pywebview.api
            : null;
    }
    function releaseHotkeyState() {
        hotkeyState.zoomIn = false;
        hotkeyState.zoomOut = false;
        hotkeyState.zoomReset = false;
        hotkeyState.snapshot = false;
        hotkeyState.loadSnapshot = false;
        hotkeyState.hardReload = false;
        hotkeyState.refresh = false;
    }
    document.addEventListener(
        "keydown",
        function(event) {
            if (event.repeat) {
                return;
            }
            const api = getApi();
            if (
                event.key === "F5"
            ) {
                if (hotkeyState.refresh) {
                    return;
                }
                hotkeyState.refresh = true;
                event.preventDefault();
                event.stopPropagation();
                if (
                    api &&
                    api.save_before_reload
                ) {
                    api.save_before_reload()
                        .finally(() => {
                            window.location.reload();
                        });
                } else {
                    window.location.reload();
                }
                return;
            }
            if (
                event.ctrlKey &&
                !event.shiftKey &&
                !event.altKey &&
                event.key.toLowerCase() === "r"
            ) {
                if (hotkeyState.refresh) {
                    return;
                }
                hotkeyState.refresh = true;
                event.preventDefault();
                event.stopPropagation();
                if (
                    api &&
                    api.save_before_reload
                ) {
                    api.save_before_reload()
                        .finally(() => {
                            window.location.reload();
                        });
                } else {
                    window.location.reload();
                }
                return;
            }
            if (
                event.key === "F11"
            ) {
                event.preventDefault();
                event.stopPropagation();
                if (
                    api &&
                    api.toggle_fullscreen
                ) {
                    api.toggle_fullscreen();
                }
                return;
            }
            if (
                event.ctrlKey &&
                event.shiftKey &&
                !event.altKey &&
                (
                    event.key === "+" ||
                    event.key === "=" ||
                    event.code === "NumpadAdd"
                )
            ) {
                if (hotkeyState.zoomIn) {
                    return;
                }
                hotkeyState.zoomIn = true;
                event.preventDefault();
                event.stopPropagation();
                if (
                    api &&
                    api.zoom_in
                ) {
                    api.zoom_in();
                }
                return;
            }
            if (
                event.ctrlKey &&
                event.shiftKey &&
                !event.altKey &&
                (
                    event.key === "-" ||
                    event.key === "_" ||
                    event.code === "NumpadSubtract"
                )
            ) {
                if (hotkeyState.zoomOut) {
                    return;
                }
                hotkeyState.zoomOut = true;
                event.preventDefault();
                event.stopPropagation();
                if (
                    api &&
                    api.zoom_out
                ) {
                    api.zoom_out();
                }
                return;
            }
            if (
                event.ctrlKey &&
                event.shiftKey &&
                !event.altKey &&
                (
                    event.key === "0" ||
                    event.code === "Digit0" ||
                    event.code === "Numpad0"
                )
            ) {
                if (hotkeyState.zoomReset) {
                    return;
                }
                hotkeyState.zoomReset = true;
                event.preventDefault();
                event.stopPropagation();
                if (
                    api &&
                    api.zoom_reset
                ) {
                    api.zoom_reset();
                }
                return;
            }
            if (
                event.ctrlKey &&
                event.shiftKey &&
                !event.altKey &&
                event.key.toLowerCase() === "s"
            ) {
                if (hotkeyState.snapshot) {
                    return;
                }
                hotkeyState.snapshot = true;
                event.preventDefault();
                event.stopPropagation();
                if (
                    api &&
                    api.create_snapshot_now
                ) {
                    api.create_snapshot_now();
                }
                return;
            }
            if (
                event.ctrlKey &&
                event.shiftKey &&
                !event.altKey &&
                event.key.toLowerCase() === "l"
            ) {
                if (hotkeyState.loadSnapshot) {
                    return;
                }
                hotkeyState.loadSnapshot = true;
                event.preventDefault();
                event.stopPropagation();
                if (
                    api &&
                    api.load_snapshot
                ) {
                    api.load_snapshot();
                }
                return;
            }
            if (
                event.ctrlKey &&
                event.shiftKey &&
                !event.altKey &&
                event.key.toLowerCase() === "r"
            ) {
                if (hotkeyState.hardReload) {
                    return;
                }
                hotkeyState.hardReload = true;
                event.preventDefault();
                event.stopPropagation();
                if (
                    api &&
                    api.hard_reload
                ) {
                    api.hard_reload();
                }
                return;
            }
        },
        true
    );
    document.addEventListener(
        "keyup",
        function(event) {
            if (
                event.key === "+" ||
                event.key === "=" ||
                event.code === "NumpadAdd"
            ) {
                hotkeyState.zoomIn = false;
            }
            if (
                event.key === "-" ||
                event.key === "_" ||
                event.code === "NumpadSubtract"
            ) {
                hotkeyState.zoomOut = false;
            }
            if (
                event.key === "0" ||
                event.code === "Digit0" ||
                event.code === "Numpad0"
            ) {
                hotkeyState.zoomReset = false;
            }
            if (
                event.key.toLowerCase() === "s"
            ) {
                hotkeyState.snapshot = false;
            }
            if (
                event.key.toLowerCase() === "l"
            ) {
                hotkeyState.loadSnapshot = false;
            }
            if (
                event.key.toLowerCase() === "r"
            ) {
                hotkeyState.hardReload = false;
                hotkeyState.refresh = false;
            }
            if (
                event.key === "F5"
            ) {
                hotkeyState.refresh = false;
            }
        },
        true
    );
    window.addEventListener(
        "blur",
        releaseHotkeyState
    );
})();
"""
        try:
            self.window.expose(
                self.toggle_fullscreen,
                self.zoom_in,
                self.zoom_out,
                self.zoom_reset,
                self.save_before_reload,
                self.create_snapshot_now,
                self.load_snapshot,
                self.hard_reload,
            )
            self.window.evaluate_js(
                js
            )
            self.log(
                "Keyboard shortcuts installed."
            )
        except Exception as e:
            self.warning(
                "Could not install keyboard handler: "
                f"{e}"
            )
    # ---------------------------------------------------------------
    # Workflow state
    # ---------------------------------------------------------------
    def get_workflow_state(self):
        if (
            self.window is None
            or not self.running
        ):
            return None
        js = r"""
(() => {
    const result = {};
    for (
        let i = 0;
        i < sessionStorage.length;
        i++
    ) {
        const key =
            sessionStorage.key(i);
        if (!key) {
            continue;
        }
        if (
            key.startsWith(
                "Comfy.Workflow.OpenPaths:"
            ) ||
            key.startsWith(
                "Comfy.Workflow.ActivePath:"
            )
        ) {
            result[key] =
                sessionStorage.getItem(
                    key
                );
        }
    }
    return JSON.stringify(
        result
    );
})()
"""
        return self.window.evaluate_js(
            js
        )

    def normalize_state(self, raw):
        if not raw:
            return None
        try:
            data = json.loads(
                raw
            )
            if not data:
                return None
            return json.dumps(
                data,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
            )
        except Exception:
            return None

    def persist_workflow_tabs(
        self,
        force=False,
    ):
        if (
            self.window is None
            or not self.running
        ):
            return False
        try:
            raw = (
                self.get_workflow_state()
            )
            state_string = (
                self.normalize_state(
                    raw
                )
            )
            if not state_string:
                return False
            if (
                not force
                and state_string ==
                    self.last_saved_state
            ):
                return False
            storage_value = json.dumps(
                state_string
            )
            save_js = (
                "localStorage.setItem("
                "'ComfyUIWebView.PersistentWorkflowTabs', "
                + storage_value
                + ");"
            )
            self.window.evaluate_js(
                save_js
            )
            self.last_saved_state = (
                state_string
            )
            self.log(
                "Workflow state persisted."
            )
            return True
        except Exception as e:
            self.warning(
                "Could not save workflow state: "
                f"{e}"
            )
            return False
    # ---------------------------------------------------------------
    # Snapshots
    # ---------------------------------------------------------------
    def create_session_snapshot(
        self,
        state_string=None,
        force=False,
    ):
        if state_string is None:
            if (
                self.window is None
                or not self.running
            ):
                return False
            try:
                state_string = (
                    self.normalize_state(
                        self.get_workflow_state()
                    )
                )
            except Exception as e:
                self.warning(
                    "Could not capture session "
                    f"snapshot: {e}"
                )
                return False
        if not state_string:
            return False
        if (
            not force
            and state_string ==
                self.last_snapshot_state
        ):
            return False
        try:
            data = json.loads(
                state_string
            )
            now = datetime.now()
            timestamp = now.strftime(
                "%Y%m%d-%H%M%S"
            )
            snapshot_file = (
                self.snapshot_path
                / f"session-{timestamp}.json"
            )
            snapshot = {
                "version": 1,
                "timestamp": now.isoformat(
                    timespec="seconds"
                ),
                "workflow_state": data,
            }
            snapshot_file.write_text(
                json.dumps(
                    snapshot,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.last_snapshot_state = (
                state_string
            )
            self.cleanup_old_snapshots()
            self.log(
                "Created snapshot: "
                f"{snapshot_file.name}"
            )
            return True
        except Exception as e:
            self.warning(
                "Could not write session "
                f"snapshot: {e}"
            )
            return False

    def create_snapshot_now(self):
        if not self.running:
            return False
        try:
            state = (
                self.normalize_state(
                    self.get_workflow_state()
                )
            )
            if not state:
                self.warning(
                    "No workflow session state "
                    "is currently available."
                )
                return False
            if self.create_session_snapshot(
                state,
                force=True,
            ):
                self.info(
                    "Session snapshot saved."
                )
                return True
        except Exception as e:
            self.warning(
                "Could not create session "
                f"snapshot: {e}"
            )
        return False

    def cleanup_old_snapshots(
        self,
        keep=10,
    ):
        try:
            snapshots = sorted(
                self.snapshot_path.glob(
                    "session-*.json"
                ),
                key=lambda p:
                    p.stat().st_mtime,
                reverse=True,
            )
            for old_snapshot in snapshots[
                keep:
            ]:
                try:
                    old_snapshot.unlink()
                    self.log(
                        "Removed old snapshot: "
                        f"{old_snapshot.name}"
                    )
                except OSError:
                    pass
        except OSError as e:
            self.warning(
                "Could not clean old snapshots: "
                f"{e}"
            )

    def get_snapshot_files(self):
        return sorted(
            self.snapshot_path.glob(
                "session-*.json"
            ),
            key=lambda p:
                p.stat().st_mtime,
            reverse=True,
        )

    def load_snapshot(self):
        if (
            self.window is None
            or not self.running
        ):
            return False
        try:
            files = (
                self.get_snapshot_files()
            )
            if not files:
                self.info(
                    "No session snapshots available."
                )
                return False
            selected = (
                self.window.create_file_dialog(
                    webview.OPEN_DIALOG,
                    directory=str(
                        self.snapshot_path
                    ),
                    allow_multiple=False,
                    file_types=(
                        "Session snapshots (*.json)",
                        "JSON files (*.json)",
                    ),
                )
            )
            if not selected:
                return False
            snapshot_file = Path(
                selected[0]
            )
            snapshot = json.loads(
                snapshot_file.read_text(
                    encoding="utf-8"
                )
            )
            state = snapshot.get(
                "workflow_state"
            )
            if not isinstance(
                state,
                dict,
            ):
                raise ValueError(
                    "Snapshot does not contain "
                    "valid workflow state."
                )
            state_string = json.dumps(
                state,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
            )
            saved_state = json.dumps(
                state_string
            )
            save_js = (
                "localStorage.setItem("
                "'ComfyUIWebView.PersistentWorkflowTabs', "
                + saved_state
                + ");"
            )
            self.window.evaluate_js(
                save_js
            )
            self.last_saved_state = (
                state_string
            )
            self.last_snapshot_state = (
                state_string
            )
            self.restore_attempted = False
            self.info(
                "Loading session: "
                f"{snapshot_file.name}"
            )
            self.window.load_url(
                self.comfyui_url
            )
            return True
        except Exception as e:
            self.warning(
                "Could not load session snapshot: "
                f"{e}"
            )
            return False

    def restore_workflow_tabs(self):
        if (
            self.window is None
            or not self.running
            or self.restore_attempted
        ):
            return False
        js = r"""
(() => {
    const savedRaw =
        localStorage.getItem(
            "ComfyUIWebView.PersistentWorkflowTabs"
        );
    if (!savedRaw) {
        return JSON.stringify({
            saved: false,
            restored: 0
        });
    }
    let saved;
    try {
        saved = JSON.parse(
            savedRaw
        );
    } catch (e) {
        return JSON.stringify({
            saved: false,
            restored: 0,
            error: "invalid saved state"
        });
    }
    let clientId = null;
    for (
        let i = 0;
        i < sessionStorage.length;
        i++
    ) {
        const key =
            sessionStorage.key(i);
        if (!key) {
            continue;
        }
        if (
            key.startsWith(
                "Comfy.Workflow.OpenPaths:"
            )
        ) {
            clientId = key.substring(
                "Comfy.Workflow.OpenPaths:"
                    .length
            );
            break;
        }
        if (
            key.startsWith(
                "Comfy.Workflow.ActivePath:"
            )
        ) {
            clientId = key.substring(
                "Comfy.Workflow.ActivePath:"
                    .length
            );
            break;
        }
    }
    if (!clientId) {
        return JSON.stringify({
            saved: true,
            restored: 0,
            reason: "clientId not found"
        });
    }
    let restored = 0;
    for (
        const [key, value]
        of Object.entries(saved)
    ) {
        let targetKey = null;
        if (
            key.startsWith(
                "Comfy.Workflow.OpenPaths:"
            )
        ) {
            targetKey =
                "Comfy.Workflow.OpenPaths:"
                + clientId;
        } else if (
            key.startsWith(
                "Comfy.Workflow.ActivePath:"
            )
        ) {
            targetKey =
                "Comfy.Workflow.ActivePath:"
                + clientId;
        }
        if (!targetKey) {
            continue;
        }
        sessionStorage.setItem(
            targetKey,
            value
        );
        restored++;
    }
    return JSON.stringify({
        saved: true,
        restored: restored
    });
})()
"""
        try:
            result = (
                self.window.evaluate_js(
                    js
                )
            )
            if not result:
                return False
            parsed = json.loads(
                result
            )
            if (
                parsed.get("reason")
                == "clientId not found"
            ):
                self.log(
                    "Waiting for ComfyUI clientId."
                )
                return False
            self.restore_attempted = True
            restored = parsed.get(
                "restored",
                0,
            )
            if restored:
                self.log(
                    f"Restored {restored} "
                    "workflow state value(s)."
                )
                try:
                    saved_raw = (
                        self.window.evaluate_js(
                            "localStorage.getItem("
                            "'ComfyUIWebView.PersistentWorkflowTabs'"
                            ");"
                        )
                    )
                    if saved_raw:
                        self.last_saved_state = (
                            json.dumps(
                                json.loads(
                                    saved_raw
                                ),
                                sort_keys=True,
                                separators=(
                                    ",",
                                    ":",
                                ),
                            )
                        )
                except Exception:
                    pass
            return restored > 0
        except Exception as e:
            self.warning(
                "Could not restore workflow state: "
                f"{e}"
            )
            return False
    # ---------------------------------------------------------------
    # Background state saving
    # ---------------------------------------------------------------
    def state_save_loop(self):
        while self.running:
            time.sleep(
                self.state_check_interval
            )
            if not self.running:
                break
            if self.window is None:
                continue
            try:
                changed = (
                    self.persist_workflow_tabs()
                )
                if (
                    changed
                    and self.last_saved_state
                ):
                    self.create_session_snapshot(
                        self.last_saved_state
                    )
            except Exception as e:
                if self.running:
                    self.warning(
                        f"State save error: {e}"
                    )
    # ---------------------------------------------------------------
    # Window status
    # ---------------------------------------------------------------
    def update_window_status(
        self,
        available,
    ):
        if (
            self.window is None
            or not self.running
        ):
            return
        try:
            self.window.title = (
                "ComfyUI - Running"
                if available
                else "ComfyUI - Offline"
            )
        except Exception:
            pass
    # ---------------------------------------------------------------
    # ComfyUI monitor
    # ---------------------------------------------------------------
    def monitor_comfyui(self):
        while self.running:
            time.sleep(
                self.monitor_interval
            )
            if not self.running:
                break
            available = (
                self.check_connection()
            )
            if not self.running:
                break
            if not available:
                if not self.connection_was_lost:
                    self.warning(
                        "ComfyUI connection lost."
                    )
                self.connection_was_lost = True
                self.comfyui_available = False
                self.update_window_status(
                    False
                )
                continue
            if (
                self.connection_was_lost
                and not self.reloading
                and self.running
            ):
                self.info(
                    "ComfyUI connection restored."
                )
                self.comfyui_available = True
                self.reloading = True
                try:
                    if (
                        self.window
                        and self.running
                    ):
                        self.window.load_url(
                            self.comfyui_url
                        )
                except Exception as e:
                    if self.running:
                        self.warning(
                            "Could not reconnect "
                            f"to ComfyUI: {e}"
                        )
                    self.reloading = False
                else:
                    self.connection_was_lost = False
                    self.update_window_status(
                        True
                    )

                    def clear_reload_flag():
                        time.sleep(2)
                        if self.running:
                            self.reloading = False
                    threading.Thread(
                        target=clear_reload_flag,
                        daemon=True,
                    ).start()
            else:
                self.comfyui_available = True
                self.update_window_status(
                    True
                )
    # ---------------------------------------------------------------
    # Page loaded
    # ---------------------------------------------------------------
    def on_loaded(self):
        if not self.running:
            return
        self.log(
            "WebView page loaded."
        )
        self.install_keyboard_handler()

        def delayed_setup():
            time.sleep(2)
            if not self.running:
                return
            self.restore_workflow_tabs()
        threading.Thread(
            target=delayed_setup,
            daemon=True,
        ).start()
    # ---------------------------------------------------------------
    # Close warning
    # ---------------------------------------------------------------
    def show_close_warning(self):
        try:
            result = (
                ctypes.windll.user32
                .MessageBoxW(
                    0,
                    (
                        "ComfyUI is currently "
                        "processing a job.\n\n"
                        "Closing this WebView will "
                        "not stop ComfyUI itself, "
                        "but this window will close.\n\n"
                        "Are you sure you want to close?"
                    ),
                    "ComfyUI is Processing",
                    0x00000004
                    | 0x00000030,
                )
            )
            return result == 6
        except Exception as e:
            self.warning(
                "Could not display close warning: "
                f"{e}"
            )
            return True

    def on_closing(self):
        if self.close_confirmed:
            self.running = False
            return True
        if not self.comfyui_available:
            self.close_confirmed = True
            self.running = False
            return True
        queue = self.get_queue_status()
        self.log(
            "Close requested: "
            f"running={queue['running']}, "
            f"pending={queue['pending']}."
        )
        if queue["active"]:
            if not self.show_close_warning():
                self.log(
                    "Close cancelled."
                )
                return False
        self.close_confirmed = True
        self.running = False
        return True
    # ---------------------------------------------------------------
    # Run
    # ---------------------------------------------------------------
    def run(self):
        available = (
            self.wait_for_comfyui()
        )
        if available:
            self.window = (
                webview.create_window(
                    title="ComfyUI - Running",
                    url=self.comfyui_url,
                    width=1400,
                    height=900,
                    min_size=(800, 600),
                    resizable=True,
                    zoomable=True,
                )
            )
        else:
            self.window = (
                webview.create_window(
                    title="ComfyUI - Offline",
                    html=self.get_error_page(),
                    width=1400,
                    height=900,
                    min_size=(800, 600),
                    resizable=True,
                    zoomable=True,
                )
            )
        self.window.events.before_show += (
            self.on_before_show
        )
        self.window.events.loaded += (
            self.on_loaded
        )
        self.window.events.closing += (
            self.on_closing
        )
        threading.Thread(
            target=self.monitor_comfyui,
            daemon=True,
        ).start()
        threading.Thread(
            target=self.state_save_loop,
            daemon=True,
        ).start()
        self.log(
            "Starting pywebview."
        )
        webview.start(
            debug=self.debug,
            private_mode=False,
            storage_path=str(
                self.storage_path
            ),
        )

def main():
    parser = argparse.ArgumentParser(
        description="ComfyUI WebView wrapper"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug logging.",
    )
    args = parser.parse_args()
    app = ComfyUIApp(
        debug=args.debug
    )
    app.run()
if __name__ == "__main__":
    main()