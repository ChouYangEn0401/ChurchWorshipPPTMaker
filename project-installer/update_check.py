import os
import subprocess
import sys
from pathlib import Path

VENV_DIR = "venv"
REQUIREMENTS_FILE = "project-installer\\requirements.txt"

def run_command(command):
    """Run a shell command and ensure success."""
    try:
        subprocess.check_call(command, shell=True)
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        sys.exit(1)

def check_and_update_dependencies():
    """Check and install missing/updated dependencies."""
    python_executable = os.path.join(VENV_DIR, "Scripts", "python.exe")
    
    if not os.path.exists(python_executable):
        print(f"Virtual environment not found at {VENV_DIR}. Please run setup_env.py first.")
        sys.exit(1)

    print("Checking for outdated or missing dependencies...")
    installed_packages = subprocess.check_output(
        f'"{python_executable}" -m pip freeze',
        shell=True,
        text=True
    ).splitlines()

    installed_packages = {pkg.split("==")[0]: pkg.split("==")[1] for pkg in installed_packages if "==" in pkg}

    if not os.path.exists(REQUIREMENTS_FILE):
        print(f"No {REQUIREMENTS_FILE} found. Skipping dependency check.")
        sys.exit(0)

    with open(REQUIREMENTS_FILE, "r") as req_file:
        required_packages = [line.strip() for line in req_file if line.strip() and not line.startswith("#")]

    missing_or_outdated = []
    for req in required_packages:
        if "==" in req:
            package, version = req.split("==")
            if package not in installed_packages or installed_packages[package] != version:
                missing_or_outdated.append(req)
        else:
            if req not in installed_packages:
                missing_or_outdated.append(req)

    if missing_or_outdated:
        print(f"Updating Dependencies: {', '.join(missing_or_outdated)}")
        run_command(f'"{python_executable}" -m pip install {" ".join(missing_or_outdated)}')
    else:
        print("All Dependencies Are Already Up-To-Date.")

if __name__ == "__main__":
    check_and_update_dependencies()
