
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vxm_repl.py — Interactive CLI to control a Velmex VXM controller via RS-232/USB-RS232.

Now with blocking waits: operations like `run` and `home` will **wait until the VXM
signals ready** (the controller sends '^' when done).

Requirements:
    pip install pyserial

Usage:
    python vxm_repl.py --port COM3
    python vxm_repl.py --port /dev/ttyUSB0 --baud 9600

Type "help" inside the REPL for available commands.
"""

import argparse
import sys
import time
import shlex

try:
    import serial
    from serial.tools import list_ports
except Exception as e:
    print("❌ pyserial is required. Install it with:  pip install pyserial")
    raise

PROMPT = "VXM> "

class VXM:
    READY_CHAR = '^'

    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 0.2):
        # Use a short timeout so read loop can poll responsively
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=timeout,
        )
        # Enter On-Line mode ("F" = On-Line, echo off)
        self.send("F", wait=False)
        # Default unit scale: steps per mm (user can change with 'scale')
        self.steps_per_mm = None

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def _read_nonblocking(self) -> str:
        """Drain available bytes without blocking too long."""
        data = self.ser.read(self.ser.in_waiting or 1)
        return data.decode(errors="ignore")

    def wait_ready(self, timeout: float = 60.0) -> str:
        """
        Block until the controller sends the READY_CHAR '^' or the timeout expires.
        Returns the collected text (without the final '^').
        """
        end = time.time() + timeout
        buf = ""
        while time.time() < end:
            chunk = self._read_nonblocking()
            if chunk:
                buf += chunk
                if self.READY_CHAR in chunk:
                    # split at last '^' to be safe
                    last = buf.rfind(self.READY_CHAR)
                    out = buf[:last].strip()
                    return out
            else:
                # brief yield
                time.sleep(0.01)
        raise TimeoutError("Timed out waiting for controller ready '^'")

    def send(self, cmd: str, wait: bool = True, block_until_ready: bool = False, timeout: float = 60.0) -> str:
        """
        Send a raw command (without trailing CR).
        - If wait==True, read any immediate response (non-blocking).
        - If block_until_ready==True, additionally wait for '^' indicating completion.
        Returns accumulated response text.
        """
        # Clear input buffer (avoid mixing old output)
        self.ser.reset_input_buffer()
        data = (cmd + "\r").encode("ascii", errors="ignore")
        self.ser.write(data)

        resp = ""
        # Small grace period to allow immediate echo/message
        t0 = time.time()
        if wait:
            time.sleep(0.03)
            resp = self.ser.read(self.ser.in_waiting or 0).decode(errors="ignore")

        if block_until_ready:
            rest = self.wait_ready(timeout=timeout)
            resp = (resp + rest).strip()

        return resp.strip()

    # High-level helpers
    def set_speed(self, motor: int, speed: int, full_power: bool = False):
        # S = speed (70% power) ; SA = speed at 100% power
        prefix = "SA" if full_power else "S"
        return self.send(f"{prefix}{motor}M{speed}")

    def set_accel(self, motor: int, accel: int):
        return self.send(f"A{motor}M{accel}")

    def move_relative(self, motor: int, steps: int):
        # Incremental move
        return self.send(f"I{motor}M{steps}")

    def run(self, block: bool = True, timeout: float = 120.0):
        # 'R' starts queued moves; if block=True, wait for '^'
        return self.send("R", block_until_ready=block, timeout=timeout)

    def stop(self, block: bool = True):
        return self.send("D", block_until_ready=block)

    def kill(self):
        return self.send("K")

    def position(self, motor: int):
        # X=1, Y=2, Z=3, T=4 according to VXM docs
        axis_cmd = {1: "X", 2: "Y", 3: "Z", 4: "T"}.get(motor)
        if not axis_cmd:
            raise ValueError("motor must be 1..4")
        return self.send(axis_cmd, block_until_ready=True)

    def list_program(self):
        """List current program/memory (VXM 'lst')."""
        return self.send("lst", block_until_ready=True)

    # Convenience conversions
    def mm_to_steps(self, mm: float) -> int:
        if self.steps_per_mm is None:
            raise RuntimeError("Scale not set. Use: scale <steps_per_mm>")
        return int(round(mm * self.steps_per_mm))

    # Homing utility with blocking waits
    def home(self, motor: int, direction: str = "neg", speed: int = 500, backoff_steps: int = 200, timeout: float = 180.0):
        """
        Home a motor to a limit switch, then back off and set zero.
        Uses blocking waits until the controller signals ready.

        direction: 'neg' or 'pos' — which limit to seek.
        speed: steps/sec used during homing (<=1000 recommended).
        backoff_steps: steps to move away from the switch before zeroing.
        timeout: max seconds to wait for each move to complete.
        """
        if direction not in ("neg", "pos"):
            raise ValueError("direction must be 'neg' or 'pos'")
        # Safe speed
        self.set_speed(motor, speed)
        # Seek limit
        if direction == "neg":
            self.send(f"I{motor}M-0")
        else:
            self.send(f"I{motor}M0")
        self.run(block=True, timeout=timeout)

        # Back off to clear switch
        steps = abs(backoff_steps)
        if direction == "neg":
            self.move_relative(motor, steps)
        else:
            self.move_relative(motor, -steps)
        self.run(block=True, timeout=timeout)

        # Set absolute zero at current location for that motor
        self.send(f"IA{motor}M-0", block_until_ready=True)

HELP = """\
Commands:
  help                                      Show this help
  ports                                     List available serial ports
  send <raw>                                Send a raw command (without trailing CR)
  speed <motor> <steps_per_s> [full]        Set speed (1..6000), 'full' for 100% power
  accel <motor> <val>                       Set acceleration (1..127)
  move <motor> <steps>                      Relative move in steps (+/-)
  move_mm <motor> <mm>                      Relative move in millimeters (requires scale)
  run [noblock] [timeout]                   Start motion (R). Default blocks until '^'
  stop                                      Decelerated stop (D), blocks
  kill                                      Immediate stop (K)
  pos [motor]                               Read position for motor (1..4). Default 1
  scale <steps_per_mm>                      Define conversion scale for move_mm
  home <motor> [neg|pos] [speed] [backoff]  Home to limit, back off, set zero (defaults: neg 500 200)
  status                                    Show program/memory listing (lst)
  sleep <seconds>                           Pause a bit
  quit / exit                               Leave the REPL

