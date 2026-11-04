# Print247 Chatbot

Sales-support chatbot for [Print247](https://print247.us) website chats. It answers product and process questions from a verified markdown knowledge base, drives visitors toward a complete quote handoff, and refuses unsafe replies before they are sent.

**Package:** `print247-chatbot` · **Version:** 0.1.0 · **Python:** ≥ 3.11

---

## Goals

- Ground every factual answer in the `kb/` knowledge base (no invented prices, policies, sizes, or certifications).
- Rotate nine sales personas (one sticky persona per conversation).
- Collect quote fields (product family, use case, size, quantity, style / material / finish, contact) and hand off when ready.
- Capture name / email / phone from informal intros in one turn (including forms like “hey Bilal here”) and acknowledge everything shared.
- Reply in the visitor’s language via a dynamic LLM inbound/outbound pass (reasoning stays English-internal; no per-language word lists).
- Run deterministic guards on every draft reply.
- Support local chat, a browser UI, and a Zoho SalesIQ-compatible webhook.

**Out of scope:** model fine-tuning, ERP pricing in chat, replacing the separate QA dashboard.

Design history and rollout decisions live in [`PLAN.md`](./PLAN.md) and [`PLAN_V2.md`](./PLAN_V2.md).

---

## Architecture at a glance

```
Visitor (UI / SalesIQ / CLI)
        │
        ▼
   FastAPI service          bot/service.py
        │
        ▼
   Orchestrator             bot/orchestrator.py
        │
        ├── Language        bot/reply_language.py, visitor_language.py
        │                     (detect → English gloss in; translate reply out)
        ├── State machine   bot/state.py          (fields, goals, handoff, contact extract)
        ├── Spelling / PII  bot/spelling.py, pii.py
        ├── Vision          bot/vision.py         (optional image → fields)
        ├── KB retrieval    bot/kb.py             (BM25 over markdown)
        ├── Catalogue       bot/capability.py     (registry → primer)
        ├── Composer        bot/composer.py       (fake heuristic | live LLM)
        └── Guards          bot/guards.py         (block / warn / rewrite)
        │
        ▼
   Store                    bot/store.py          (SQLite or Postgres)
```

Live turns use a deterministic **catalogue primer** (from the capability registry) plus family-filtered KB chunks. `BOT_CONTEXT` is locked to `catalogue` in code (decision D-12). Session language sticks on `flags.language`; short catalogue answers do not flip it back to English.

---

## Tech stack

| Layer | Choice |
| --- | --- |
| Runtime | Python ≥ 3.11 |
| HTTP | FastAPI + Uvicorn |
| LLM | OpenAI-compatible API (default text: `gpt-5-nano`, vision: `gpt-4o-mini`) |
| KB search | In-process BM25 over chunked markdown (no vector DB) |
| State | SQLite locally; Postgres when `DATABASE_URL` / `POSTGRES_URL` / `BOT_DATABASE_URL` is set |
| Attachments | Local `data/uploads`, or Vercel Blob when a blob token is set |
| Fuzzy / spelling | rapidfuzz, pyspellchecker |
| Deploy | Vercel (`main.py` exports the FastAPI app, `maxDuration: 60`) |
| Tests | pytest (~347 tests) |

Anthropic is never used. Paid LLM calls require explicit spend gates (`BOT_ALLOW_LIVE=1` + API key + non-`fake` mode).

---

## Repository layout

```
chatbot/
├── main.py                 # Vercel entry — exports FastAPI `app`
├── pyproject.toml
├── requirements.txt
├── vercel.json
├── PLAN.md / PLAN_V2.md    # Status audit and v2 shopkeeper design
├── bot/                    # Application package
│   ├── config.py           # Env loading, modes, paths, spend gates
│   ├── service.py          # FastAPI: UI APIs, SalesIQ webhook, health
│   ├── cli.py              # ingest, capability, chat, serve, probe, …
│   ├── orchestrator.py     # End-to-end turn pipeline
│   ├── state.py            # Goal / field machine + contact extract
│   ├── composer.py         # Heuristic + live prompt / turn
│   ├── guards.py           # Deterministic reply checks
│   ├── reply_language.py   # LLM inbound gloss + outbound translate
│   ├── visitor_language.py # Session language helpers (no word lists)
│   ├── capability.py       # Capability registry + catalogue primer
│   ├── kb.py               # Markdown ingest, chunking, BM25
│   ├── canon.py            # Canonical facts + sign-off report
│   ├── personas.py         # Nine fixed sales personas
│   ├── llm.py              # OpenAI client, JSON schema, cost caps
│   ├── store.py            # Conversation / event persistence
│   ├── attachments.py      # Image validate / save
│   ├── vision.py           # Multimodal field extraction
│   ├── spelling.py         # Visitor-text normalisation
│   ├── pii.py              # Email / phone mask before compose LLM
│   ├── golden.py           # Golden examples from judged chats
│   ├── replay.py           # Offline historical replay
│   └── probe.py            # Phase 4 grounding probe (paid)
├── web/                    # Browser chat UI + persona avatars (no build step)
├── kb/                     # Verified facts, products, materials, policies, capabilities
├── seed/                   # Cold-start primer, KB index, golden.jsonl
├── scripts/
│   └── vercel_prepare.py   # Pre-deploy: copy kb + seed artifacts
├── tools/                  # Registry builders, vocabulary helpers
└── tests/                  # Pytest suite
```

Runtime dirs (gitignored): `data/` (sqlite, uploads, copied seed files), `out/` (reports).

---

## Knowledge base

Verified markdown under `kb/`:

| Folder | Role |
| --- | --- |
| `kb/products/` | Product families (boxes, pouches/mylar, labels, print products, …) |
| `kb/facts/` | MOQ, turnaround, samples, payments, contact, quote flow, … |
| `kb/materials/` | Materials and finishes by family |
| `kb/policies/` | Shipping, refunds, privacy, terms |
| `kb/capabilities/` | Capability registry, compliance allowlist, sign-off packet |

**Rules** (see [`kb/README.md`](./kb/README.md)):

- One concept per file; YAML frontmatter (`id`, `title`, `category`, `source`, `status`, `last_reviewed`).
- A fact without a source does not belong in the KB.
- Never invent price, policy, certification, or delivery date — hand off if unverified.
- “Retraining” = edit a file and re-run ingest (no fine-tuning).

---

## Personas

One persona is assigned per conversation (round-robin via an atomic store counter) and stays for the whole chat:

| Name | Email |
| --- | --- |
| Alex Kane | alex.kane@print247.us |
| Frank Castle | frank.castle@print247.us |
| Jessica Joe | jessica.joe@print247.us |
| Max Carter | max.carter@print247.us |
| Harry Brook | harry.brook@print247.us |
| Ethan Wilson | ethan.wilson@print247.us |
| Paul Smith | paul.smith@print247.us |
| Brian Tylar | briantylar@print247.us |
| Hazel Grace | hazel.grace@print247.us |

Identity policy: the persona is held naturally; the bot does not volunteer that it is AI. On an explicit identity question it discloses honestly and pivots back to helping.

---

## Operating modes

| `BOT_MODE` | Behaviour |
| --- | --- |
| `fake` (default) | Heuristic composer only — **no LLM spend** |
| `live` | Real LLM replies when `BOT_ALLOW_LIVE=1` and `BOT_LLM_API_KEY` are set |
| `dry_run` | Compose with LLM but return empty visitor replies on the webhook |
| `shadow` | Same pattern for shadow evaluation |

`Config.real_llm_enabled` is false in `fake`; otherwise requires `allow_live` and a non-empty API key.

---

## Prerequisites

- Python 3.11+
- OpenAI-compatible API key (only for live / probe / `llm-check`)
- Optional: Postgres URL for durable state; Vercel Blob token for durable uploads
- Optional: `cryptography` for SalesIQ RSA signature verification

---

## Install

This package is typically imported as `chatbot.bot.*`. Run CLI and tests from the **parent** of the `chatbot/` folder (e.g. `d:\Task-3-Chat`) so that path is on `PYTHONPATH`.

```bash
cd d:\Task-3-Chat
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
# source .venv/bin/activate

pip install -r chatbot/requirements.txt

# Optional — SalesIQ webhook signature verify
# pip install cryptography
```

Create `chatbot/.env` (gitignored). Example:

```env
BOT_MODE=fake
BOT_ALLOW_LIVE=0
BOT_LLM_API_KEY=
BOT_LLM_MODEL=gpt-5-nano
BOT_VISION_MODEL=gpt-4o-mini
BOT_LLM_BASE_URL=https://api.openai.com/v1
BOT_TIMEOUT_S=6
BOT_MAX_TURNS=12
BOT_TOP_K=6
BOT_UI=1
BOT_ARCH=v2
# BOT_HANDOFF_OPERATOR=johnhenry.it@print247.us
# DATABASE_URL=
# BLOB_READ_WRITE_TOKEN=
```

---

## Quick start

### 1. Build the KB index and catalogue primer

```bash
python -m chatbot.bot.cli ingest
python -m chatbot.bot.cli capability
python -m chatbot.bot.cli signoff
```

### 2. Interactive CLI chat (fake mode by default)

```bash
python -m chatbot.bot.cli chat
```

One-shot message:

```bash
python -m chatbot.bot.cli ask --conversation-id test-1 --start --text "Do you have a minimum order?"
```

### 3. Browser UI

```bash
python -m chatbot.bot.cli serve --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/). The UI calls `POST /api/start` and `POST /api/chat` (text and optional image).

Equivalent:

```bash
uvicorn chatbot.bot.service:app --host 127.0.0.1 --port 8000
```

### 4. Live connectivity check (paid)

```env
BOT_MODE=live
BOT_ALLOW_LIVE=1
BOT_LLM_API_KEY=sk-...
```

```bash
python -m chatbot.bot.cli llm-check
```

---

## CLI reference

| Command | Purpose |
| --- | --- |
| `ingest` | Build BM25 index → `data/kb_index.json`; write catalogue primer |
| `capability` | Validate registry, primer token budget, drift (no LLM) |
| `signoff` | List canonical facts still needing sales sign-off |
| `llm-check` | Tiny paid ping to verify key + model |
| `golden` | Build golden examples from judged chats |
| `replay` | Replay historical chats through the pipeline (fake; no API) |
| `ask` | Send one message (`--text`, optional `--start`) |
| `chat` | Interactive local chat |
| `probe` | Phase 4 grounding probe (paid; `--stage`, `--max-usd`) |
| `transcript` | Print conversations from a sqlite DB |
| `serve` | Run FastAPI (UI + webhook) |

Examples:

```bash
python -m chatbot.bot.cli golden
python -m chatbot.bot.cli replay --limit 300
python -m chatbot.bot.cli probe --stage all --max-usd 1.90
python -m chatbot.bot.cli transcript --db chatbot/out/replay_<stamp>.sqlite3 --limit 3
```

---

## HTTP API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness / config summary |
| `GET` | `/` | Local chat UI (when `BOT_UI` is on) |
| `GET` | `/signoff` | Sign-off report JSON |
| `GET` | `/avatars/{name}` | Persona avatar SVG |
| `POST` | `/api/start` | Start conversation → greeting + persona |
| `POST` | `/api/chat` | Turn: `{ "conversation_id", "text"? , "image_base64"? }` |
| `POST` | `/salesiq/webhook` | Zoho SalesIQ webhook (trigger / message / close / failure) |

Attachments: JPEG, PNG, WebP, GIF up to `BOT_ATTACHMENT_MAX_BYTES` (default 8 MB).

---

## Chat turn flow

1. **Start** — assign persona → heuristic greeting (ask product) → guard → persist.
2. **Handle** — load state; optional image save + vision enrichment.
3. **Language (inbound)** — detect visitor language; keep an English gloss for extract / spelling / guards. Contact fields are also read from the **raw** visitor text so email/phone survive inbound masking.
4. **Extract / apply** — quote fields plus `extract_contact_fields` (name intros such as “I am…”, “hey NAME here”, “this is…”, plus email and phone together).
5. **Handoff reasons** — human requested, quote complete, complex / stalled, contact declined, or `max_turns`.
6. **Retrieve** — BM25 top-K chunks; catalogue path uses family-filtered prompt context + primer.
7. **Compose** — `fake` → heuristic; `live` → LLM with primer, facts, chunks, goldens, goal (PII masked). Multi-contact intros ack with “I've got everything you shared.”
8. **Guard** — block → one rewrite attempt or fallback.
9. **Language (outbound)** — translate the English reply into the session language when needed; then persist state + events.

Guards cover invented prices, rush dates, AI self-claim / denial, unsanctioned dimensions, config↔prose reconciliation, Tier B claims, repeated asks, answer-first behaviour, and more.

---

## Configuration

Source of truth: [`bot/config.py`](./bot/config.py). `load_dotenv()` reads `chatbot/.env` with `setdefault` (existing process env wins).

| Variable | Default | Notes |
| --- | --- | --- |
| `BOT_MODE` | `fake` | `fake` \| `live` \| `dry_run` \| `shadow` |
| `BOT_ALLOW_LIVE` | off | Required for any paid LLM call |
| `BOT_LLM_MODEL` | `gpt-5-nano` | Text model |
| `BOT_VISION_MODEL` | `gpt-4o-mini` | Image analysis |
| `BOT_LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible |
| `BOT_LLM_API_KEY` | empty | |
| `BOT_TIMEOUT_S` | `6` | Per-call timeout |
| `BOT_MAX_LLM_CALLS` | `0` | `0` = unlimited per process |
| `BOT_MAX_TURNS` | `12` | Then hand off |
| `BOT_TOP_K` | `6` | BM25 retrieval depth |
| `BOT_ATTACHMENT_MAX_BYTES` | `8388608` | 8 MB |
| `BOT_CONTEXT` | *(ignored)* | Code forces `catalogue` |
| `BOT_ARCH` | `v2` | `v1` \| `v2` |
| `BOT_KB_DIR` | bundled `kb/` | |
| `BOT_DATA_DIR` | `data/` | On Vercel: `/tmp/chatbot-data` |
| `BOT_OUT_DIR` | `out/` | On Vercel: `/tmp/chatbot-out` |
| `DATABASE_URL` / `POSTGRES_URL` / `BOT_DATABASE_URL` | empty | Postgres if set |
| `BLOB_READ_WRITE_TOKEN` / `BOT_BLOB_READ_WRITE_TOKEN` | empty | Vercel Blob |
| `BOT_UI` | on | Serve browser UI |
| `BOT_SALESIQ_PUBLIC_KEY` | empty | PEM for webhook verify |
| `BOT_ALLOW_UNVERIFIED` | off | Allow missing / bad signatures |
| `BOT_FORWARD_ON_HANDOFF` | off | Forward to operator on handoff |
| `BOT_HANDOFF_OPERATOR` | `johnhenry.it@print247.us` | |
| `VERCEL` | — | Set by platform → `/tmp` data/out |

---

## Deployment (Vercel)

- Entry: [`main.py`](./main.py) → `from bot.service import app`
- [`vercel.json`](./vercel.json): function `main.py` with `maxDuration: 60`
- Build: `python scripts/vercel_prepare.py` (from `pyproject.toml` `[tool.vercel.scripts]`)
  - Copies parent `../kb` → `./kb` when present
  - Seeds `catalogue_primer.txt`, `kb_index.json`, `golden.jsonl` into `seed/`

**Production durability:** use Postgres (`DATABASE_URL`) and Vercel Blob for uploads. SQLite / files under `/tmp` on Vercel are ephemeral.

---

## Testing & QA

```bash
# From parent of chatbot/
python -m pytest chatbot/tests -q

# Or from chatbot/ with parent on path
cd chatbot
set PYTHONPATH=..
python -m pytest tests -q
```

Coverage includes orchestrator, state, guards, attachments / vision, capability, service, LLM helpers, spelling, config, and Phase 3 / probe fixtures. Default fixtures use `BOT_MODE=fake` and a real KB index build — no API key required.

Offline quality loops:

- **Golden set** — examples from judged-correct historical chats
- **Replay** — pipeline over old chats with fake composer; reports blockers
- **Probe** — paid grounding scenarios with USD / call budget (needs written approval per project rules)

---

## Safety constraints

1. No paid LLM call without explicit approval for that run (`BOT_ALLOW_LIVE` + key + non-fake mode).
2. Never call the Anthropic API.
3. Mask email and phone before **compose** LLM calls. The inbound language gloss runs unmasked so contact details can be extracted from the visitor’s own words; those values stay in state, not in model prompts for compose.
4. `kb/` wins on signed facts; unverified claims must hand off, not guess.
5. No prices in chat — pricing stays with the quote / operator.
6. The bot must not invent or guarantee packaging dimensions outside the verified catalogue (or the customer’s own numbers).

---

## Related docs

| Doc | Contents |
| --- | --- |
| [`PLAN.md`](./PLAN.md) | Phase 0 status, production baseline, module map, runbook |
| [`PLAN_V2.md`](./PLAN_V2.md) | Goal-driven “shopkeeper” behaviours, registry, probe design |
| [`kb/README.md`](./kb/README.md) | KB authoring rules |
| [`kb/capabilities/SIGNOFF_PACKET.md`](./kb/capabilities/SIGNOFF_PACKET.md) | Capability / compliance sign-off packet |

---

## License / ownership

Internal Print247 sales-support service. Not published as an open-source package.
