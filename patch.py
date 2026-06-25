import subprocess
import sys

def install_modules():
    print("Installing required modules...")
    modules = [
        "streamlit",
        "customtkinter",
        "psutil",
        "python-dotenv",
        "openai"
    ]
    for module in modules:
        try:
            print(f"Installing {module}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", module])
        except Exception as e:
            print(f"Failed to install {module}: {e}")
    print("Installation complete.")

if __name__ == "__main__":
    install_modules()
