
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vxm_repl.py — Interactive CLI REPL built on top of vxm.VXM.
"""

import argparse
import sys
import time
import shlex

from vxm import VXM, list_serial_ports

PROMPT = "VXM> "

HELP = """\
Commands:
  help                                      Show this help
  ports                                     List available serial ports
  send <raw>                                Send a raw command (no CR needed) and wait
  speed <motor> <steps_per_s> [full]        Set speed (1..6000), 'full' for 100% power
  accel <motor> <val>                       Set acceleration (1..127)
  move <motor> <steps>                      Relative move in steps (+/-)
  move_mm <motor> <mm>                      Relative move in millimeters (requires 'scale')
  run [noblock] [timeout]                   Start motion (R). Default blocks until ready
  stop                                      Decelerated stop (D), blocks
  kill                                      Immediate stop (K)
  clear                                     Clear queued commands (C)
  pos [motor]                               Read position for motor (1..4). Default 1
  isbusy [motor] [interval_s]               True if position changes over interval (default 0.2s)
  scale <steps_per_mm>                      Define conversion scale for move_mm
  home <motor> [neg|pos] [speed] [backoff]  Home to limit, back off, set zero
  status                                    Show program/memory listing (lst)
  readymode [char|silence]                  Switch ready detection strategy
  readychar <char>                          Set the prompt character (default '^')
  quietms <milliseconds>                    Set silence window (default 150 ms)
  monitor [seconds]                         Print raw incoming data (diagnostic)
  sleep <seconds>                           Pause a bit
  quit / exit                               Leave the REPL
"""

def monitor(vxm: VXM, seconds: float = 10.0) -> None:
    print(f"# Monitoring raw serial for {seconds} s (Ctrl+C to stop) ...")
    end = time.time() + seconds
    try:
        while time.time() < end:
            s = vxm._read_available()
            if s:
                for ch in s:
                    if ch.isprintable() and ch not in '\r\n':
                        print(ch, end='', flush=True)
                    elif ch == '\r':
                        print('\\r', end='', flush=True)
                    elif ch == '\n':
                        print('\\n\n', end='', flush=True)
                    else:
                        print(f"\\x{ord(ch):02x}", end='', flush=True)
            else:
                time.sleep(0.01)
        print("\n# Monitor done.")
    except KeyboardInterrupt:
        print("\n# Monitor interrupted.")

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
                noblock = (len(args) > 1 and args[1].lower() in ("noblock", "nb"))
                timeout = float(args[2]) if len(args) > 2 else 120.0
                print(vxm.run(block=(not noblock), timeout=timeout))

            elif cmd == "stop":
                print(vxm.stop())

            elif cmd == "kill":
                print(vxm.kill())

            elif cmd == "clear":
                print(vxm.clear())

            elif cmd == "pos":
                motor = int(args[1]) if len(args) > 1 else 1
                print(vxm.position(motor))

            elif cmd == "isbusy":
                motor = int(args[1]) if len(args) > 1 else 1
                interval = float(args[2]) if len(args) > 2 else 0.2
                print(f"Motor {motor} busy: {vxm.is_busy(motor, interval)}")

            elif cmd == "scale":
                if len(args) < 2:
                    print("Usage: scale <steps_per_mm>")
                else:
                    vxm.set_scale(float(args[1]))
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

            elif cmd == "readymode":
                if len(args) < 2 or args[1].lower() not in ("char", "silence"):
                    print("Usage: readymode [char|silence]")
                else:
                    vxm.ready_mode = args[1].lower()
                    print(f"Ready mode set to: {vxm.ready_mode}")

            elif cmd == "readychar":
                if len(args) < 2 or len(args[1]) != 1:
                    print("Usage: readychar <single_char>")
                else:
                    vxm.ready_char = args[1]
                    print(f"Ready char set to: {vxm.ready_char}")

            elif cmd == "quietms":
                if len(args) < 2:
                    print("Usage: quietms <milliseconds>")
                else:
                    vxm.quiet_ms = int(args[1])
                    print(f"Quiet window set to: {vxm.quiet_ms} ms")

            elif cmd == "monitor":
                seconds = float(args[1]) if len(args) > 1 else 10.0
                monitor(vxm, seconds)

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
