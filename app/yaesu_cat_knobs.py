 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/app/yaesu_cat_knobs.py b/app/yaesu_cat_knobs.py
new file mode 100644
index 0000000000000000000000000000000000000000..ba91c12f44306c59359b1e63aca87bb4fcd41993
--- /dev/null
+++ b/app/yaesu_cat_knobs.py
@@ -0,0 +1,475 @@
+#!/usr/bin/env python3
+"""Yaesu CAT multi-knob controller for Raspberry Pi.
+
+支持：
+- 4 个操作旋钮（可在运行中由“配置旋钮”重新映射功能）
+- 1 个配置旋钮（菜单导航/确认）
+- 2.8 寸 LCD：配置菜单 + 运行时信息页（功率/SWR/信号强度）
+- 每个操作旋钮对应 OLED：显示当前功能和当前值
+"""
+
+from __future__ import annotations
+
+import argparse
+import logging
+import re
+import signal
+import sys
+import threading
+import time
+from dataclasses import dataclass
+from pathlib import Path
+from string import Formatter
+from typing import Any, Dict, List, Optional
+
+
+LOGGER = logging.getLogger("yaesu_cat_knobs")
+FT710_CMD_RE = re.compile(r"^[A-Z]{2}")
+
+
+class CatClient:
+    def __init__(self, serial_cfg: Dict[str, Any], terminator: str, min_interval_ms: int) -> None:
+        self._terminator = terminator
+        self._min_interval_s = max(0, min_interval_ms) / 1000.0
+        self._last_sent = 0.0
+        self._lock = threading.Lock()
+
+        import serial
+
+        self._ser = serial.Serial(
+            port=serial_cfg["port"],
+            baudrate=serial_cfg.get("baudrate", 38400),
+            timeout=serial_cfg.get("timeout", 0.2),
+            bytesize=serial_cfg.get("bytesize", 8),
+            parity=serial_cfg.get("parity", "N"),
+            stopbits=serial_cfg.get("stopbits", 1),
+        )
+
+    def send(self, cmd: str) -> None:
+        if not cmd:
+            return
+        message = cmd if cmd.endswith(self._terminator) else f"{cmd}{self._terminator}"
+        payload = message.encode("ascii", errors="ignore")
+
+        with self._lock:
+            now = time.monotonic()
+            elapsed = now - self._last_sent
+            if elapsed < self._min_interval_s:
+                time.sleep(self._min_interval_s - elapsed)
+            self._ser.write(payload)
+            self._ser.flush()
+            self._last_sent = time.monotonic()
+
+        LOGGER.info("CAT >>> %s", message)
+
+    def close(self) -> None:
+        self._ser.close()
+
+
+class LcdDisplay:
+    """LCD抽象层；当前实现为日志输出，便于后续接入真实驱动。"""
+
+    def __init__(self, cfg: Dict[str, Any]) -> None:
+        self.cfg = cfg
+
+    def show_menu(self, selected_knob: str, selected_profile: str, profiles: List[str]) -> None:
+        LOGGER.info(
+            "[LCD] MENU knob=%s profile=%s options=%s",
+            selected_knob,
+            selected_profile,
+            ",".join(profiles),
+        )
+
+    def show_telemetry_page(self, page_name: str, page_value: Any) -> None:
+        LOGGER.info("[LCD] PAGE %s => %s", page_name, page_value)
+
+    def poll_touch_event(self) -> bool:
+        """返回True表示检测到触摸，用于切换显示页。"""
+        return False
+
+
+class OledDisplay:
+    """每个操作旋钮一个 OLED；当前实现为日志输出。"""
+
+    def __init__(self, knob_name: str, cfg: Dict[str, Any]) -> None:
+        self.knob_name = knob_name
+        self.cfg = cfg
+
+    def show_assignment(self, profile_name: str, value_summary: str) -> None:
+        LOGGER.info("[OLED:%s] %s => %s", self.knob_name, profile_name, value_summary)
+
+
+@dataclass
+class KnobRuntime:
+    name: str
+    kind: str
+    encoder: Any
+    button: Optional[Any]
+
+
+class ActionExecutor:
+    def __init__(self, cat: CatClient, state: Dict[str, Any], protocol: str = "generic") -> None:
+        self.cat = cat
+        self.state = state
+        self.protocol = protocol
+        self._lock = threading.Lock()
+
+    def execute_many(self, actions: List[Dict[str, Any]]) -> None:
+        for action in actions:
+            self.execute(action)
+
+    def execute(self, action: Dict[str, Any]) -> None:
+        with self._lock:
+            kind = action.get("type")
+            if kind == "send":
+                self.cat.send(self._encode_command(str(action["command"])))
+            elif kind == "sequence":
+                for cmd in action.get("commands", []):
+                    self.cat.send(self._encode_command(str(cmd)))
+            elif kind == "state_update":
+                key = action["key"]
+                value = action["value"]
+                self.state[key] = value
+                LOGGER.info("state[%s] = %r", key, value)
+            elif kind == "step_cycle":
+                self._step_cycle(action)
+            elif kind == "math_update":
+                self._math_update(action)
+            elif kind == "send_template":
+                command_template = str(action["command"])
+                rendered = render_template(command_template, self.state)
+                self.cat.send(self._encode_command(rendered))
+            else:
+                raise ValueError(f"Unsupported action type: {kind}")
+
+    def _encode_command(self, command: str) -> str:
+        normalized = command[:-1] if command.endswith(";") else command
+        if self.protocol == "ft710":
+            if len(normalized) < 2 or not FT710_CMD_RE.match(normalized):
+                raise ValueError(f"Invalid FT-710 CAT command: {command!r}")
+        return normalized
+
+    def _step_cycle(self, action: Dict[str, Any]) -> None:
+        key = action["key"]
+        values = action["values"]
+        if not values:
+            raise ValueError("step_cycle values cannot be empty")
+        current = self.state.get(key, values[0])
+        try:
+            idx = values.index(current)
+        except ValueError:
+            idx = 0
+        next_value = values[(idx + 1) % len(values)]
+        self.state[key] = next_value
+        LOGGER.info("state[%s] cycled -> %r", key, next_value)
+
+    def _math_update(self, action: Dict[str, Any]) -> None:
+        key = action["key"]
+        op = action.get("op", "add")
+        if "delta_key" in action:
+            delta = int(self.state.get(str(action["delta_key"]), 0))
+        else:
+            delta = int(action.get("delta", 0))
+        current = int(self.state.get(key, 0))
+        value = current + delta if op == "add" else current - delta
+        if "min" in action:
+            value = max(value, int(action["min"]))
+        if "max" in action:
+            value = min(value, int(action["max"]))
+        self.state[key] = value
+        LOGGER.info("state[%s] -> %r", key, value)
+
+
+def render_template(template: str, state: Dict[str, Any]) -> str:
+    formatter = Formatter()
+    for _, field_name, _, _ in formatter.parse(template):
+        if field_name and field_name not in state:
+            raise KeyError(f"Template variable '{field_name}' not found in state")
+    return template.format(**state)
+
+
+def load_config(path: Path) -> Dict[str, Any]:
+    import yaml
+
+    with path.open("r", encoding="utf-8") as f:
+        config = yaml.safe_load(f)
+    if not isinstance(config, dict):
+        raise ValueError("Top-level config must be a mapping")
+    return config
+
+
+class AssignmentManager:
+    def __init__(self, knobs_cfg: List[Dict[str, Any]], oled_cfg: Dict[str, Any], lcd: LcdDisplay) -> None:
+        self.operation_knob_names = [k["name"] for k in knobs_cfg if k.get("kind", "operation") == "operation"]
+        self.config_knob_name = next((k["name"] for k in knobs_cfg if k.get("kind") == "config"), "config")
+
+        self.profiles: Dict[str, Dict[str, Any]] = {
+            p["name"]: p for p in oled_cfg.get("profiles", [])
+        }
+        if not self.profiles:
+            raise ValueError("display.oled.profiles must not be empty")
+
+        default_profile = next(iter(self.profiles.keys()))
+        self.assignments: Dict[str, str] = {
+            name: oled_cfg.get("default_assignments", {}).get(name, default_profile)
+            for name in self.operation_knob_names
+        }
+
+        self._selected_knob_idx = 0
+        self._selected_profile_idx = 0
+        self.menu_active = False
+        self.lcd = lcd
+
+    def enter_menu(self) -> None:
+        self.menu_active = True
+        self._render_menu()
+
+    def leave_menu(self) -> None:
+        self.menu_active = False
+
+    def cycle_knob(self, clockwise: bool) -> None:
+        if not self.operation_knob_names:
+            return
+        step = 1 if clockwise else -1
+        self._selected_knob_idx = (self._selected_knob_idx + step) % len(self.operation_knob_names)
+        self._render_menu()
+
+    def cycle_profile(self, clockwise: bool) -> None:
+        names = list(self.profiles.keys())
+        step = 1 if clockwise else -1
+        self._selected_profile_idx = (self._selected_profile_idx + step) % len(names)
+        self._render_menu()
+
+    def confirm_assignment(self) -> None:
+        knob = self.operation_knob_names[self._selected_knob_idx]
+        profile = list(self.profiles.keys())[self._selected_profile_idx]
+        self.assignments[knob] = profile
+        LOGGER.info("Assigned knob %s => %s", knob, profile)
+        self._render_menu()
+
+    def profile_for(self, knob_name: str) -> Dict[str, Any]:
+        profile_name = self.assignments[knob_name]
+        return self.profiles[profile_name]
+
+    def profile_name_for(self, knob_name: str) -> str:
+        return self.assignments[knob_name]
+
+    def _render_menu(self) -> None:
+        knob = self.operation_knob_names[self._selected_knob_idx]
+        profile = list(self.profiles.keys())[self._selected_profile_idx]
+        self.lcd.show_menu(knob, profile, list(self.profiles.keys()))
+
+
+class Controller:
+    def __init__(self, config: Dict[str, Any]) -> None:
+        runtime_cfg = config.get("runtime", {})
+        self.debounce_ms = int(runtime_cfg.get("debounce_ms", 3))
+        min_interval_ms = int(runtime_cfg.get("min_command_interval_ms", 30))
+        self.menu_idle_timeout_s = int(runtime_cfg.get("menu_idle_timeout_s", 10))
+
+        self.cat = CatClient(
+            serial_cfg=config["serial"],
+            terminator=str(config["cat"].get("terminator", ";")),
+            min_interval_ms=min_interval_ms,
+        )
+        self.executor = ActionExecutor(
+            cat=self.cat,
+            state=dict(config.get("state", {})),
+            protocol=str(config.get("cat", {}).get("protocol", "generic")).lower(),
+        )
+
+        display_cfg = config.get("display", {})
+        self.lcd = LcdDisplay(display_cfg.get("lcd", {}))
+        self.assignment_mgr = AssignmentManager(config["knobs"], display_cfg.get("oled", {}), self.lcd)
+
+        self.oled_map: Dict[str, OledDisplay] = {
+            name: OledDisplay(name, cfg)
+            for name, cfg in display_cfg.get("oled", {}).get("devices", {}).items()
+        }
+        self.telemetry_pages = display_cfg.get("lcd", {}).get(
+            "telemetry_pages", ["tx_power_w", "swr", "s_meter"]
+        )
+
+        self.stop_event = threading.Event()
+        self.knobs: List[KnobRuntime] = []
+        self.last_config_activity = time.monotonic()
+        self.telemetry_page_idx = 0
+
+    def start(self, knobs_cfg: List[Dict[str, Any]]) -> None:
+        for knob_cfg in knobs_cfg:
+            self.knobs.append(self._bind_knob(knob_cfg))
+        self._refresh_oleds()
+
+        signal.signal(signal.SIGINT, self._handle_signal)
+        signal.signal(signal.SIGTERM, self._handle_signal)
+
+        LOGGER.info("Controller started with %d knobs", len(self.knobs))
+        while not self.stop_event.is_set():
+            self._handle_menu_idle_timeout()
+            self._handle_lcd_touch()
+            self._update_lcd_runtime_page()
+            time.sleep(0.2)
+
+    def close(self) -> None:
+        for item in self.knobs:
+            item.encoder.close()
+            if item.button:
+                item.button.close()
+        self.cat.close()
+
+    def _handle_menu_idle_timeout(self) -> None:
+        if not self.assignment_mgr.menu_active:
+            return
+        if time.monotonic() - self.last_config_activity >= self.menu_idle_timeout_s:
+            LOGGER.info("Config knob idle timeout reached; exit menu and return telemetry view")
+            self.assignment_mgr.leave_menu()
+
+    def _handle_lcd_touch(self) -> None:
+        if self.assignment_mgr.menu_active:
+            return
+        if self.lcd.poll_touch_event():
+            self.telemetry_page_idx = (self.telemetry_page_idx + 1) % max(1, len(self.telemetry_pages))
+
+    def _update_lcd_runtime_page(self) -> None:
+        if self.assignment_mgr.menu_active:
+            return
+
+        page_name = self.telemetry_pages[self.telemetry_page_idx % len(self.telemetry_pages)]
+        page_value = self.executor.state.get(page_name, "-")
+        self.lcd.show_telemetry_page(page_name, page_value)
+
+    def _refresh_oleds(self) -> None:
+        for knob_name in self.assignment_mgr.operation_knob_names:
+            profile = self.assignment_mgr.profile_for(knob_name)
+            profile_name = self.assignment_mgr.profile_name_for(knob_name)
+            value_key = profile.get("value_key")
+            value = self.executor.state.get(value_key, "-") if value_key else "-"
+            display = self.oled_map.get(knob_name)
+            if display:
+                display.show_assignment(profile_name, str(value))
+
+    def _handle_signal(self, _signum: int, _frame: Any) -> None:
+        self.stop_event.set()
+
+    def _bind_knob(self, knob_cfg: Dict[str, Any]) -> KnobRuntime:
+        from gpiozero import Button, RotaryEncoder
+
+        name = knob_cfg["name"]
+        kind = knob_cfg.get("kind", "operation")
+        encoder = RotaryEncoder(
+            a=knob_cfg["pins"]["a"],
+            b=knob_cfg["pins"]["b"],
+            max_steps=0,
+            wrap=True,
+            bounce_time=max(0, self.debounce_ms) / 1000.0,
+        )
+
+        def on_cw() -> None:
+            self._on_rotate(name, kind, clockwise=True)
+
+        def on_ccw() -> None:
+            self._on_rotate(name, kind, clockwise=False)
+
+        encoder.when_rotated_clockwise = on_cw
+        encoder.when_rotated_counter_clockwise = on_ccw
+
+        btn_cfg = knob_cfg.get("pins", {}).get("button")
+        button: Optional[Button] = None
+        if btn_cfg is not None:
+            button = Button(btn_cfg, bounce_time=max(0, self.debounce_ms) / 1000.0)
+
+            def on_press() -> None:
+                self._on_press(name, kind)
+
+            button.when_pressed = on_press
+
+        LOGGER.info("Knob %s initialized kind=%s", name, kind)
+        return KnobRuntime(name=name, kind=kind, encoder=encoder, button=button)
+
+    def _on_rotate(self, knob_name: str, kind: str, clockwise: bool) -> None:
+        if kind == "config":
+            if not self.assignment_mgr.menu_active:
+                return
+            self.last_config_activity = time.monotonic()
+            if self.executor.state.get("menu_focus", "knob") == "knob":
+                self.assignment_mgr.cycle_knob(clockwise)
+            else:
+                self.assignment_mgr.cycle_profile(clockwise)
+            return
+
+        profile = self.assignment_mgr.profile_for(knob_name)
+        actions_key = "cw" if clockwise else "ccw"
+        self.executor.execute_many(profile.get("actions", {}).get(actions_key, []))
+        self._refresh_oleds()
+
+    def _on_press(self, knob_name: str, kind: str) -> None:
+        if kind == "config":
+            self.last_config_activity = time.monotonic()
+            if not self.assignment_mgr.menu_active:
+                self.assignment_mgr.enter_menu()
+                self.executor.state["menu_focus"] = "knob"
+                return
+            focus = self.executor.state.get("menu_focus", "knob")
+            if focus == "knob":
+                self.executor.state["menu_focus"] = "profile"
+            elif focus == "profile":
+                self.assignment_mgr.confirm_assignment()
+                self.executor.state["menu_focus"] = "knob"
+                self.assignment_mgr.leave_menu()
+                self._refresh_oleds()
+            return
+
+        profile = self.assignment_mgr.profile_for(knob_name)
+        self.executor.execute_many(profile.get("actions", {}).get("press", []))
+        self._refresh_oleds()
+
+
+def validate_config(config: Dict[str, Any]) -> None:
+    for key in ("serial", "cat", "knobs", "display"):
+        if key not in config:
+            raise ValueError(f"Missing required config key: {key}")
+    knobs = config["knobs"]
+    if not isinstance(knobs, list):
+        raise ValueError("knobs must be list")
+    operation_count = sum(1 for k in knobs if k.get("kind", "operation") == "operation")
+    config_count = sum(1 for k in knobs if k.get("kind") == "config")
+    if operation_count != 4 or config_count != 1:
+        raise ValueError("This build expects exactly 4 operation knobs and 1 config knob")
+
+
+def run(config_path: Path) -> int:
+    config = load_config(config_path)
+    validate_config(config)
+
+    controller = Controller(config)
+    try:
+        controller.start(config["knobs"])
+    finally:
+        controller.close()
+
+    return 0
+
+
+def parse_args(argv: List[str]) -> argparse.Namespace:
+    parser = argparse.ArgumentParser(description="Yaesu CAT multi-knob controller")
+    parser.add_argument("--config", required=True, type=Path, help="Path to YAML config")
+    parser.add_argument("--log-level", default="INFO", help="Python logging level")
+    return parser.parse_args(argv)
+
+
+def main(argv: List[str]) -> int:
+    args = parse_args(argv)
+    logging.basicConfig(
+        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
+        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
+    )
+
+    try:
+        return run(args.config)
+    except Exception as exc:
+        LOGGER.exception("Fatal error: %s", exc)
+        return 1
+
+
+if __name__ == "__main__":
+    sys.exit(main(sys.argv[1:]))
 
EOF
)
