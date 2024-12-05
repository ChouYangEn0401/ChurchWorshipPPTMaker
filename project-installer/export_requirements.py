import os
import subprocess

VENV_DIR = "venv"
REQUIREMENTS_FILE = "project-installer\\requirements.txt"

def export_requirements():
    """Export the current virtual environment's dependencies to requirements.txt."""
    python_executable = os.path.join(VENV_DIR, "Scripts", "python.exe")
    
    if not os.path.exists(python_executable):
        print(f"Virtual environment not found at {VENV_DIR}. Please ensure it is set up.")
        return

    print("Exporting dependencies to requirements.txt...")
    with open(REQUIREMENTS_FILE, "w") as req_file:
        subprocess.run(
            [python_executable, "-m", "pip", "freeze"],
            stdout=req_file,
            check=True
        )
    print(f"Dependencies exported to {REQUIREMENTS_FILE}.")

if __name__ == "__main__":
    export_requirements()
