# Setting up AyuMitra AI on a new Windows PC

This copy runs everything locally: the React frontend, the Django backend, the AI service and the
Qwen2.5-3B model (on the CPU, no GPU needed). It contains no user accounts or uploaded documents;
you start with an empty database.

## What you need

| | |
|---|---|
| Windows 10/11, 64-bit | `llama-server.exe` in `ai_service/runtime/llama` is a Windows build |
| 16 GB RAM recommended (8 GB minimum) | the model alone uses about 3.4 GB |
| About 8 GB free disk | about 2.2 GB for this folder plus Python packages |
| Internet for the first setup | Python and npm packages, and three small AI models downloaded on first start |
| [Python 3.13](https://www.python.org/downloads/) | tick **"Add python.exe to PATH"** in the installer |
| [Node.js 24 LTS](https://nodejs.org/) | includes npm |

Check both from PowerShell: `py -3.13 --version` and `node -v`.

## 1. Unzip

Extract the zip to a short path without spaces, for example `C:\medirag-ai`. All commands below are
run in **PowerShell**, starting from that folder.

## 2. Settings file

```powershell
cd C:\medirag-ai
copy .env.example .env
py -3.13 -c "import secrets; print(secrets.token_urlsafe(50))"
```

Open `.env` in Notepad and replace `change-me` after `DJANGO_SECRET_KEY=` with the printed value.
Everything else can stay as it is.

## 3. Backend (Django)

```powershell
cd C:\medirag-ai\backend
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
```

## 4. AI service

```powershell
cd C:\medirag-ai\ai_service
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python -m pip install -r requirements.txt
```

Optional: `copy .env.example .env` and add a contact to enable Wikipedia answers.

The knowledge library (57 sources, already indexed in `ai_service/data`) and the Qwen model
(`ai_service/models`) are included, so nothing needs to be rebuilt.

## 5. Frontend

```powershell
cd C:\medirag-ai\frontend
npm ci
```

## 6. Start the app (five PowerShell windows)

| Window | Command | Ready when |
|---|---|---|
| 1. Qwen model | `cd C:\medirag-ai\ai_service; powershell -ExecutionPolicy Bypass -File scripts\start_llm.ps1` | `listening on http://127.0.0.1:8081` |
| 2. AI service | `cd C:\medirag-ai\ai_service; .venv\Scripts\uvicorn ayumitra_ai.api:app --host 127.0.0.1 --port 8001` | `Application startup complete` (first start downloads ~300 MB of models) |
| 3. Backend | `cd C:\medirag-ai\backend; .venv\Scripts\python manage.py runserver 127.0.0.1:8000` | `Starting development server` |
| 4. Document worker | `cd C:\medirag-ai\backend; .venv\Scripts\python manage.py process_documents` | stays running quietly |
| 5. Frontend | `cd C:\medirag-ai\frontend; npm run dev` | `Local: http://localhost:5173/` |

Open **http://localhost:5173** and register a new account.

To stop: press `Ctrl+C` in each window.

## Checks

- http://127.0.0.1:8001/health shows `"llm_reachable":true`
- http://127.0.0.1:8000/api/health/ shows `ok`

## Good to know

- **Answers are slow** on a CPU: about 30–90 s per assistant question. That is normal.
- **Nearby hospitals map** uses free OpenStreetMap servers. If it says the service is busy, try again
  a minute later.
- **`llama-server.exe` doesn't start / missing DLL:** install the
  [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe).
- **`py` not found:** reinstall Python with "Add python.exe to PATH" ticked, or use `python` instead of `py -3.13`.
- **Port already in use:** another copy is still running; close its window.
