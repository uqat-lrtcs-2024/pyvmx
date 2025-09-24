
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vxm_repl.py — CLI REPL for libvxm.VXM (non-blocking stop by default).
"""

import argparse,sys,shlex,time
from libvxm import VXM,list_serial_ports

PROMPT="VXM> "

HELP = """\
Commands:
  help
  ports
  send <raw>
  speed <m> <sps>
  accel <m> <val>
  move <m> <steps>
  move_mm <m> <mm>
  run [noblock] [timeout]          # default blocks
  stop [block] [timeout]           # default NON-blocking
  kill [block] [timeout]           # default NON-blocking
  clear [block] [timeout]          # default NON-blocking
  pos [m]
  isbusy [m] [interval]
  scale <steps_per_mm>
  home <m> [neg|pos] [speed] [backoff]
  status
  sleep <s>
  quit/exit
"""

def repl(vxm:VXM):
    print("✅ Connected. Type 'help'.")
    while True:
        try: line=input(PROMPT)
        except (EOFError,KeyboardInterrupt): print(); break
        if not line.strip(): continue
        try: args=shlex.split(line)
        except ValueError as e: print("Parse error",e); continue
        cmd=args[0].lower()
        try:
            if cmd in ("quit","exit"): break
            elif cmd=="help":
                print(HELP)
            elif cmd=="ports":
                for p in list_serial_ports(): print(p)
            elif cmd=="send":
                print(vxm.send(" ".join(args[1:])))
            elif cmd=="speed":
                print(vxm.set_speed(int(args[1]),int(args[2])))
            elif cmd=="accel":
                print(vxm.set_accel(int(args[1]),int(args[2])))
            elif cmd=="move":
                print(vxm.move_relative(int(args[1]),int(args[2])))
            elif cmd=="move_mm":
                print(vxm.move_mm(int(args[1]),float(args[2])))
            elif cmd=="run":
                noblock = (len(args)>1 and args[1].lower() in ("noblock","nb","no"))
                timeout = float(args[2]) if len(args)>2 else 120.0
                print(vxm.run(block=not noblock, timeout=timeout))
            elif cmd=="stop":
                block = (len(args)>1 and args[1].lower() in ("block","b","yes","y","true","1"))
                timeout = float(args[2]) if len(args)>2 else 60.0
                print(vxm.stop(block=block, timeout=timeout))
            elif cmd=="kill":
                block = (len(args)>1 and args[1].lower() in ("block","b","yes","y","true","1"))
                timeout = float(args[2]) if len(args)>2 else 60.0
                print(vxm.kill(block=block, timeout=timeout))
            elif cmd=="clear":
                block = (len(args)>1 and args[1].lower() in ("block","b","yes","y","true","1"))
                timeout = float(args[2]) if len(args)>2 else 10.0
                print(vxm.clear(block=block, timeout=timeout))
            elif cmd=="pos":
                m=int(args[1]) if len(args)>1 else 1
                raw=vxm.position_raw(m); val=vxm.position_value(m)
                print(f"Motor {m} pos raw='{raw}' parsed={val}")
            elif cmd=="isbusy":
                m=int(args[1]) if len(args)>1 else 1
                interval=float(args[2]) if len(args)>2 else 0.2
                print(vxm.is_busy(m, interval))
            elif cmd=="scale":
                vxm.set_scale(float(args[1])); print("scale set")
            elif cmd=="home":
                m=int(args[1]); dir=args[2].lower() if len(args)>2 else "neg"
                sp=int(args[3]) if len(args)>3 else 500
                back=int(args[4]) if len(args)>4 else 200
                vxm.home(m,dir,sp,back); print("homed")
            elif cmd=="sleep":
                time.sleep(float(args[1]))
            else: print("Unknown")
        except Exception as e: print("❌",e)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--baud",type=int,default=9600)
    ap.add_argument("--list",action="store_true")
    a=ap.parse_args()
    if a.list:
        for p in list_serial_ports(): print(p)
        return
    if not a.port: print("Need --port"); return
    vxm=VXM(a.port,baudrate=a.baud)
    try: repl(vxm)
    finally: vxm.close(); print("🔌 closed")

if __name__=="__main__": sys.exit(main())
