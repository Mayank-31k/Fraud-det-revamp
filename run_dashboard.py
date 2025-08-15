#!/usr/bin/env python3
"""
Simple launcher script that starts both API and Streamlit dashboard
"""
import subprocess
import sys
import time
import requests
import os

def check_api_running():
    """Check if API is already running"""
    try:
        response = requests.get("http://localhost:8001/health", timeout=5)
        return response.status_code == 200
    except:
        return False

def start_api():
    """Start the API server"""
    print("🚀 Starting API server...")
    try:
        api_process = subprocess.Popen(
            [sys.executable, "src/api/main.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait a moment for the API to start
        print("⏳ Waiting for API to start...")
        for i in range(10):  # Wait up to 10 seconds
            time.sleep(1)
            if check_api_running():
                print("✅ API server started successfully!")
                return api_process
            print(f"   Checking... ({i+1}/10)")
        
        print("❌ API server failed to start within 10 seconds")
        api_process.terminate()
        return None
        
    except Exception as e:
        print(f"❌ Failed to start API server: {e}")
        return None

def start_streamlit():
    """Start Streamlit dashboard"""
    print("🎨 Starting Streamlit dashboard...")
    try:
        streamlit_process = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run", "streamlit_app.py",
            "--server.port=8501",
            "--server.address=0.0.0.0"
        ])
        return streamlit_process
    except Exception as e:
        print(f"❌ Failed to start Streamlit: {e}")
        return None

def main():
    print("🛡️  Fraud Detection Dashboard Launcher")
    print("=" * 50)
    
    # Check if API is already running
    if check_api_running():
        print("✅ API server is already running")
        api_process = None
    else:
        api_process = start_api()
        if not api_process:
            print("❌ Cannot start dashboard without API server")
            sys.exit(1)
    
    # Start Streamlit
    streamlit_process = start_streamlit()
    if not streamlit_process:
        if api_process:
            api_process.terminate()
        sys.exit(1)
    
    print("\n🎉 Fraud Detection System is ready!")
    print("📊 Dashboard: http://localhost:8501")
    print("🔧 API: http://localhost:8001/docs")
    print("\nPress Ctrl+C to stop all services")
    
    try:
        # Wait for Streamlit to finish
        streamlit_process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Stopping services...")
        if api_process:
            api_process.terminate()
        streamlit_process.terminate()
        print("✅ All services stopped")

if __name__ == "__main__":
    main()