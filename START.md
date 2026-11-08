# Quick Start Guide

## 🚀 Easiest Way

```bash
# One command starts everything (if you have Docker)
cd docker
docker compose up --build
```

Then open http://localhost:8080

---

## 🛠️ Manual Start (3 terminals)

### Terminal 1 - Ollama
```bash
ollama serve
ollama pull nomic-embed-text  # embeddings model
```

### Terminal 2 - Backend (from the repository root)
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
./backend/run.sh
```

### Terminal 3 - Frontend
```bash
cd frontend
npm install
npm run dev
```

---

## 🎯 Quick Start Script

Two scripts available, both run from the repository root:

### Option A: `run.sh` (simple, all-in-one)
```bash
./run.sh
```
Starts the backend and frontend, and Ollama when it is already installed.

### Option B: `start-all.sh` (comprehensive)
```bash
./start-all.sh
```
Adds dependency checks, readiness polling and service cleanup.

---

## 🎨 After Starting

1. **Open**: http://localhost:5173 (frontend)
2. Go to **Documents** → Add files
3. Go to **Indexes** → Create + Build
4. Go to **Ask Knowledge** → Ask questions

---

## 🔧 Troubleshooting

**Ollama not responding?**
```bash
curl http://localhost:11434/api/tags
ollama pull nomic-embed-text
```

**Backend errors?** Run from the repository root so the package imports resolve:
```bash
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

**Frontend errors?**
```bash
cd frontend
npm run dev  # Check console for errors
```

---

## 📁 Project Structure

```
📁 local-knowledgeos/
├── 📁 backend/              # Python FastAPI server
│   ├── main.py              # App assembly (routers, CORS, lifespan)
│   ├── api/                 # Resource routers
│   ├── config.py, db.py, …  # Domain modules
│   └── run.sh               # Backend launcher
├── 📁 frontend/             # React/Vite UI
│   └── src/
├── 📁 docker/               # Docker compose
├── 📄 run.sh                # Quick start script
├── 📄 start-all.sh          # Full featured start script
└── 📄 START.md              # This file
```

---

## 🎯 Module Architecture

The backend engine is split into cohesive modules under `backend/`:

| Module | Purpose |
|--------|---------|
| `config.py` | Environment constants and validated `Settings` |
| `db.py` | SQLite schema, migrations, connections and backups |
| `security.py` | Secret files, file permissions and Fernet helpers |
| `auth.py` | Workspace principals and bearer authentication |
| `parsing.py` | PDF/DOCX/XLSX/PPTX/CSV/HTML/image extraction |
| `chunking.py` | Structure-aware chunk metadata over `utils.split_chunks` |
| `ingestion.py` | Uploads, job queue and the ingestion pipeline |
| `providers.py` | Provider profiles, embeddings and generation transport |
| `retrieval.py` | Catalog filters and hybrid FTS5/dense retrieval |
| `routing.py` | Rules, classifier and optional LLM query routing |
| `verification.py` | Claim splitting and lexical entailment |
| `cache.py` | Answer cache identity, lookup and storage |
| `indexes.py` | Index build/validate/evaluate/activate/rollback |
| `answering.py` | Metadata, conversational and grounded answers |
| `api/` | Thin HTTP routers grouped by resource |

See `backend/ARCHITECTURE.md` for dependency rules and the request flow.
