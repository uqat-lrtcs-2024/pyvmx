
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vxm.py — Lightweight Python library for Velmex VXM controllers (RS-232/USB-RS232).

Features
--------
- Robust blocking using either a prompt character '^' or a "silence window" (no incoming bytes)
- High-level helpers: set_speed, set_accel, move_relative, run/stop/kill/clear, position, list_program
- Units helper: scale (steps/mm) + mm_to_steps + move_mm
- Homing: home(direction='neg'|'pos', backoff)
- Busy detection: is_busy() by polling positions
- Runtime config: ready mode ('char' or 'silence'), ready char, quiet window

Dependencies
------------
    pip install pyserial

Example
-------
    from vxm import VXM

    with VXM('COM3') as vxm:
        vxm.set_speed(1, 800)
        vxm.move_relative(1, 2000)
        vxm.run()                 # blocks until finished
        print(vxm.position(1))
"""

from __future__ import annotations
import time
from typing import Optional

try:
    import serial
    from serial.tools import list_ports
except Exception as e:
    raise RuntimeError("pyserial is required. Install with: pip install pyserial") from e


class VXM:
    """
    Minimal, pragmatic wrapper around a Velmex VXM controller.
    Default serial: 9600 8N1, no flow control.
    """
    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        timeout: float = 0.2,
        ready_mode: str = "char",         # or "silence"
        ready_char: str = "^",
        quiet_ms: int = 150,
    ) -> None:
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        # Put controller in On-Line mode (echo off)
        self.send("F", wait=False)
        # Units
        self.steps_per_mm: Optional[float] = None
        # Blocking configuration
        self.ready_mode = ready_mode
        self.ready_char = ready_char
        self.quiet_ms = int(quiet_ms)

    # --------- Context manager ---------
    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass

    def __enter__(self) -> "VXM":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # --------- Internals ---------
    def _read_available(self) -> str:
        data = self.ser.read(self.ser.in_waiting or 1)
        return data.decode(errors="ignore")

    def wait_ready(self, timeout: float = 60.0) -> str:
        """
        Wait until controller indicates 'ready'.
        - char mode: wait until ready_char appears
        - silence mode: wait until no bytes for quiet_ms
        Returns collected text (without trailing ready char if any).
        """
        end = time.time() + timeout
        buf = ""
        if self.ready_mode == "char":
            while time.time() < end:
                chunk = self._read_available()
                if chunk:
                    buf += chunk
                    if self.ready_char in chunk:
                        last = buf.rfind(self.ready_char)
                        return buf[:last].strip()
                else:
                    time.sleep(0.01)
            raise TimeoutError("Timed out waiting for ready char")
        else:
            last_rx = time.time()
            while time.time() < end:
                chunk = self._read_available()
                if chunk:
                    buf += chunk
                    last_rx = time.time()
                else:
                    if (time.time() - last_rx) * 1000.0 >= self.quiet_ms:
                        return buf.strip()
                    time.sleep(0.01)
            raise TimeoutError("Timed out waiting for silent period")

    def send(self, cmd: str, wait: bool = True, block_until_ready: bool = False, timeout: float = 60.0) -> str:
        """
        Send a VXM command (string without CR). Adds CR, optionally waits for immediate bytes,
        and optionally blocks until 'ready' per ready_mode.
        Returns accumulated text.
        """
        # Clear input to avoid mixing old bytes
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\r").encode("ascii", errors="ignore"))
        resp = ""
        if wait:
            # give the controller a moment to echo/print
            time.sleep(0.03)
            resp = self.ser.read(self.ser.in_waiting or 0).decode(errors="ignore")

        if block_until_ready:
            rest = self.wait_ready(timeout=timeout)
            resp = (resp + rest).strip()
        return resp.strip()

    # --------- High-level helpers ---------
    def set_speed(self, motor: int, speed: int, full_power: bool = False) -> str:
        prefix = "SA" if full_power else "S"
        return self.send(f"{prefix}{motor}M{speed}")

    def set_accel(self, motor: int, accel: int) -> str:
        return self.send(f"A{motor}M{accel}")

    def move_relative(self, motor: int, steps: int) -> str:
        return self.send(f"I{motor}M{steps}")

    def run(self, block: bool = True, timeout: float = 120.0) -> str:
        return self.send("R", block_until_ready=block, timeout=timeout)

    def stop(self, block: bool = True) -> str:
        return self.send("D", block_until_ready=block)

    def kill(self) -> str:
        return self.send("K")

    def clear(self) -> str:
        return self.send("C")

    def position(self, motor: int) -> str:
        axis_cmd = {1: "X", 2: "Y", 3: "Z", 4: "T"}.get(motor)
        if not axis_cmd:
            raise ValueError("motor must be 1..4")
        return self.send(axis_cmd, block_until_ready=True)

    def list_program(self) -> str:
        return self.send("lst", block_until_ready=True)

    # --------- Units ---------
    def set_scale(self, steps_per_mm: float) -> None:
        self.steps_per_mm = float(steps_per_mm)

    def mm_to_steps(self, mm: float) -> int:
        if self.steps_per_mm is None:
            raise RuntimeError("Scale not set. Call set_scale(steps_per_mm) first.")
        return int(round(mm * self.steps_per_mm))

    def move_mm(self, motor: int, mm: float) -> str:
        steps = self.mm_to_steps(mm)
        return self.move_relative(motor, steps)

    # --------- Homing ---------
    def home(self, motor: int, direction: str = "neg", speed: int = 500, backoff_steps: int = 200, timeout: float = 180.0) -> None:
        if direction not in ("neg", "pos"):
            raise ValueError("direction must be 'neg' or 'pos'")
        self.set_speed(motor, speed)
        self.send(f"I{motor}M-0" if direction == "neg" else f"I{motor}M0")
        self.run(block=True, timeout=timeout)
        # back off to clear switch
        steps = abs(backoff_steps)
        self.move_relative(motor, steps if direction == "neg" else -steps)
        self.run(block=True, timeout=timeout)
        # zero absolute
        self.send(f"IA{motor}M-0", block_until_ready=True)

    # --------- Busy detection ---------
    def is_busy(self, motor: int = 1, interval: float = 0.2) -> bool:
        """
        Returns True if motor is moving (position changes), False otherwise.
        """
        try:
            p1s = self.position(motor)
            p1 = int(p1s.strip().split()[0]) if p1s else 0
            time.sleep(interval)
            p2s = self.position(motor)
            p2 = int(p2s.strip().split()[0]) if p2s else 0
            return p1 != p2
        except Exception:
            return False


def list_serial_ports() -> list[str]:
    try:
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []
