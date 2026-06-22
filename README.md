# CardSync

A chat-based visiting card digitization system. Point it at a card photo and it extracts the contact details, checks for duplicates against a Google Sheet, logs the row, sends the manager a WhatsApp alert, and enriches the company with its website and LinkedIn page. Later in the same session, send a voice note and it transcribes and attaches it to the right contact row automatically.

---

## How it works

The user interacts through a chat UI. Each session maps to one LangGraph agent thread. The agent decides which tools to call based on what the user sends:

- Upload a card image: agent calls `extract_card_details`, then `check_duplicate`, then (if new) `log_contact_to_sheet`, `send_whatsapp_alert`, and `enrich_company`
- Send a voice note: agent calls `store_voice_note`, which transcribes it and attaches it to the card logged earlier in the same session

Two points in the flow pause for human confirmation before any writes happen: once before logging the contact (so the user can correct OCR errors), and once before saving the transcript (so the user can fix mishearings). Both support Confirm, Edit, or Reject.

---

## Architecture

### LangGraph agent

The graph has two nodes in a loop:

```
START
  |
  v
[agent]  <----+
  |            |
  | tool_calls |
  v            |
[tools] -------+
  |
  | no tool_calls
  v
 END
```

`agent` calls `gpt-4o` with the full message history and a system prompt. If the model returns tool calls, `tools` (a LangGraph `ToolNode`) executes them and appends the results. This loops until the model returns a plain text response.

The MongoDB checkpointer saves the full graph state after every step, keyed by `thread_id = session_id`. This is what allows a voice note sent in a later WebSocket turn to find the `current_row_id` that was written when the card was logged earlier.

### State

```python
class AgentState(TypedDict):
    messages: list          # full conversation history (append-only)
    session_id: str         # MongoDB session + LangGraph thread ID
    image_key: str | None   # R2 key set this turn, read by extract_card_details
    audio_key: str | None   # R2 key set this turn, read by store_voice_note
    current_row_id: str | None  # Sheet row written by log_contact_to_sheet,
                                # read by store_voice_note and enrich_company
```

`current_row_id` is the link between a card and any subsequent voice notes. It persists across WebSocket reconnects because the checkpointer writes it to MongoDB after every tool step.

### Tools

| Tool | What it does |
|------|--------------|
| `extract_card_details` | Downloads the image from R2, calls gpt-4o vision with a structured output schema, returns name/phone/email/company |
| `check_duplicate` | Scans the Google Sheet for a matching normalized email (primary) or phone (fallback) |
| `log_contact_to_sheet` | Calls `interrupt()` to pause for user confirmation, then appends the row and writes `current_row_id` into state |
| `send_whatsapp_alert` | POSTs a template message to the Meta Graph API |
| `enrich_company` | Asks gpt-4o for the company's website and LinkedIn URL and writes them to columns E/F |
| `store_voice_note` | Transcribes audio with Whisper, calls `interrupt()` for transcript review, writes audio URL and transcript to columns G/H |

File bytes never pass through the LLM. Tools receive an R2 key from injected state and fetch the bytes themselves.

### Services

Each external integration lives in its own module under `app/services/`:

- `llm.py` - gpt-4o vision extraction, gpt-4o enrichment, Whisper transcription
- `sheets.py` - gspread client, dedup, append, update
- `whatsapp.py` - Meta Cloud API template messages
- `storage.py` - Cloudflare R2 via boto3 S3-compatible API
- `mongo.py` - AsyncMongoClient for sessions and message history

### WebSocket protocol

Files are uploaded via REST first, then the key is sent over the socket.

Client to server:
```json
{ "text": "...", "image_key": "...", "audio_key": "..." }
{ "resume": { "decision": "confirm" } }
{ "resume": { "decision": "edit", "edits": { "name": "..." } } }
{ "resume": { "decision": "reject" } }
```

Server to client (streamed):
```json
{ "type": "token",     "data": "partial text..." }
{ "type": "tool",      "data": { "name": "extract_card_details", "status": "running" } }
{ "type": "tool",      "data": { "name": "extract_card_details", "status": "done" } }
{ "type": "interrupt", "data": { "action": "confirm_contact", "contact": {...} } }
{ "type": "done",      "data": {} }
{ "type": "error",     "data": "Internal server error" }
```

