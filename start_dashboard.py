import subprocess
import time
import webbrowser
import os
import sys

def main():
    print("🚀 Starting Distributed Load Balancer Dashboard...")

    # 1. Start Backend
    print("🔹 Launching Backend API (FastAPI)...")
    backend_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.dashboard.backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=os.getcwd()
    )

    # 2. Start Frontend
    print("🔹 Launching Frontend UI (Vite)...")
    # We need to find where npm is or just run it via shell
    frontend_dir = os.path.join("src", "dashboard", "frontend")
    
    # Use 'npm.cmd' on Windows, 'npm' on others
    npm_cmd = "npm.cmd" if os.name == 'nt' else "npm"
    
    frontend_process = subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=frontend_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    print("\n✅ Dashboard is initializing...")
    print("   - Backend: http://127.0.0.1:8000")
    print("   - Frontend: http://localhost:5173")
    print("\n⏳ Waiting for services to come online...")
    
    time.sleep(5) # Give it a moment
    
    # Open Browser
    webbrowser.open("http://localhost:5173")

    print("\n🎉 System is Live! Press Ctrl+C to stop.")

    try:
        backend_process.wait()
        frontend_process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        backend_process.terminate()
        frontend_process.terminate()
        sys.exit(0)

if __name__ == "__main__":
    main()
