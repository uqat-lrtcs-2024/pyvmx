
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
libvxm.py — Python library for Velmex VXM controllers (RS-232/USB-RS232).

Updates:
- stop(block: bool = False, timeout: float = 60.0): non-blocking by default.
- kill(block: bool = False), clear(block: bool = False): optional blocking.
- run(block: bool = True, timeout: float = 120.0): unchanged (blocks by default).
- position() uses a short line read to avoid hangs.
"""

import time, re
from typing import Optional

try:
    import serial
    from serial.tools import list_ports
except Exception as e:
    raise RuntimeError("pyserial is required. Install with: pip install pyserial") from e


class VXM:
    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 0.2):
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
        self.send("F", wait=False)        # On-Line mode
        self.steps_per_mm: Optional[float] = None

    def close(self): 
        try: self.ser.close()
        except: pass

    def __enter__(self): return self
    def __exit__(self, a,b,c): self.close()

    # -------- Helpers --------
    def _read_line(self, timeout: float = 1.0) -> str:
        end = time.time() + timeout
        buf = ""
        while time.time() < end:
            b = self.ser.read(1)
            if not b: continue
            ch = b.decode(errors="ignore")
            if ch in ("\r","\n"):
                self.ser.read(self.ser.in_waiting or 0)
                return buf.strip()
            buf += ch
        return buf.strip()

    def _wait_ready_silence(self, quiet_ms: int = 150, timeout: float = 60.0) -> str:
        end = time.time() + timeout
        buf = ""
        last_rx = time.time()
        while time.time() < end:
            chunk = self.ser.read(self.ser.in_waiting or 1).decode(errors="ignore")
            if chunk:
                buf += chunk
                last_rx = time.time()
            else:
                if (time.time() - last_rx) * 1000.0 >= quiet_ms:
                    return buf.strip()
                time.sleep(0.01)
        return buf.strip()

    def send(self, cmd: str, wait: bool = True) -> str:
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\r").encode("ascii", errors="ignore"))
        if wait:
            time.sleep(0.03)
            return self.ser.read(self.ser.in_waiting or 0).decode(errors="ignore").strip()
        return ""

    # -------- High-level API --------
    def set_speed(self, motor:int, speed:int): return self.send(f"S{motor}M{speed}")
    def set_accel(self, motor:int, accel:int): return self.send(f"A{motor}M{accel}")
    def move_relative(self, motor:int, steps:int): return self.send(f"I{motor}M{steps}")
    def run(self, block: bool = True, timeout: float = 120.0) -> str:
        self.send("R", wait=False)
        return self._wait_ready_silence(timeout=timeout) if block else ""
    def stop(self, block: bool = False, timeout: float = 60.0) -> str:
        self.send("D", wait=False)
        return self._wait_ready_silence(timeout=timeout) if block else ""
    def kill(self, block: bool = False, timeout: float = 60.0) -> str:
        self.send("K", wait=False)
        return self._wait_ready_silence(timeout=timeout) if block else ""
    def clear(self, block: bool = False, timeout: float = 10.0) -> str:
        self.send("C", wait=False)
        return self._wait_ready_silence(timeout=timeout) if block else ""

    def position_raw(self, motor:int, line_timeout:float=1.0)->str:
        axis = {1:"X",2:"Y",3:"Z",4:"T"}.get(motor)
        if not axis: raise ValueError("motor 1..4")
        self.ser.reset_input_buffer()
        self.ser.write((axis+"\r").encode("ascii"))
        return self._read_line(timeout=line_timeout)

    def position_value(self, motor:int, line_timeout:float=1.0)->Optional[int]:
        raw=self.position_raw(motor,line_timeout)
        m=re.search(r'[-+]?\d+', raw)
        return int(m.group(0)) if m else None

    def set_scale(self, steps_per_mm:float): self.steps_per_mm=float(steps_per_mm)
    def mm_to_steps(self, mm:float)->int:
        if self.steps_per_mm is None: raise RuntimeError("Scale not set")
        return int(round(mm*self.steps_per_mm))
    def move_mm(self, motor:int, mm:float): return self.move_relative(motor, self.mm_to_steps(mm))

    def home(self, motor:int, direction:str="neg", speed:int=500, backoff_steps:int=200):
        self.set_speed(motor,speed)
        self.send(f"I{motor}M-0" if direction=="neg" else f"I{motor}M0", wait=False)
        self.run(block=True)
        steps=abs(backoff_steps)
        self.move_relative(motor, steps if direction=="neg" else -steps)
        self.run(block=True)
        self.send(f"IA{motor}M-0")

    def is_busy(self, motor:int=1, interval:float=0.2)->bool:
        p1=self.position_value(motor) or 0
        time.sleep(interval)
        p2=self.position_value(motor) or 0
        return p1!=p2


def list_serial_ports():
    try: return [p.device for p in list_ports.comports()]
    except: return []