The `done` event is sent only when the graph actually finishes. If the graph pauses on an interrupt, the server sends `interrupt` and waits. The client resumes by sending a `resume` message on the same socket.

---

## Environment variables

### Backend (`backend/.env`)

| Variable | Description | Where to get it |
|----------|-------------|-----------------|
| `OPENAI_API_KEY` | OpenAI API key for gpt-4o and Whisper | platform.openai.com |
| `GOOGLE_SERVICE_ACCOUNT_B64` | Base64-encoded service account JSON | GCP console -> IAM -> Service accounts -> create key (JSON), then `base64 -w0 key.json` on Linux or `[Convert]::ToBase64String([IO.File]::ReadAllBytes("key.json"))` on Windows |
| `GOOGLE_SHEET_ID` | ID from the Sheet URL: `docs.google.com/spreadsheets/d/{ID}/` | Google Sheets URL bar |
| `MONGODB_URI` | Atlas connection string | Atlas dashboard -> Connect -> Drivers |
| `R2_ACCOUNT_ID` | Cloudflare account ID | R2 dashboard URL or Account Home |
| `R2_ACCESS_KEY_ID` | R2 API token access key ID | R2 -> Manage R2 API Tokens |
| `R2_SECRET_ACCESS_KEY` | R2 API token secret key | Same page, shown once on creation |
| `R2_BUCKET` | Name of the R2 bucket | R2 dashboard |
| `R2_PUBLIC_URL` | Public bucket URL (e.g. `https://pub-xxx.r2.dev`) | R2 bucket settings -> Public access |
| `WHATSAPP_TOKEN` | Meta Graph API access token | Meta for Developers -> WhatsApp -> API Setup |
| `WHATSAPP_PHONE_NUMBER_ID` | Phone number ID for the sending number | Same page |
| `WHATSAPP_RECIPIENT` | Recipient number in international format without `+` (e.g. `919876543210`) | The number to notify |
| `WHATSAPP_TEMPLATE_NAME` | Approved template name, or `hello_world` for testing | Meta -> WhatsApp -> Message Templates |
| `CORS_ORIGINS` | Comma-separated allowed origins, e.g. `https://your-app.vercel.app` | Your Vercel deployment URL |

The Google Sheet must have this header row (row 1, columns A through J):

```
Name | Phone | Email | Company | Website | LinkedIn | Audio URL | Transcript | Session ID | Created At
```

Share the sheet with the service account email (found in the JSON key file) as an editor.

### Frontend (`frontend/.env`)

| Variable | Description |
|----------|-------------|
| `VITE_API_BASE_URL` | Backend HTTP URL, e.g. `http://localhost:8000` locally or `https://your-app.onrender.com` in prod |
| `VITE_WS_BASE_URL` | Backend WebSocket URL, e.g. `ws://localhost:8000` locally or `wss://your-app.onrender.com` in prod |

---

## Local setup

### Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# fill in .env with your credentials

uvicorn app.main:app --reload --port 8000
```

The API runs at `http://localhost:8000`. Visit `/docs` for the auto-generated OpenAPI UI.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
# defaults point to localhost:8000, no changes needed for local dev

npm run dev
```

The app runs at `http://localhost:5173`.

### Smoke test

The smoke test drives the full agent flow without the UI. It uploads a real card image and voice note to R2, runs the agent end-to-end with an `InMemorySaver` (no MongoDB connection needed), and prints every tool call, tool result, and interrupt.

```bash
cd backend
# place sample_card.jpg and sample_voice.ogg in the backend/ folder
python -m app.agent.smoke
```

Expected trace:
1. Turn 1: `extract_card_details` -> `check_duplicate` -> `log_contact_to_sheet` -> INTERRUPT
2. Turn 2 (resumed with a name edit): row logged, `send_whatsapp_alert`, `enrich_company`
3. Turn 3: voice note -> `store_voice_note` -> INTERRUPT
4. Turn 3 resume (with transcript edit): transcript written to sheet

Run this before touching any endpoint code. It validates the agent logic independently of the API layer.

---

## Deployment

### Backend on Render

A `Dockerfile` is included in `backend/`, so the recommended approach is to deploy as a Docker container. Render auto-detects the Dockerfile when the environment is set to Docker.

