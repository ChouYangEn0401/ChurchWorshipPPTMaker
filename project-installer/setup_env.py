import os
import subprocess
import sys

VENV_DIR = "venv"
REQUIREMENTS_FILE = "requirements.txt"

def run_command(command, cwd=None):
    """Run a shell command and ensure success."""
    try:
        subprocess.check_call(command, shell=True, cwd=cwd)
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        sys.exit(1)

def setup_venv():
    """Set up the virtual environment."""
    if not os.path.exists(VENV_DIR):
        print("Creating virtual environment...")
        run_command([sys.executable, "-m", "venv", VENV_DIR])

    python_executable = os.path.join(VENV_DIR, "Scripts", "python.exe")

    print("Upgrading pip...")
    run_command(f'"{python_executable}" -m pip install --upgrade pip')

    if os.path.exists(REQUIREMENTS_FILE):
        print(f"Installing dependencies from {REQUIREMENTS_FILE}...")
        run_command(f'"{python_executable}" -m pip install -r {REQUIREMENTS_FILE}')
    else:
        print(f"No {REQUIREMENTS_FILE} found. Skipping dependency installation.")

if __name__ == "__main__":
    setup_venv()
