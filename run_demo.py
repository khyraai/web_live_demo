#!/usr/bin/env python3
"""Unified runner for Khyra Voice AI Demo (Web Server + LiveKit Agent Worker).

Usage:
    python run_demo.py             # Run both the web backend server and the agent worker
    python run_demo.py --server    # Run only the web server
    python run_demo.py --agent     # Run only the LiveKit agent worker
"""

import argparse
import os
import signal
import subprocess
import sys
import time

from config import WEB_SERVER_HOST, WEB_SERVER_PORT, LIVEKIT_URL, AGENT_NAME


def run_process(cmd: list[str], name: str) -> subprocess.Popen:
    print(f"[*] Starting {name}: {' '.join(cmd)}")
    return subprocess.Popen(cmd, env=os.environ.copy())


def main():
    parser = argparse.ArgumentParser(description="Khyra Voice AI Demo Runner")
    parser.add_argument("--server", action="store_true", help="Start only the web demo server")
    parser.add_argument("--agent", action="store_true", help="Start only the LiveKit agent worker")
    args = parser.parse_args()

    python_bin = sys.executable

    server_cmd = [python_bin, "-m", "uvicorn", "server:app", "--host", str(WEB_SERVER_HOST), "--port", str(WEB_SERVER_PORT), "--reload"]
    agent_cmd = [python_bin, "agent.py", "dev"]

    processes = []

    try:
        if args.server:
            p_server = run_process(server_cmd, "Web Demo Server")
            processes.append(p_server)
        elif args.agent:
            p_agent = run_process(agent_cmd, "LiveKit Agent Worker")
            processes.append(p_agent)
        else:
            print("=" * 70)
            print("  [*] Starting Khyra Web Voice AI Demo")
            print(f"  * Web Interface: http://localhost:{WEB_SERVER_PORT}")
            print(f"  * LiveKit URL:   {LIVEKIT_URL}")
            print(f"  * Agent Name:    {AGENT_NAME}")
            print("=" * 70)

            p_server = run_process(server_cmd, "Web Demo Server")
            processes.append(p_server)

            # Short delay so server starts listening before agent connects
            time.sleep(1)

            p_agent = run_process(agent_cmd, "LiveKit Agent Worker")
            processes.append(p_agent)

        # Monitor processes
        while True:
            for p in processes:
                ret = p.poll()
                if ret is not None:
                    print(f"[-] Process {p.pid} exited with code {ret}")
                    return ret
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n[*] Stopping all demo processes...")
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
        print("[*] All processes stopped.")


if __name__ == "__main__":
    main()