1. Push the repo to GitHub.
2. Create a new Render **Web Service** pointing at the `backend/` directory.
3. Set the **Environment** to **Docker**. Render will detect the `Dockerfile` automatically — no separate build or start commands are needed.
4. Add all backend environment variables in the Render dashboard under **Environment**.
5. Set `CORS_ORIGINS` to your Vercel frontend URL.

To test the Docker build locally before pushing:

```bash
cd backend
docker build -t cardsync-backend .
docker run -p 8000:8000 --env-file .env cardsync-backend
```

The Render free tier sleeps after 15 minutes of inactivity. Use UptimeRobot or a similar pinger on the `/health` endpoint to keep it awake before demos.

### Frontend on Vercel

1. Import the repo in Vercel and set the root directory to `frontend/`.
2. Add `VITE_API_BASE_URL` and `VITE_WS_BASE_URL` pointing at your Render service URL (use `https://` and `wss://`).
3. Deploy. Vercel detects Vite automatically.

### MongoDB Atlas

Create a free M0 cluster. Under **Network Access**, add `0.0.0.0/0` to allow connections from Render (or restrict to Render's static outbound IPs if you have a paid plan). Copy the connection string into `MONGODB_URI`.

### WhatsApp template

Submit your custom template (`new_card_logged`) for approval as early as possible. Meta approval takes anywhere from a few minutes to 24 hours. While waiting, set `WHATSAPP_TEMPLATE_NAME=hello_world` to confirm the API connection works. The `hello_world` template takes no parameters so the alert body will be generic, but the plumbing is identical.

For production, replace the temporary 24-hour developer token with a permanent one. In Meta Business Manager, go to **Business Settings -> Users -> System Users**, create a system user, assign it the WhatsApp app with the `whatsapp_business_messaging` permission, and generate an access token. System user tokens do not expire. Set that token as `WHATSAPP_TOKEN` in your Render environment variables.

---

## Design decisions

**Google Sheets as the contact database.** The brief specified it and it fits the use case well: non-technical users can open the sheet directly, filter and sort contacts, and spot errors without any custom admin UI. The tradeoff is that every dedup check requires a full `get_all_records()` call, which is slow at scale. At the volume of visiting cards collected at a conference it is fine.

**MongoDB for sessions and the checkpointer.** The LangGraph MongoDB checkpointer needs a persistent store to save agent state between WebSocket turns. Using the same Atlas cluster for the session and message store keeps the infrastructure to one database. MongoDB is never used as the contact store.

**One session, one primary contact.** `current_row_id` in agent state is a single value. Each session is designed around one card: log it, enrich it, attach a voice note. If a second card is logged in the same session, `current_row_id` gets overwritten and voice notes will attach to the new card. This is a deliberate simplification, not an oversight.

**HITL before writes, not after.** Both `log_contact_to_sheet` and `store_voice_note` call `interrupt()` as the very first line of the tool body. LangGraph resumes a tool by re-running it from the top, so the write only happens after confirmation. If the interrupt fired after the write, a reject would have no effect.

**HITL extended to transcripts.** Whisper is accurate but not perfect, especially on names and company jargon. Showing the transcript before saving gives the user one chance to fix it. The same confirm/edit/reject UI handles both interrupts with no extra frontend code.

**Files by reference only.** Images and audio are uploaded to R2 via a REST endpoint first. Only the storage key enters the agent state. The LLM never sees raw bytes or base64. This keeps token costs low and avoids the model attempting to reason about file contents it was not asked about.

---

## Known limitations

**Voice notes attach to the most recently logged card per session.** There is no UI to select which contact a voice note refers to. If you log two cards in one session and send a voice note, it attaches to the second card.

**WhatsApp access token expires every 24 hours in development.** The temporary token from the Meta developer dashboard is only valid for one day. For production, create a System User in Meta Business Manager and generate a permanent token. See the Meta docs under "System User Access Tokens."

**Whisper is called twice on transcript resume.** `store_voice_note` transcribes before calling `interrupt()` so the user sees the real text immediately. When the user confirms, LangGraph re-runs the tool from the top and calls Whisper again. The two results are almost always identical. Fixing this properly would require caching the first transcript in agent state.

**Render free tier cold starts.** The backend takes 30 to 60 seconds to respond after sleeping. Pin it with a health check pinger before recording a demo.
