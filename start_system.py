#!/usr/bin/env python3
"""
Enhanced launcher script for the Fraud Detection System
Starts both API and Streamlit dashboard with better error handling
"""
import subprocess
import sys
import time
import requests
import os
import signal
import atexit

# Global process variables
api_process = None
streamlit_process = None

def cleanup():
    """Cleanup function to terminate processes on exit"""
    global api_process, streamlit_process
    print("\n🛑 Shutting down services...")
    
    if streamlit_process:
        streamlit_process.terminate()
        try:
            streamlit_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            streamlit_process.kill()
    
    if api_process:
        api_process.terminate()
        try:
            api_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            api_process.kill()
    
    print("✅ All services stopped")

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    cleanup()
    sys.exit(0)

def check_api_running():
    """Check if API is already running"""
    try:
        response = requests.get("http://localhost:8001/health", timeout=3)
        return response.status_code == 200
    except:
        return False

def start_api():
    """Start the API server"""
    global api_process
    print("🚀 Starting API server...")
    
    try:
        api_process = subprocess.Popen(
            [sys.executable, "src/api/main.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait for API to start with better feedback
        print("⏳ Waiting for API to start...")
        for i in range(15):  # Wait up to 15 seconds
            time.sleep(1)
            if check_api_running():
                print("✅ API server started successfully on http://localhost:8001")
                return True
            print(f"   Checking... ({i+1}/15)")
        
        print("❌ API server failed to start within 15 seconds")
        if api_process:
            api_process.terminate()
        return False
        
    except Exception as e:
        print(f"❌ Failed to start API server: {e}")
        return False

def start_streamlit():
    """Start Streamlit dashboard"""
    global streamlit_process
    print("🎨 Starting Streamlit dashboard...")
    
    try:
        streamlit_process = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run", "streamlit_app.py",
            "--server.port=8501",
            "--server.address=0.0.0.0",
            "--server.headless=true"
        ])
        
        # Give Streamlit a moment to start
        time.sleep(3)
        print("✅ Streamlit dashboard started on http://localhost:8501")
        return True
        
    except Exception as e:
        print(f"❌ Failed to start Streamlit: {e}")
        return False

def main():
    """Main function"""
    # Register cleanup functions
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("🛡️  Fraud Detection System Launcher")
    print("=" * 50)
    
    # Check if API is already running
    if check_api_running():
        print("✅ API server is already running")
    else:
        if not start_api():
            print("❌ Cannot start system without API server")
            sys.exit(1)
    
    # Start Streamlit
    if not start_streamlit():
        cleanup()
        sys.exit(1)
    
    print("\n🎉 Fraud Detection System is ready!")
    print("📊 Dashboard: http://localhost:8501")
    print("🔧 API: http://localhost:8001/docs")
    print("\nPress Ctrl+C to stop all services")
    print("=" * 50)
    
    try:
        # Keep the script running and monitor processes
        while True:
            time.sleep(1)
            
            # Check if processes are still running
            if api_process and api_process.poll() is not None:
                print("❌ API server stopped unexpectedly")
                break
                
            if streamlit_process and streamlit_process.poll() is not None:
                print("❌ Streamlit dashboard stopped unexpectedly")
                break
                
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()

if __name__ == "__main__":
    main()