Notes:
  • The controller sends '^' when ready; this REPL blocks on long ops by default.
  • Typical sequence:
        speed 1 1000
        accel 1 5
        move 1 400
        run
        pos 1
"""

def list_serial_ports() -> list[str]:
    try:
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []

def repl(vxm: VXM):
    print("✅ Connected. Type 'help' for commands.\n")
    while True:
        try:
            line = input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line.strip():
            continue

        try:
            args = shlex.split(line)
        except ValueError as e:
            print(f"Parse error: {e}")
            continue

        cmd = args[0].lower()

        try:
            if cmd in ("quit", "exit"):
                break

            elif cmd == "help":
                print(HELP)

            elif cmd == "ports":
                ports = list_serial_ports()
                if ports:
                    print("Available ports:")
                    for p in ports:
                        print(" ", p)
                else:
                    print("No ports found.")

            elif cmd == "send":
                if len(args) < 2:
                    print("Usage: send <raw>")
                else:
                    raw = " ".join(args[1:])
                    resp = vxm.send(raw, block_until_ready=True)
                    print(resp if resp else "OK")

            elif cmd == "speed":
                if len(args) < 3:
                    print("Usage: speed <motor> <steps_per_s> [full]")
                else:
                    motor = int(args[1])
                    spd = int(args[2])
                    full = (len(args) > 3 and args[3].lower() in ("full", "true", "1", "yes", "y"))
                    print(vxm.set_speed(motor, spd, full))

            elif cmd == "accel":
                if len(args) < 3:
                    print("Usage: accel <motor> <val>")
                else:
                    motor = int(args[1])
                    acc = int(args[2])
                    print(vxm.set_accel(motor, acc))

            elif cmd == "move":
                if len(args) < 3:
                    print("Usage: move <motor> <steps>")
                else:
                    motor = int(args[1])
                    steps = int(args[2])
                    print(vxm.move_relative(motor, steps))

            elif cmd == "move_mm":
                if len(args) < 3:
                    print("Usage: move_mm <motor> <mm>  (requires 'scale')")
                else:
                    motor = int(args[1])
                    mm = float(args[2])
                    steps = vxm.mm_to_steps(mm)
                    print(f"# {mm} mm -> {steps} steps")
                    print(vxm.move_relative(motor, steps))

            elif cmd == "run":
                # run [noblock] [timeout]
                noblock = (len(args) > 1 and args[1].lower() in ("noblock", "nb"))
                timeout = float(args[2]) if len(args) > 2 else 120.0
                print(vxm.run(block=(not noblock), timeout=timeout))

            elif cmd == "stop":
                print(vxm.stop())

            elif cmd == "kill":
                print(vxm.kill())

            elif cmd == "pos":
                motor = int(args[1]) if len(args) > 1 else 1
                print(vxm.position(motor))

            elif cmd == "scale":
                if len(args) < 2:
                    print("Usage: scale <steps_per_mm>")
                else:
                    vxm.steps_per_mm = float(args[1])
                    print(f"Scale set: {vxm.steps_per_mm} steps/mm")

            elif cmd == "home":
                if len(args) < 2:
                    print("Usage: home <motor> [neg|pos] [speed] [backoff_steps]")
                else:
                    motor = int(args[1])
                    direction = args[2].lower() if len(args) > 2 else "neg"
                    speed = int(args[3]) if len(args) > 3 else 500
                    backoff = int(args[4]) if len(args) > 4 else 200
                    vxm.home(motor, direction=direction, speed=speed, backoff_steps=backoff)
                    print(f"Homed M{motor} to {direction} limit, backoff {backoff} steps, zeroed.")

            elif cmd == "status":
                print(vxm.list_program())

            elif cmd == "sleep":
                secs = float(args[1]) if len(args) > 1 else 1.0
                time.sleep(secs)

            else:
                print(f"Unknown command: {cmd}. Type 'help'.")

        except Exception as e:
            print(f"❌ {e}")

def main():
    parser = argparse.ArgumentParser(description="Interactive REPL for Velmex VXM.")
    parser.add_argument("--port", help="Serial port (e.g., COM3 or /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=9600, help="Baudrate (default 9600)")
    parser.add_argument("--list", action="store_true", help="List serial ports and exit")
    args = parser.parse_args()

    if args.list:
        ports = list_serial_ports()
        if ports:
            print("Available ports:")
            for p in ports:
                print(" ", p)
        else:
            print("No ports found.")
        return 0

    if not args.port:
        print("Please specify --port. Example: --port COM3  or  --port /dev/ttyUSB0")
        return 2

    try:
        vxm = VXM(args.port, baudrate=args.baud, timeout=0.2)
    except Exception as e:
        print(f"❌ Unable to open port {args.port}: {e}")
        return 1

    try:
        repl(vxm)
    finally:
        vxm.close()
        print("🔌 Serial closed.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
