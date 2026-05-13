# Install

This project is designed to run from a fresh clone with a local Python environment and Ollama.

## Recommended first-run path

1. Clone the repository.
2. From the repository root, run:

   ```bash
   bash setup.sh
   ```

3. Start Ollama in another terminal:

   ```bash
   ollama serve
   ```

4. Pull the model used by default:

   ```bash
   ollama pull llama3:latest
   ```

5. Start the application:

   ```bash
   python3 master_terminal_chat.py --frontend
   ```

## What the setup script does

- Creates `.venv` if it does not already exist
- Upgrades `pip`
- Installs `requirements.txt`
- Verifies the main Python dependencies import correctly

## Notes

- The frontend ships prebuilt in `Fanuc-frontend/dist`, so no npm build step is required for normal use.
- If `sounddevice` fails to import, the machine may be missing system audio libraries. Install the OS-level audio packages and rerun `bash setup.sh`.
- If Ollama is not installed yet, install it separately before starting the app.