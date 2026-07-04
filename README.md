# CardSync

**Visiting card digitization via a chat interface.** Upload a card photo, the AI agent extracts the contact, confirms with you, logs it to your contact list, and sends you an email — all in one flow.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-cardsync.dev-2563eb?style=flat-square)](https://www.cardsync.dev)
![Python](https://img.shields.io/badge/Python-3.12-3776ab?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1.x-f97316?style=flat-square)
![React](https://img.shields.io/badge/React-18-61dafb?style=flat-square&logo=react&logoColor=black)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Neon-4169e1?style=flat-square&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-deployed-2496ed?style=flat-square&logo=docker&logoColor=white)

---

## What it does

- Upload a visiting card photo — GPT-4o extracts name, phone, email, and company
- The agent checks for duplicates before writing; re-uploads of the same card are silently rejected
- You confirm (and optionally edit) the extracted details before anything is saved
- Contact is logged to Postgres, company website and LinkedIn are auto-enriched, and you get an email via Resend
- Send a voice note in the same session — Whisper transcribes it and attaches it to the right contact automatically

---

## Tech Stack

| Category | Technology | Purpose |
|---|---|---|
| AI / ML | GPT-4o, Whisper | Vision extraction, company enrichment, voice transcription |
| Agent framework | LangGraph 1.x | Tool-calling loop, HITL interrupts, MongoDB checkpointer |
| Backend | FastAPI + uvicorn | REST endpoints and WebSocket server |
| Frontend | React (Vite) | Chat UI, contacts view, CSV export |
| Contact store | Neon Postgres (asyncpg) | Structured contacts, dedup, per-user isolation |
| App state | MongoDB Atlas | Sessions, messages, users, LangGraph checkpoint collections |
| Auth | Clerk | JWT issuance; backend verifies RS256 signature against JWKS |
| File storage | Cloudflare R2 | Card images and voice audio; bytes never touch the LLM |
| Email | Resend | Contact-logged notification to the authenticated user |
| Deployment | AWS EC2 + Nginx, Vercel | Backend (Docker container), frontend (static) |

---

## Architecture

A single LangGraph `StateGraph` with two nodes (`agent → tools → agent`) drives the entire flow. The graph is compiled once at startup with a MongoDB checkpointer; every session gets its own `thread_id`, so state (including the active contact's UUID) survives across WebSocket reconnections. Files are uploaded to R2 via REST first; only the storage key enters agent state — raw bytes never pass through the LLM. See [DOCUMENTATION.md](./DOCUMENTATION.md) for the full architecture diagram, every tool signature, the HITL interrupt mechanism, and database schemas.

---

## Key Features

- **GPT-4o structured extraction** — uses `response_format` with a Pydantic schema; the model cannot return malformed JSON
- **HITL confirmation** — `interrupt()` fires before any database write; on resume the tool re-runs from the top, making confirmation idempotent
- **Dedup with normalisation** — email (lowercase + strip) and phone (digits only) are compared after normalisation; checks run before the confirm step
- **Company enrichment** — `enrich_company` tool asks GPT-4o for website and LinkedIn URL and writes them to the contact row
- **Whisper voice notes** — transcript is shown for review before being written; `current_row_id` in checkpointed state links the note to the correct contact
- **Resend email alerts** — sent to the authenticated user's `notification_email` after every successful log
- **Clerk auth** — RS256 JWT verified against Clerk JWKS; WebSocket auth via `?token=` query param (browsers cannot set WS headers)
- **Per-user data isolation** — every Postgres query and MongoDB operation includes `user_id` from the verified JWT
- **Free tier with waitlist** — 2 card scans per account; limit modal captures email for waitlist via an idempotent upsert

---

## Local Setup

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # fill in values (see table below)
uvicorn app.main:app --reload --port 8000
```

API at `http://localhost:8000` — OpenAPI docs at `/docs`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env                                 # defaults point to localhost:8000
npm run dev
```

App at `http://localhost:5173`.

### Agent smoke test (no UI)

```bash
cd backend
python -m app.agent.smoke
```

### Environment variables

**`backend/.env`**

| Variable | Where to get it |
|---|---|
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| `MONGODB_URI` | Atlas dashboard → Connect → Drivers (`mongodb+srv://...`) |
| `DATABASE_URL` | Neon dashboard → Connection string (`postgresql://...`) |
| `CLERK_SECRET_KEY` | Clerk dashboard → API Keys |
| `RESEND_API_KEY` | [resend.com](https://resend.com) → API Keys |
| `R2_ACCOUNT_ID` | Cloudflare dashboard → R2 |
| `R2_ACCESS_KEY_ID` | R2 → Manage R2 API Tokens |
| `R2_SECRET_ACCESS_KEY` | Same page (shown once on creation) |
| `R2_BUCKET` | R2 bucket name |
| `R2_PUBLIC_URL` | R2 bucket → Settings → Public access URL |
| `CORS_ORIGINS` | Comma-separated allowed origins, e.g. `http://localhost:5173` |

**`frontend/.env`**

| Variable | Value |
|---|---|
| `VITE_CLERK_PUBLISHABLE_KEY` | Clerk dashboard → API Keys (starts with `pk_`) |
| `VITE_API_BASE_URL` | `http://localhost:8000` (local) or `https://api.cardsync.dev` (prod) |
| `VITE_WS_BASE_URL` | `ws://localhost:8000` (local) or `wss://api.cardsync.dev` (prod) |

---

## Deployment

Full guide (Docker build, EC2 setup, Nginx config, Let's Encrypt SSL, domain wiring) is in [DOCUMENTATION.md § Deployment](./DOCUMENTATION.md#10-deployment).

| | URL |
|---|---|
| Frontend | https://www.cardsync.dev |
| Backend API | https://api.cardsync.dev |
| Health check | https://api.cardsync.dev/health |
| Hosting | AWS EC2 t3.micro (Mumbai) + Nginx + Let's Encrypt / Vercel |

---

## Project Structure

```
backend/
  app/
    main.py              # FastAPI app, all REST routes, WebSocket handler
    auth.py              # Clerk JWKS fetch and RS256 JWT verification
    models.py            # Pydantic request/response schemas
    agent/
      graph.py           # StateGraph definition, checkpointer wiring
      state.py           # AgentState TypedDict
      tools.py           # All @tool functions (the only place external calls are made)
      prompts.py         # System prompt encoding the agent workflow
      runner.py          # graph.astream → WebSocket event emitter
    services/
      database.py        # Neon Postgres via SQLAlchemy async + asyncpg
      mongo.py           # MongoDB: sessions, messages, users, waitlist
      llm.py             # GPT-4o vision extraction, enrichment, Whisper transcription
      storage.py         # Cloudflare R2 via boto3 S3-compatible API
      email.py           # Resend transactional email
      whatsapp.py        # (legacy) Meta WhatsApp Cloud API
      sheets.py          # (legacy) Google Sheets via gspread
  Dockerfile
  requirements.txt

frontend/
  src/
    App.jsx              # Root: session state, scan count, tab routing
    api.js               # All fetch() calls to the REST API
    socket.js            # WebSocket wrapper with pre-connect send queue
    components/
      LandingPage.jsx    # Marketing page with CardSwap animation
      Sidebar.jsx        # Session list, tabs, scan counter, profile footer
      ChatWindow.jsx     # WebSocket consumer, message thread, interrupt handling
      ContactsView.jsx   # Full contacts table with search, sort, CSV export
      ConfirmCard.jsx    # HITL confirmation UI for contacts and transcripts
      Composer.jsx       # Text input + image/audio upload + record button
      Message.jsx        # Individual message bubble renderer
      CardSwap.jsx       # GSAP card stack animation (landing page)
```

---

## Legacy Integrations

`backend/app/services/whatsapp.py` and `backend/app/services/sheets.py` are not imported or called anywhere in the active codebase. They are kept as reference implementations: `whatsapp.py` shows the Meta WhatsApp Cloud API template message flow (v1 notification method); `sheets.py` documents the original Google Sheets contact store (replaced by Neon Postgres in v2 for per-user isolation and query capability).
