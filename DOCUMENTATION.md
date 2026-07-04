# CardSync — Engineering Documentation

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Overview](#2-architecture-overview)
3. [LangGraph Agent Deep Dive](#3-langgraph-agent-deep-dive)
4. [API Reference](#4-api-reference)
5. [Database Schema](#5-database-schema)
6. [Authentication & Security](#6-authentication--security)
7. [Software Engineering Techniques](#7-software-engineering-techniques)
8. [Key Engineering Decisions](#8-key-engineering-decisions)
9. [Legacy Integrations](#9-legacy-integrations)
10. [Deployment](#10-deployment)
11. [Local Development Setup](#11-local-development-setup)

---

## 1. Project Overview

CardSync digitizes physical visiting cards via a chat interface. A user photographs a card, uploads it, and a LangGraph AI agent extracts the contact details using GPT-4o vision, checks for duplicates, confirms the details with the user, writes the contact to a Postgres database, sends an email notification, and optionally enriches the company information. In a later turn within the same session, the user can record a voice note; the agent transcribes it with Whisper and attaches it to the correct contact — identified by the UUID that was persisted in agent state at logging time.

**Problem solved**: Manual contact management after networking events is slow and error-prone. Visiting cards accumulate without ever becoming searchable records. CardSync turns a card photo into a structured contact in under 30 seconds.

**Target users**: Sales teams, founders, and professionals who collect visiting cards at events and need them in a searchable, notifiable contact list.

**v2 changes from the original spec**: Google Sheets replaced by Neon Postgres for the contact store; WhatsApp Cloud API replaced by Resend email for notifications.

---

## 2. Architecture Overview

```
┌────────────────────────────────────────────────────────────┐
│                     User's Browser                         │
│                                                            │
│   React + Vite (Vercel)                                    │
│   ┌──────────┐  ┌───────────────┐  ┌───────────────────┐   │
│   │ Sidebar  │  │  ChatWindow   │  │   ContactsView    │   │
│   │ sessions │  │  WS + upload  │  │   REST + CSV      │   │
│   └────┬─────┘  └──────┬────────┘  └─────────┬─────────┘   │
│        │               │                     │             │
└────────┼───────────────┼─────────────────────│─────────────┘
         │  REST + Bearer│  WS ?token=         │ REST
         ▼               ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│              FastAPI backend (Docker / EC2 + Nginx)         │
│                                                             │
│  ┌────────────────┐   ┌───────────────────────────────────┐ │
│  │  REST routes   │   │   WebSocket /ws/sessions/{id}     │ │
│  │  /api/*        │   │   auth → session check →          │ │
│  │  Clerk JWT     │   │   scan limit → run_and_stream     │ │
│  └────────┬───────┘   └──────────────┬────────────────────┘ │
│           │                          │                      │
│           ▼                          ▼                      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            LangGraph Agent (StateGraph)              │   │
│  │                                                      │   │
│  │  START → [agent node] ←──────────────┐               │   │
│  │               │                      │               │   │
│  │        has tool calls?               │               │   │
│  │          yes │     no → END          │               │   │
│  │               ▼                      │               │   │
│  │          [tools node] ───────────────┘               │   │
│  │     (ToolNode wraps all @tool functions)             │   │
│  │                                                      │   │
│  │  Tools: extract_card_details, check_duplicate,       │   │
│  │         log_contact_to_sheet, send_email_alert,      │   │
│  │         store_voice_note, enrich_company             │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
└──────────────────────────┬──────────────────────────────────┘ 
                           │ calls
        ┌──────────────────┼─────────────────────────┐
        ▼                  ▼                         ▼
┌──────────────┐  ┌────────────────┐       ┌─────────────────┐
│ Neon Postgres│  │  MongoDB Atlas │       │  Cloudflare R2  │
│  (asyncpg)   │  │  (AsyncMongo)  │       │  (boto3/S3 API) │
│              │  │                │       │                 │
│  contacts    │  │  sessions      │       │  card images    │
│  table       │  │  messages      │       │  voice notes    │
│  (one per    │  │  users         │       │                 │
│   user_id)   │  │  waitlist      │       │  public URLs    │
└──────────────┘  │  checkpoints   │       └────────┬────────┘
                  │  (LangGraph)   │                │
                  └────────────────┘                │ presigned
        ┌──────────────────────────────────────────┤  URL
        ▼                  ▼                        │
┌──────────────┐  ┌────────────────┐               │
│    Resend    │  │  OpenAI API    │               │
│  (email      │  │  gpt-4o vision │               │
│   alerts)    │  │  whisper-1     │               │
└──────────────┘  │  (structured   │               │
                  │   output)      │               │
                  └────────────────┘               │
                                                   ▼
                                        Files stored by R2 key,
                                        never passed to LLM as bytes.
                                        Only the key enters agent state.

┌────────────────────────────────────────┐
│  Clerk (external SaaS)                 │
│  Issues JWTs signed with RSA key pair. │
│  Backend fetches JWKS, verifies RS256. │
│  WebSocket auth via ?token= query param│
│  (browsers cannot set WS headers).     │
└────────────────────────────────────────┘
```

**Request flow for a card upload**:

1. Browser uploads the card file to `POST /api/sessions/{id}/upload` with Bearer token.
2. Backend writes bytes to R2, returns the R2 key.
3. Browser sends `{ image_key: "<key>" }` over the WebSocket.
4. Backend verifies ownership, checks scan limit, calls `graph.astream`.
5. Agent node calls GPT-4o, emits `token` events over the socket.
6. Tools node calls Postgres/R2/Resend as the agent directs.
7. Before writing, the graph pauses (`interrupt()`), sends `{ type: "interrupt" }` to the browser.
8. Browser displays a confirmation card; user confirms or edits.
9. Browser sends `{ resume: { decision, edits } }` over the same socket.
10. Graph resumes, writes the contact, sends email alert, enriches company.
11. Backend increments scan count in MongoDB, sends `{ type: "done" }`.

---

## 3. LangGraph Agent Deep Dive

### AgentState TypedDict

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # full conversation history; add_messages reducer appends
    session_id: str         # equals the WebSocket session_id and LangGraph thread_id
    image_key: Optional[str]  # R2 key for the card image uploaded this turn; None if no image
    audio_key: Optional[str]  # R2 key for the voice note uploaded this turn; None if no audio
    current_row_id: Optional[str]  # UUID of the contact logged in this session; persisted by checkpointer
    user_id: Optional[str]  # Clerk user_id from verified JWT; injected every turn, never from LLM
```

`current_row_id` is the critical field. It is written by `log_contact_to_sheet` via a `Command(update={"current_row_id": contact_id})` return, which LangGraph applies to the state. The MongoDB checkpointer then persists this state snapshot under the `thread_id` (= `session_id`). When the user later sends a voice note in the same session, `store_voice_note` reads `state["current_row_id"]` to know which Postgres row to update — without the LLM ever seeing or being asked for the row ID.

`image_key` and `audio_key` are reset to their incoming values on every WebSocket turn by the WS handler. This prevents stale keys from a previous turn from accidentally triggering re-processing.

### Graph Topology

```
START
  │
  ▼
agent_node  ──── no tool calls ──── END
  │
  has tool calls
  │
  ▼
tools_node (ToolNode)
  │
  └──────────────────► agent_node (loop)
```

The graph is built once at startup, compiled with the MongoDB checkpointer, and stored on `app.state.graph`. Every WebSocket session uses the same graph instance with a different `thread_id`.

```python
builder = StateGraph(AgentState)
builder.add_node("agent", agent_node)
builder.add_node("tools", ToolNode(ALL_TOOLS))
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", should_continue, ["tools", END])
builder.add_edge("tools", "agent")
return builder.compile(checkpointer=checkpointer)
```

`should_continue` routes to `"tools"` if the last message has `tool_calls`, otherwise to `END`.

### Tools

All tools use `InjectedState` to read file keys and user identity from agent state — the LLM supplies only semantic arguments (extracted contact fields, company name). This prevents hallucination of file keys, row IDs, and user identities.

---

**`extract_card_details(state)`** — sync

Reads `state["image_key"]`, fetches the bytes from R2, base64-encodes them, and calls `gpt-4o` with the image as a data URI. Uses `client.beta.chat.completions.parse` with a `_CardFields` Pydantic schema for structured output — the model cannot return malformed JSON. Returns `{name, phone, email, company}`.

---

**`check_duplicate(email, phone, state)`** — async

Queries Postgres for all contacts belonging to `state["user_id"]`. Normalises email (lowercase strip) and phone (digits only) before comparing. Returns `{is_duplicate: bool, existing_row: dict | None}`. Email match is tried first; if no email, phone is the fallback key.

---

**`log_contact_to_sheet(contact, state, tool_call_id)`** — async, uses `interrupt`

1. Calls `interrupt({"action": "confirm_contact", "contact": contact})` **before any write**. The graph pauses here; the runner sends `{ type: "interrupt", data: {...} }` to the browser.
2. On resume, receives `{"decision": "confirm"|"reject", "edits": {...}}`.
3. If rejected, returns a `ToolMessage` asking the user to re-upload.
4. If confirmed, merges any edits, calls `database.insert_contact`, and returns `Command(update={"current_row_id": contact_id, "messages": [...]})`.

The interrupt is placed as the **first action** in the tool, before any database write. LangGraph's resume mechanism re-executes the tool from the top (it does not resume mid-function), so placing side effects after the interrupt guarantees idempotency: a re-run after crash or timeout will re-prompt the user, not write a duplicate row.

---

**`send_email_alert(name, company, phone, email, state)`** — async

Looks up the user's `notification_email` from the MongoDB `users` collection via `state["user_id"]`. Calls `resend.Emails.send` via `asyncio.to_thread` (Resend SDK is sync). The contact fields passed here always come from the `log_contact_to_sheet` result, not the raw extraction — the system prompt enforces this — ensuring edited values are used, not pre-edit values.

---

**`store_voice_note(state, tool_call_id)`** — async, uses `interrupt`

1. Reads `state["current_row_id"]` (fails gracefully if None — no card logged yet).
2. Downloads audio from R2, calls `whisper-1` via `asyncio.to_thread`.
3. Calls `interrupt({"action": "confirm_transcript", "transcript": ..., "audio_url": ...})`.
4. On resume, applies any corrections to the transcript, calls `database.update_audio`.

The Whisper call happens before the interrupt so the user sees the actual transcript in the confirmation card. On resume the tool re-runs from the top, calling Whisper again. This double-call is acceptable in a prototype; a production system would cache the transcript result between the interrupt and resume.

---

**`enrich_company(company, state)`** — async

Calls GPT-4o with a `_CompanyInfo` Pydantic schema requesting `website` and `linkedin` URLs. The model is instructed not to fabricate URLs. On success, calls `database.update_enrichment` with `state["current_row_id"]`. Fails gracefully — any exception is caught and logged, and the tool returns `"enrichment skipped"` so the agent can proceed.

---

### MongoDB Checkpointer

`langgraph-checkpoint-mongodb==0.4.0` ships only the sync `MongoDBSaver`. It exposes async methods (`aput`/`aget`/`alist`) that LangGraph invokes via a thread pool, so it works correctly under the async `graph.astream` call. The checkpointer is built from a `pymongo.MongoClient` (not `AsyncMongoClient`) and stores snapshots in the `card_orchestrator` database, in collections managed by LangGraph internally (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`).

```python
client = MongoClient(mongodb_uri)
checkpointer = MongoDBSaver(client, db_name="card_orchestrator")
graph = build_graph(checkpointer)
```

Because `thread_id == session_id`, every WebSocket session has its own isolated checkpoint sequence. The `current_row_id` written in one session is invisible to other sessions. Interrupt state is also checkpointed, which is why `Command(resume=...)` sent in a later WebSocket message correctly resumes the paused graph.

### HITL Interrupt Mechanism

```
graph.astream(stream_input, config, stream_mode=["updates", "messages"])
  │
  ├── "messages" events → token by token text → ws.send_json({type:"token"})
  │
  └── "updates" events
        ├── payload has "__interrupt__" key
        │     → ws.send_json({type:"interrupt", data: interrupt_obj.value})
        │     → runner returns (interrupted=True), NOT sending "done"
        │
        └── payload has node name ("agent"|"tools")
              → ws.send_json({type:"tool", data:{name, status}})
```

The client receives `{ type: "interrupt" }`, renders `ConfirmCard`, and waits. On confirm, it sends `{ resume: { decision, edits } }` back over the same socket. The server reconstructs `Command(resume=incoming["resume"])` and calls `graph.astream` again with the same `thread_id`. LangGraph looks up the checkpoint, finds the pending interrupt, and resumes the tool from the top with the provided resume value.

---

## 4. API Reference

All REST endpoints except `/health` and `POST /api/waitlist` require a `Bearer <token>` in the `Authorization` header. The token is a Clerk-issued JWT.

### Health

```
GET /health
HEAD /health
→ 200 {"status": "ok"}
```

No auth. Used by uptime monitors and load balancers.

---

### User Setup

```
POST /api/users/setup
Authorization: Bearer <token>
Content-Type: application/json

{ "email": "user@example.com" }

→ 200 {
    "scan_count": 0,
    "notification_email": "user@example.com"
  }
```

Idempotent. Creates the user document if it does not exist; returns the existing document otherwise. Called on every login. Frontend uses the returned `scan_count` to populate the sidebar indicator. The `notification_email` defaults to the Clerk email on first call.

---

### Waitlist

```
POST /api/waitlist
Content-Type: application/json

{ "email": "user@example.com" }

→ 200 { "status": "added" }
```

No auth required. Idempotent — duplicate submissions are silently ignored via a MongoDB upsert with `$setOnInsert`.

---

### Contacts

```
GET /api/contacts
Authorization: Bearer <token>

→ 200 [
    {
      "id": "uuid",
      "name": "...",
      "phone": "...",
      "email": "...",
      "company": "...",
      "website": "...",
      "linkedin": "...",
      "audio_url": "...",
      "transcript": "...",
      "session_id": "...",
      "created_at": "2026-01-01T00:00:00Z"
    },
    ...
  ]
```

Returns all contacts belonging to the authenticated user, ordered by `created_at` descending.

```
GET /api/contacts/export
Authorization: Bearer <token>

→ 200 text/csv (Content-Disposition: attachment; filename=contacts.csv)
```

Returns the same contact set as a CSV download with columns: `name, phone, email, company, website, linkedin, audio_url, transcript, session_id, created_at`.

---

### Sessions

```
POST /api/sessions
Authorization: Bearer <token>
{ "title": "New session" }
→ 200 SessionOut

GET /api/sessions
Authorization: Bearer <token>
→ 200 [SessionOut, ...]

PATCH /api/sessions/{session_id}
Authorization: Bearer <token>
{ "title": "Renamed title" }
→ 200 SessionOut
→ 404 if session not found or not owned by user
→ 422 if title is empty

DELETE /api/sessions/{session_id}
Authorization: Bearer <token>
→ 204
→ 404 if session not found or not owned by user
```

`SessionOut`: `{ session_id, title, created_at, updated_at }`. All queries filter by `user_id` extracted from the JWT so users cannot access each other's sessions.

Delete cascades: the handler also calls `messages.delete_many({session_id})` to remove orphaned messages.

---

### Message History

```
GET /api/sessions/{session_id}/messages
Authorization: Bearer <token>

→ 200 [
    {
      "session_id": "...",
      "role": "user"|"assistant",
      "type": "text"|"image"|"audio",
      "content": "...",
      "media_url": "...",
      "created_at": "..."
    },
    ...
  ]
```

Returns messages for a session in chronological order. Verifies session ownership before querying.

---

### File Upload

```
POST /api/sessions/{session_id}/upload
Authorization: Bearer <token>
Content-Type: multipart/form-data

file=<binary>
kind=image|audio

→ 200 { "key": "session_id/kind/uuid-filename", "kind": "image"|"audio" }
```

Saves the file to Cloudflare R2. The key pattern is `{session_id}/{kind}/{uuid}-{original_filename}`. The key is returned to the client, which includes it in the next WebSocket message as `image_key` or `audio_key`. Raw bytes never enter the agent or any message payload.

---

### WebSocket

```
WS /ws/sessions/{session_id}?token=<jwt>
```

Auth via query param — browsers cannot set custom headers on WebSocket connections.

**Client → Server messages**:

```jsonc
// New turn with card image
{ "text": "...", "image_key": "session_id/image/uuid-card.jpg" }

// New turn with voice note
{ "text": "...", "audio_key": "session_id/audio/uuid-note.m4a" }

// Text-only turn
{ "text": "Hello" }

// Resume after interrupt
{ "resume": { "decision": "confirm", "edits": {} } }
{ "resume": { "decision": "reject" } }
```

**Server → Client events**:

```jsonc
// LLM text token (stream)
{ "type": "token", "data": "extracted" }

// Tool call started / completed
{ "type": "tool", "data": { "name": "extract_card_details", "status": "running" } }
{ "type": "tool", "data": { "name": "extract_card_details", "status": "done" } }

// HITL pause — awaiting resume
{ "type": "interrupt", "data": { "action": "confirm_contact", "contact": { "name": "...", "phone": "...", "email": "...", "company": "..." } } }
{ "type": "interrupt", "data": { "action": "confirm_transcript", "transcript": "...", "audio_url": "..." } }

// Turn complete
{ "type": "done", "data": {} }

// Free tier scan limit hit
{ "type": "limit_reached", "data": { "scan_count": 2 } }

// Server-side error
{ "type": "error", "data": "Internal server error" }
```

The server never sends `done` after an `interrupt` — the turn is considered in-flight until the resume completes and the graph reaches `END`.

---

## 5. Database Schema

### Neon Postgres — `contacts` table

```sql
CREATE TABLE contacts (
    id          TEXT PRIMARY KEY,           -- UUID generated by the backend on insert
    user_id     TEXT NOT NULL,              -- Clerk user_id; indexed; isolates data per user
    name        TEXT NOT NULL DEFAULT '',
    phone       TEXT DEFAULT '',
    email       TEXT DEFAULT '',
    company     TEXT DEFAULT '',
    website     TEXT DEFAULT '',            -- filled by enrich_company tool
    linkedin    TEXT DEFAULT '',            -- filled by enrich_company tool
    audio_url   TEXT DEFAULT '',            -- R2 public URL, filled by store_voice_note
    transcript  TEXT DEFAULT '',            -- Whisper output, filled by store_voice_note
    session_id  TEXT DEFAULT '',            -- which session logged this contact
    created_at  TIMESTAMPTZ
);

CREATE INDEX ON contacts (user_id);
```

Created at startup by `database.init_db()` via SQLAlchemy's `metadata.create_all`. Connection uses asyncpg with SSL required. The URL parser strips `sslmode=` query parameters (asyncpg does not accept them as URL params) and passes `ssl="require"` via `connect_args` instead.

**Deduplication logic** (`find_duplicate`): fetches all rows for the `user_id`, normalises email (lowercase + strip) and phone (digits only), and compares in Python. Email takes precedence; phone is the fallback if email is empty on either side.

---

### MongoDB Atlas — `card_orchestrator` database

**`sessions` collection**
```json
{
  "session_id": "uuid",
  "user_id": "clerk_user_id",
  "title": "New session",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

**`messages` collection**
```json
{
  "session_id": "uuid",
  "role": "user | assistant",
  "type": "text | image | audio",
  "content": "string | null",
  "media_url": "R2 public URL | null",
  "created_at": "ISODate"
}
```
Messages are written only for user turns (the WebSocket handler calls `save_message` before invoking the graph). Agent turns are reconstructed from the LangGraph checkpoint's `messages` field and are not stored separately.

**`users` collection**
```json
{
  "user_id": "clerk_user_id",
  "email": "user@example.com",
  "scan_count": 0,
  "notification_email": "user@example.com",
  "created_at": "ISODate"
}
```
`scan_count` is incremented atomically with `$inc`. The free tier allows 2 scans.

**`waitlist` collection**
```json
{
  "email": "user@example.com",
  "created_at": "ISODate"
}
```
Upserted with `$setOnInsert`, so re-submissions for the same email are no-ops.

**LangGraph checkpointer collections** (managed by `langgraph-checkpoint-mongodb`)

- `checkpoints` — checkpoint metadata (thread_id, checkpoint_id, parent_id, timestamps)
- `checkpoint_blobs` — serialised state blobs (the actual `AgentState` snapshots)
- `checkpoint_writes` — pending writes from interrupted nodes

These are written and read exclusively by the `MongoDBSaver`. The `current_row_id` from `AgentState` is stored here, which is what allows a voice note sent in a new WebSocket connection to find the contact logged in a previous connection — as long as `thread_id == session_id` is consistent.

---

## 6. Authentication & Security

### Clerk JWT Verification

Clerk issues RS256 JWTs. The backend verifies them without using Clerk's SDK:

1. Decode the token header (without verifying) to extract the `kid` (key ID).
2. Fetch the JWKS from `https://api.clerk.com/v1/jwks` using the `CLERK_SECRET_KEY` to authenticate the fetch. Cache the key list for 1 hour.
3. Find the matching key by `kid`. If the key is missing, force one JWKS refresh (handles key rotation).
4. Reconstruct the RSA public key with `PyJWT`'s `RSAAlgorithm.from_jwk`.
5. Verify the JWT signature and expiry with `pyjwt.decode(..., algorithms=["RS256"])`.
6. Return the `sub` claim as `user_id`.

For REST endpoints, `get_current_user` is a FastAPI `Depends` that reads the `Authorization: Bearer <token>` header.

For WebSocket connections, browsers cannot set custom headers, so the token is passed as a `?token=` query parameter. The WS handler calls `verify_token` directly before accepting any messages.

### User Isolation

Every data access is scoped to the verified `user_id`:

- **Postgres**: every query includes `WHERE user_id = :user_id`. Users cannot read or modify each other's contacts.
- **MongoDB sessions/messages**: `get_session` always queries `{session_id, user_id}` together, preventing session ID guessing attacks. `list_sessions`, `rename_session`, and `delete_session` all filter by `user_id`.
- **R2 file keys**: structured as `{session_id}/{kind}/{uuid}-{filename}`. Session ownership is verified before upload. The `session_id` prefix makes cross-user key guessing infeasible.
- **Agent state**: `user_id` is injected from the verified JWT into `AgentState` on every WebSocket turn. Tools read it from `InjectedState`, not from LLM arguments. The LLM cannot impersonate a different user.

### Why Files Are Never Passed Through the LLM

The upload flow separates file bytes from the agent entirely:

```
Browser → POST /upload → R2 (bytes stored) → returns key (string)
Browser → WS send {image_key: key} → agent state
Tool (extract_card_details) → reads key from state → fetches bytes from R2 → base64 → GPT-4o
```

Base64-encoding a card image is ~100KB. Passing this in every agent message, or through tool arguments, would be extremely expensive and would pollute the conversation history with binary data. The key is a short opaque string (~60 chars) that the LLM never needs to interpret.

### Secrets

The backend reads all secrets from environment variables. The only secret that reaches the frontend bundle is `VITE_CLERK_PUBLISHABLE_KEY`, which is intentionally public (it identifies the Clerk application, not a credential).

---

## 7. Software Engineering Techniques

### Agentic AI Patterns

**Tool-calling loop**: The LangGraph `agent → tools → agent` cycle implements the ReAct pattern. The model reasons about which tool to call next based on prior tool results in the conversation history. The system prompt encodes the intended workflow, but the model is free to deviate — for example, if extraction fails, it can ask the user to re-upload without the system needing a hard-coded fallback branch.

**State machine with checkpointing**: `AgentState` is the single source of truth for one session's orchestration state. Each node produces a partial update; LangGraph applies the `add_messages` reducer for `messages` and a last-write-wins merge for scalar fields. The MongoDB checkpointer saves a snapshot after every node execution, making the agent restartable across process restarts and WebSocket reconnections.

**Human-in-the-loop interrupts**: `interrupt(value)` suspends the graph mid-tool. The value is serialised into the checkpoint. On resume, `Command(resume=value)` is passed as the stream input; LangGraph looks up the pending interrupt in the checkpoint and calls the tool again with the resume value available from `interrupt()`'s return. This is used twice: before writing the contact (user confirms/edits extracted fields) and before writing the transcript (user confirms/edits Whisper output).

### Async Programming

**FastAPI async endpoints**: All endpoints are `async def`. I/O-bound operations (MongoDB, Postgres, R2) are all awaited without blocking the event loop.

**asyncpg**: Direct PostgreSQL driver without connection pooling overhead. The `create_async_engine` is configured with `connect_args` instead of a URL-encoded connection string, which avoids two known issues: asyncpg rejecting `sslmode` as a URL query parameter, and `urlparse` mishandling special characters in passwords.

**WebSocket streaming**: `graph.astream(stream_input, config, stream_mode=["updates", "messages"])` is an async generator. The runner iterates it with `async for`, forwarding each event to the client immediately. This means the user sees tokens and tool status updates in real time without waiting for the full agent turn to complete.

**Sync libraries in async context**: OpenAI SDK, Whisper, Resend, and boto3 are all synchronous. They are wrapped with `asyncio.to_thread()` to avoid blocking the event loop.

### State Management

**LangGraph AgentState as single source of truth**: All inter-tool communication happens through state, not through tool return values that the LLM has to parse. `current_row_id` is the clearest example — it is written as a `Command(update=...)` return from `log_contact_to_sheet` and read directly from `state["current_row_id"]` in `store_voice_note`. The LLM never needs to know the row ID; it just calls the right tool.

**MongoDB checkpointer for cross-turn persistence**: A voice note sent in a new WebSocket connection (potentially minutes or hours later) can still find the correct contact because the checkpointer replays state from the saved snapshot when the graph is invoked with the same `thread_id`.

**React state scoped to user session**: `App.jsx` holds global state (`sessions`, `scanCount`, `activeTab`). `ChatWindow` holds per-session state (`messages`, `streaming`, `interrupt`, `wsState`). Switching sessions mounts a fresh `ChatWindow` (via `key={activeId}`) which opens a new WebSocket, loads its own message history, and keeps no cross-contamination from other sessions.

### Event-Driven Architecture

The WebSocket protocol defines five event types flowing server-to-client:

| Event | When | Frontend action |
|---|---|---|
| `token` | LLM produces a text chunk | Append to streaming accumulator |
| `tool` | Tool starts or finishes | Add/update tool bubble in thread |
| `interrupt` | Graph pauses for HITL | Show ConfirmCard component |
| `done` | Graph reaches END | Flush stream, unblock composer |
| `limit_reached` | Scan count ≥ 2 | Show limit modal, disable uploads |

The `handleEvent` function in `ChatWindow` is a pure switch over these types. It only touches refs and stable state setters, so it can be captured once in the WebSocket effect closure without stale closure issues.

### Defensive Programming

**Deduplication**: Email and phone are normalised before comparison. Normalisation strips whitespace, lowercases email, and removes all non-digit characters from phone. This handles common variations: `+1 (415) 555-0182` and `4155550182` match. The check runs before the HITL interrupt and before any write — a duplicate is reported and the flow ends there.

**Idempotent waitlist upsert**: `$setOnInsert` means the MongoDB upsert only writes fields when creating a new document. If the same email is submitted twice, the second call is a no-op at the database level.

**Interrupt before side effects**: `log_contact_to_sheet` calls `interrupt()` as its very first statement. LangGraph's resume mechanism re-executes the tool from the top. Since the write happens after the interrupt, a crash between interrupt and write would result in the user being prompted again on the next attempt — not a duplicate write.

**Scan limit gate**: The WS handler checks `get_scan_count` before invoking the graph. It increments only after `run_and_stream` returns. The `is_resume` flag prevents resume turns and voice note turns from being counted as scans.

### Security Patterns

**JWT verification with RSA public key**: No shared secret. The backend fetches Clerk's public keys and verifies the signature locally. The 1-hour JWKS cache with forced refresh on unknown `kid` handles key rotation without manual intervention.

**User-scoped database queries**: Described in §6. Every read and write includes the `user_id` from the verified JWT, not from the client.

**Secrets never in the frontend bundle**: `OPENAI_API_KEY`, `MONGODB_URI`, `RESEND_API_KEY`, `CLERK_SECRET_KEY`, and R2 credentials exist only as server-side environment variables. The frontend bundle contains only `VITE_CLERK_PUBLISHABLE_KEY` (public by design) and the backend URL.

### React Patterns

**StrictMode-safe WebSocket**: React StrictMode intentionally mounts/unmounts/remounts components in development. The WebSocket effect uses an `ignore` flag: if the effect is cleaned up before the async token fetch resolves, `ignore = true` prevents the socket from being created for the discarded mount. The cleanup calls `closeWhenReady()` instead of `close()`: if the socket is still `CONNECTING`, it attaches a one-time `open` listener that immediately closes, avoiding a browser warning about closing an unestablished connection.

**Pre-connection send queue**: `openSocket` returns a wrapper with a `send(payload)` method. If called while `readyState === WebSocket.CONNECTING`, the frame is pushed to an in-memory queue and flushed on the `onopen` event. This lets the `send()` path in `ChatWindow.send()` call the socket without waiting for the connection to be established.

**StrictMode init guard**: `App.jsx` uses a `didInit` ref to prevent the initial `useEffect` from running twice in development. Refs survive the artificial unmount/remount cycle that StrictMode performs, so the second invocation sees `didInit.current === true` and exits immediately.

### Bugs Fixed During Development

**State propagation bug — post-edit contact fields in email alert**: The original prompt instructed the agent to pass name/company to `send_email_alert` from `extract_card_details`. If the user edited the name in the confirmation step, the email alert still used the pre-edit name. Fixed by updating the system prompt to explicitly instruct the agent to use the `log_contact_to_sheet` tool result for the email alert arguments — that result contains the final merged contact after edits are applied.

**asyncpg SSL and special-character password**: asyncpg does not accept `sslmode=require` as a URL query parameter (it raises `invalid connection option` at runtime). Additionally, `urlparse` misparses passwords containing special characters like `@` or `%`. Fixed by using `urlparse` + `unquote` to extract host/port/user/password/database separately and passing them as a `connect_args` dict with `ssl="require"`.

**Session deletion leaving orphaned messages**: `delete_session` originally only deleted from the `sessions` collection. The messages collection had no foreign key constraint (MongoDB), so messages for the deleted session stayed indefinitely. Fixed by adding `messages.delete_many({session_id: session_id})` gated on `deleted_count > 0` in the same function.

**WebSocket send race during fast users**: A user who submits before the WebSocket handshake completes would have their message silently dropped. Fixed with the queue in `openSocket` — frames sent while `CONNECTING` are buffered and flushed on `onopen`.

---

## 8. Key Engineering Decisions

**One agent, many tools — not a fixed node chain**: A tool-calling agent lets the LLM decide the execution path. The `check_duplicate` tool can short-circuit the flow (no write, no email) based on its result, without the developer needing to wire conditional edges. New tools can be added to `ALL_TOOLS` without changing the graph topology. A fixed pipeline would require an edge for every branch — the agent topology scales naturally.

**WebSocket instead of REST polling**: The card processing flow involves a sequence of events — extraction tokens, tool status updates, an interrupt pause, resume, more tokens — that are impossible to represent cleanly with polling. SSE was considered but lacks bidirectionality: the client needs to send the resume payload after an interrupt. A single long-lived WebSocket connection handles both directions cleanly.

**Neon Postgres for contacts**: Contacts are structured, relational, user-scoped records that benefit from a typed schema, indexed queries, and CSV export. SQLAlchemy ORM + asyncpg gives async access with type safety. Google Sheets was the v1 target but is unsuitable for user-level data isolation, programmatic CSV export, and the deduplication query pattern.

**MongoDB for sessions and the checkpointer**: Session documents and message documents are variable-length, schema-light records that fit MongoDB's document model well. More importantly, `langgraph-checkpoint-mongodb` ships a ready-made MongoDB checkpointer; using the same database for both the UI data and the LangGraph state avoids a third managed service.

**HITL covers both contact details and transcript**: Both confirmation steps serve the same purpose: the user is the ground truth for what the card says (OCR can misread a character) and what was said in a voice note (Whisper can mishear names and technical terms). Confirming before writing also catches cases where the model extracts the wrong field into the wrong slot.

---

## 9. Legacy Integrations

`backend/app/services/whatsapp.py` and `backend/app/services/sheets.py` are retained as reference implementations but are not imported or invoked anywhere in the active codebase.

**`whatsapp.py`** — Meta WhatsApp Cloud API. Sends a utility template message to a configured recipient phone number using the Graph API. Template names: `new_card_logged` (custom, with name/company parameters) with a fallback to `hello_world` (no parameters, useful while awaiting template approval). Replaced by Resend email in v2 to eliminate the WhatsApp template approval bottleneck and the per-number registration requirement.

**`sheets.py`** — Google Sheets via gspread. Would have stored contacts as rows in a Sheet, with columns `Name | Phone | Email | Company | Website | LinkedIn | Audio URL | Transcript | Session ID | Created At`. Replaced by Neon Postgres in v2 for per-user isolation, query capability, and CSV export.

Both files are preserved to demonstrate the range of integrations the system was designed to support and to document the evolution of the data layer.

---

## 10. Deployment

### Infrastructure

```
Internet
   │
   ├── cardsync.dev / www.cardsync.dev → Vercel (frontend, static)
   │
   └── api.cardsync.dev → AWS EC2 t3.micro (Mumbai, ap-south-1)
              │
              ├── Nginx (reverse proxy, ports 80/443)
              │     ├── SSL: Let's Encrypt via certbot (auto-renews)
              │     ├── HTTP → HTTPS redirect (handled by certbot)
              │     └── WebSocket upgrade headers for /ws/* routes
              │
              └── Docker container
                    ├── python:3.12-slim base
                    ├── apt install ca-certificates
                    ├── pip install -r requirements.txt
                    └── uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### EC2 Instance

- **AMI:** Ubuntu Server 24.04 LTS (ami-006f82a1d5a27da54)
- **Instance type:** t3.micro (free tier eligible in ap-south-1)
- **Security group inbound rules:** SSH/22, HTTP/80, HTTPS/443, Custom TCP/8000 — all from 0.0.0.0/0
- **SSH:** RSA key pair (.pem), connected via WSL (`chmod 400` on the key file)

> **Note:** Ubuntu 26.04 was initially used but abandoned — it uses systemd socket activation for SSH (`ssh.socket`) which is incompatible with most SSH clients. Ubuntu 24.04 LTS does not have this issue.

### Initial Server Setup

```bash
# SSH in from WSL
chmod 400 ~/.ssh/cardsync-key.pem
ssh -i ~/.ssh/cardsync-key.pem ubuntu@15.206.151.14

# Install Docker
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io git curl
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ubuntu
exit  # log out so group change takes effect

# SSH back in, clone repo, create .env
git clone https://github.com/baibhavbaidya/cardsync.git
cd cardsync/backend
nano .env  # paste all env vars
```

### Docker Build and Run

```bash
docker build -t cardsync-backend .
docker run -d --name cardsync --env-file .env -p 8000:8000 --restart always cardsync-backend
docker logs cardsync
# INFO: Application startup complete.
```

> **Important:** `docker restart` does NOT re-read the `.env` file. To apply env var changes, you must stop and remove the container then re-run:
> ```bash
> docker stop cardsync && docker rm cardsync
> docker run -d --name cardsync --env-file .env -p 8000:8000 --restart always cardsync-backend
> ```

### Nginx and SSL

```bash
sudo apt install -y nginx certbot python3-certbot-nginx

# Create site config
sudo nano /etc/nginx/sites-available/cardsync
```

Config:
```nginx
server {
    listen 80;
    server_name api.cardsync.dev;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/cardsync /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Get SSL certificate (certbot modifies the Nginx config automatically)
sudo certbot --nginx -d api.cardsync.dev
```

The `proxy_read_timeout 86400` (24 hours) is required for long-running WebSocket connections — without it Nginx closes idle WS connections after 60 seconds.

The `Upgrade` and `Connection` headers are required for WebSocket proxying. Without them, Nginx downgrades the connection to HTTP and the WS handshake fails.

### Domain Configuration (name.com + Vercel)

**DNS records added in name.com:**

| Type  | Host            | Value                                  | Purpose                    |
|-------|-----------------|----------------------------------------|----------------------------|
| A     | `@`             | `216.198.79.1`                         | cardsync.dev → Vercel      |
| CNAME | `www`           | `f20b2067a8fc61f7.vercel-dns-017.com.` | www.cardsync.dev → Vercel  |
| A     | `api`           | `15.206.151.14`                        | api.cardsync.dev → EC2     |
| TXT   | `resend._domainkey` | (Resend DKIM value)                | Email authentication       |
| MX    | `send`          | `feedback-smtp.*.amazonses.com`        | Email sending              |
| TXT   | `send`          | `v=spf1 include:*.nses.com ~all`       | SPF record                 |
| TXT   | `_dmarc`        | `v=DMARC1; p=none;`                    | DMARC policy               |

**Vercel project settings:**
- `www.cardsync.dev` set as primary domain (Production)
- `cardsync.dev` set to 308 redirect → `www.cardsync.dev`
- `cardsync-azure.vercel.app` set to 308 redirect → `www.cardsync.dev`

**CORS:** The backend `CORS_ORIGINS` env var must include all frontend origins:
```
CORS_ORIGINS=https://cardsync.dev,https://www.cardsync.dev,https://cardsync-azure.vercel.app
```

### Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PORT=8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
```

`ca-certificates` is explicitly installed because `python:3.12-slim` strips the system certificate store. Without it, outbound HTTPS connections to Resend, Clerk's JWKS endpoint, and Cloudflare R2 fail with `SSL: CERTIFICATE_VERIFY_FAILED`.

### Frontend

Deployed to Vercel. The Vite build produces a static bundle. Environment variables set in Vercel project settings:

```
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
VITE_API_BASE_URL=https://api.cardsync.dev
VITE_WS_BASE_URL=wss://api.cardsync.dev
```

### Ongoing Maintenance

Update backend after a code push:
```bash
cd ~/cardsync
git pull
cd backend
docker stop cardsync && docker rm cardsync
docker build -t cardsync-backend .
docker run -d --name cardsync --env-file .env -p 8000:8000 --restart always cardsync-backend
```

Check container logs:
```bash
docker logs cardsync --tail 50 -f
```

SSL certificate renewal is automatic via certbot's systemd timer. Manual renewal if needed:
```bash
sudo certbot renew
```

---

## 11. Local Development Setup

### Prerequisites

- Python 3.12
- Node.js 18+
- A `.env` file in `backend/` populated from `.env.example`
- A `.env` file in `frontend/` populated from `.env.example`

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # fill in all values
uvicorn app.main:app --reload --port 8000
```

On startup:
1. `mongo.connect()` — establishes the MongoDB Atlas connection
2. `database.init_db()` — creates the `contacts` table if it does not exist
3. `graph_lifespan()` — compiles the LangGraph graph with the MongoDB checkpointer

The backend is now available at `http://localhost:8000`. Interactive API docs at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env               # fill in VITE_CLERK_PUBLISHABLE_KEY and URLs
npm run dev
```

The Vite dev server starts at `http://localhost:5173` by default.

For local development, set:
```
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000
```

### Agent Smoke Test (no UI)

```bash
cd backend
python -m app.agent.smoke
```

Feeds a sample card image key through the full agent loop and prints each tool call. Requires all backend environment variables to be set, including `OPENAI_API_KEY`, `MONGODB_URI`, and R2 credentials.

### Required Environment Variables

**Backend** (`backend/.env`):

```
OPENAI_API_KEY=          # GPT-4o and Whisper
MONGODB_URI=             # MongoDB Atlas connection string (mongodb+srv://...)
DATABASE_URL=            # Neon Postgres connection string (postgresql://...)
CLERK_SECRET_KEY=        # Clerk backend secret for JWKS fetch
RESEND_API_KEY=          # Resend transactional email
R2_ACCOUNT_ID=           # Cloudflare account ID
R2_ACCESS_KEY_ID=        # R2 API token access key
R2_SECRET_ACCESS_KEY=    # R2 API token secret
R2_BUCKET=               # R2 bucket name
R2_PUBLIC_URL=           # Public base URL for the R2 bucket
CORS_ORIGINS=            # Comma-separated allowed origins (e.g. http://localhost:5173)
```

**Frontend** (`frontend/.env`):

```
VITE_CLERK_PUBLISHABLE_KEY=   # Clerk publishable key (starts with pk_)
VITE_API_BASE_URL=            # Backend REST base URL
VITE_WS_BASE_URL=             # Backend WebSocket base URL
```