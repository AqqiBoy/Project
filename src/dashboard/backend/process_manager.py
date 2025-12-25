import asyncio
import sys
from typing import Dict, Optional
import os
import signal

# Global queue for broadcasting logs
log_queue = asyncio.Queue()

class ProcessManager:
    def __init__(self):
        self.processes: Dict[str, asyncio.subprocess.Process] = {}
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    async def _read_stream(self, stream, prefix: str):
        """Reads from a stream line by line and puts it into the log queue."""
        while True:
            line = await stream.readline()
            if line:
                decoded = line.decode().strip()
                formatted_log = f"[{prefix}] {decoded}"
                print(formatted_log)
                await log_queue.put(formatted_log)
            else:
                break

    async def start_process(self, name: str, script_name: str, args: list):
        if name in self.processes and self.processes[name].returncode is None:
            await log_queue.put(f"[System] {name} is already running.")
            return False

        script_path = os.path.join(self.project_root, script_name)
        python_exe = sys.executable

        # Force unbuffered output with -u so logs appear instantly
        cmd = [python_exe, "-u", script_path] + args
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.project_root
            )
            
            self.processes[name] = process
            await log_queue.put(f"[System] 🚀 {name} started (PID: {process.pid}).")

            asyncio.create_task(self._read_stream(process.stdout, name))
            asyncio.create_task(self._read_stream(process.stderr, name))
            
            return True
        except Exception as e:
            await log_queue.put(f"[System] ❌ Failed to start {name}: {e}")
            return False

    async def stop_process(self, name: str):
        if name not in self.processes:
            return False

        process = self.processes[name]
        if process.returncode is not None:
            del self.processes[name]
            return True

        await log_queue.put(f"[System] 🛑 Stopping {name}...")
        
        try:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.kill()
            
            await log_queue.put(f"[System] {name} stopped.")
            del self.processes[name]
            return True
        except Exception as e:
            await log_queue.put(f"[System] Error stopping {name}: {e}")
            return False

    def get_status(self):
        status = {}
        for name, proc in self.processes.items():
            status[name] = "running" if proc.returncode is None else "stopped"
        return status

manager = ProcessManager()