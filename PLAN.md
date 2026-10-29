# Print247 chatbot — status audit and plan

**Last updated:** 2026-10-29
**Status:** Phase 0 complete (build + fake-mode validation). Phases 1–6 are proposals — not executed.
**Service:** `chatbot/` (Python, FastAPI) · **Knowledge base:** `kb/` · **QA data:** `server/`

> **Sequence note:** the code in `chatbot/` was built before this plan was reviewed. This
> document is the missing plan. It records what exists, why, what was measured, what is
> still open, and the rollout from here. This plan is independent of
> `server/docs/plan_extracted.txt`, which is not being followed. Anything in Phase 1+ is
> undecided until reviewed.

---

## 1. Goal

Build a chatbot that answers Print247 website chats better than the current production bot by combining:

- the 39-document `kb/` knowledge base as the factual source,
- QA findings from 2,046 real chats (300 judged),
- nine sales personas in round-robin,
- deterministic rules that refuse unsafe replies before they are sent.

### Definition of "better" — proposed targets, needs sign-off

Production baseline on the same 300 judged chats: **121 correct (40.3%), 93 partly (31.0%), 86 wrong (28.7%)**.

| Metric | Production baseline | Proposed target |
| --- | --- | --- |
| Judged correct | 121 / 300 (40.3%) | ≥ 165 / 300 (55%) |
| Judged wrong | 86 / 300 (28.7%) | ≤ 45 / 300 (15%) |
| `ignored_question` issues | 73 | ≤ 10 |
| Replies blocked by rules | not measured | 0 |
| Lead capture (email/phone) | needs measurement | ≥ production on same sample |
| p95 reply latency | 1.3–2.2 s for gpt-5-nano in production testing notes | < 6 s |

These are proposals for review, not commitments.

### Non-goals

- Fine-tuning a model. The production bot is not fine-tuned and no data justifies it yet.
- Replacing the QA dashboard in `client/` + `server/`.
- Giving prices in chat. Pricing stays with the quote, same as production.
- Multilingual output in Phases 0–3. Production detects Spanish, French, Portuguese, German,
  Italian and non-Latin scripts and translates replies on the way out; whether the new bot must
  match that is decision D9.
- ERP pricing integration.

---

## 2. Constraints and rules

1. No real paid LLM/API call without explicit approval **for that run**.
2. Never call the Anthropic API.
3. Mask PII before any external LLM call (today: email + phone).
4. `kb/` is the factual source; 4 facts conflict with production and need sales sign-off.
5. `server/data/chats.json` is read-only and is never modified.
6. No push, deploy, or publish without explicit approval.
7. Default model `gpt-5-nano`, 6-second budget, OpenAI-compatible API.
8. No package installs without approval (`cryptography` is currently optional; see G4).

---

## 3. What production does (baseline being compared against)

Source: `Original/lead-follow-up` (TypeScript, Railway).

- **Model:** `gpt-5-nano` via OpenAI (`src/services/aiClient.ts`), no fine-tuning.
- **No retrieval / RAG:** no embeddings or vector search anywhere in `src/`.
- **Knowledge:** `DEFAULT_COMPANY_FACTS` in `src/domain/companyKnowledge.ts`, editable settings in MongoDB (`Settings.ts`), sales scripts in `src/domain/salesScript.ts`.
- **Prompt:** built in `src/services/salesiq/chatComposer.ts` (~1,852 lines including prompt text and composition helpers).
- **Rules/engine:** `src/services/salesiq/chatEngine.ts` (~2,388 lines of deterministic logic and reply handling), plus `handoff.ts`.
- **Shape:** webhook handler `src/services/salesiq/webhook.ts`, SalesIQ reply JSON, operator handoff.
- **Language:** `src/domain/visitorLanguage.ts` detects the visitor's language (Spanish, French,
  Portuguese, German, Italian, Arabic, Russian, Chinese, Japanese, Korean), and replies are
  translated on the way out (`replyLanguage.ts`). Internally the bot thinks and guards in English.

QA baseline (from `server/out/judge_300.jsonl`, 300 judged chats):

| Production issue | Count |
| --- | --- |
| ignored_question | 73 |
| unanswered_reply | 71 |
| other | 51 |
| multiple_questions | 35 |
| lead_lost | 23 |
| repeated_question | 20 |
| wrong_fact | 17 |
| answer_mismatch_ignored | 14 |
| hallucination | 12 |
| opener_redundancy | 12 |
| promise_to_check | 12 |
| ignored_goodbye | 10 |

The new bot's design directly targets the top issues: answer the question first, one question per message, no promises to check, no invented facts, no repeated asks, and a quote handoff only when the conversation is actually complete.

---

## 4. What is built (Phase 0)

### 4.1 Status at a glance

| Area | Status | Evidence |
| --- | --- | --- |
| KB ingest + BM25 retrieval | Done | 39 documents → 60 chunks, all `verified` |
| Canonical facts + sign-off tracking | Done, 4 facts unsigned | `chatbot/bot/canon.py`, `cli signoff` |
| Conversation state machine | Done | `chatbot/bot/state.py` (756 lines) |
| Nine personas, round-robin | Done | `personas.py`, `store.py` (atomic counter) |
| Deterministic composer (fake mode) | Done | `composer.py` |
| Live LLM composer + verifier rewrite | Implemented; full path exercised against a local mock of the OpenAI wire format; real-key call pending | `composer.live_turn`, `llm.py`, `cli llm-check`, Section 5.4 |
| Deterministic guards | Done | 20 block rules, 10 warnings |
| Golden examples | Done | 88 examples from 121 judged-correct |
| Offline replay + report | Done | 300 chats, 0 blockers (2 drafts rejected and replaced) |
| SalesIQ-compatible webhook | Done, not connected | `service.py`, signature + trigger/message/close/failure |
| Local browser chat UI | Done (local only) | `web/index.html`, `/api/start`, `/api/chat` |
| Tests | Done | 68 passed |
| Deployment (Docker/Railway) | Not started | no Dockerfile |
| Shadow / canary / live | Not started | — |
| Judge comparison vs production | Not started | — |

### 4.2 Module map

| File | Lines | Role |
| --- | --- | --- |
| `bot/state.py` | 862 | Families, script, field extraction/validation, size/qty parsing, completion |
| `bot/guards.py` | 605 | All deterministic checks, block/warn severities |
| `bot/orchestrator.py` | 465 | Turn pipeline, handoff decisions, retry/fallback, state persistence |
| `bot/canon.py` | 459 | 19 canonical facts, topic detection, sign-off report |
| `bot/kb.py` | 324 | Markdown ingest, chunking, BM25 search, family hinting |
| `bot/replay.py` | 316 | Offline replay harness + Markdown/JSON report |
| `bot/composer.py` | 344 | Heuristic composer + live prompt builder + `live_turn` |
| `bot/cli.py` | 233 | `ingest`, `golden`, `replay`, `ask`, `chat`, `transcript`, `serve`, `signoff`, `llm-check` |
| `bot/service.py` | 231 | FastAPI app, SalesIQ webhook, `/health`, `/signoff` |
| `bot/golden.py` | 150 | Builds golden examples from judged-correct chats |
| `bot/store.py` | 120 | SQLite conversations, events, persona counter |
| `bot/llm.py` | 176 | OpenAI client: reasoning-model params, JSON schema + retry, call cap, token logging, PII masking |
| `bot/config.py` | 122 | Env config + mode/spend gates |
| `bot/personas.py` | 52 | 9 personas + validation |
| `bot/pii.py` | 26 | Email/phone masking |
| `web/index.html` | 615 | Local chat UI, no build step, no CDN |
| `tests/` | 939 | 68 tests (14 guards, 44 orchestrator, 5 service, 4 LLM, 1 config) |

### 4.3 Data assets

| Asset | Contents |
| --- | --- |
| `kb/` | 40 markdown files; 39 indexed as `verified` (README excluded) |
| `chatbot/data/kb_index.json` | 60 chunks, BM25 postings, built by `cli ingest` |
| `chatbot/data/golden.jsonl` | 88 example turns from the 121 judged-correct chats (caps: 22/family, 150 total) |
| `chatbot/data/chatbot.sqlite3` | Conversations, events, persona rotation counter |
| `chatbot/out/replay_20261029_202926.*` | 300-chat fake-mode replay (JSON, MD, SQLite) |

### 4.4 Turn pipeline

```
SalesIQ webhook  →  Orchestrator.handle
  1. load conversation state from SQLite
  2. extract + validate visitor fields; detect family and canon topics
  3. choose the next script question; decide handoff (human / quote / complex / max-turns / stalled / declined)
  4. BM25 retrieve top-6 KB chunks (family-filtered, with fallback search)
  5. compose the reply:
       - fake mode  → deterministic heuristic composer
       - live mode  → LLM with written answers + KB excerpts + 3 golden examples
  6. run the guard layer (20 block rules, 10 warnings)
  7. if live reply is blocked → one verifier rewrite with the blocker text
  8. still blocked → deterministic safe fallback (canon answers + next question), re-guarded
  9. persist state + event row; return SalesIQ JSON
```

Every turn records: visitor text, reply, persona, source (`heuristic` / `live` / `live-rewrite` / `fallback`), issues, retrieved chunk IDs, accepted/rejected fields, and flags.

### 4.5 Scripts and fields by family

Blocking fields for any quote: **product, size, quantity**. Contact: **email** (fallback **phone**). When all are done the conversation hands off as `quote`.

| Family | Script order |
| --- | --- |
| bags | size → style → finish → quantity → SKUs → extras → material |
| boxes | size → style → finish → quantity → SKUs → material |
| labels | size → finish → quantity → SKUs → material |
| banners | size → quantity → finish → material (single/double-sided) |
| business cards | size → quantity → finish → material |
| print | size → quantity → finish → material |
| unknown | product first, max 2 attempts, then hand off |

Field handling includes: pouch/bag/box/label/banner/sign detection, inches/cm/mm confirmation when a size has no unit, pack-count vs order-quantity disambiguation, finish-vs-style separation, and "no standard size" answers.

Answer handling: an unsure size ("not sure") is stored as `to be confirmed` and gets the custom-size explanation instead of a verbatim echo; "I don't have…" at the style or material question is stored as `no preference` and gets a short options list; the product field stores the family label ("boxes"), not the visitor's sentence. A quantity below the standard minimum no longer hands off — the reply states the standard MOQ, says smaller runs are possible, and asks the next question.

Size units: a unitless size ("100 x 150") gets the "inches, cm or mm?" follow-up, which does not count as a repeated size ask; a unit-only answer ("mm") is merged into the stored size ("100 x 150 mm"). The unit follow-up alone can no longer mark the size unconfirmed.

Contact refusal: if the visitor declines contact at the email/phone question ("no I don't want it", "no thanks", "not interested"), both contact attempts close and the chat hands off as `declined` with a specialist line, instead of repeating the email question. The live composer is skipped for this turn.

MOQ wording (confirmed from production chat, 2026-10-29): "Our standard MOQ is 1,000 per size (500 each if you have multiple designs), but we do smaller runs too, so just tell me the quantity you need." Banners have no minimum.

### 4.6 Nine personas, round-robin

Nine Print247 identities (Alex Kane, Frank Castle, Jessica Joe, Max Carter, Harry Brook, Ethan Wilson, Paul Smith, Brian Tylar, Hazel Grace) rotate per **conversation** using an atomic SQLite counter (`BEGIN IMMEDIATE`). Each persona only changes the greeting/name; policy, script and guards are shared. Replay distribution over 300 chats: 33–34 per persona.

> This is persona rotation, not nine independent models or prompts. If "multiple agents" means something stronger (per-persona prompts/models), see D4.

### 4.7 Guard layer

**Block rules (20 codes):**
`empty_reply`, `too_long` (>95 words), `markdown`, `emoji`, `multiple_questions`,
`promise_to_check`, `holding_phrase`, `discount_promise`, `price_given`, `time_promise`,
`bot_self_claim`, `human_claim`, `unsupported_claim`, `untraceable_number`, `wrong_minimum`,
`unanswered_question`, `repeated_message`, `repeated_question`, `second_intro`,
`question_already_answered`.

**Warnings (10 codes):**
`long_reply` (>65 words), `bot_question_unanswered`, `minimum_needs_condition`,
`possibly_unanswered_question`, `repeated_wording`, `second_greeting`, `off_script`,
`no_question_asked`, `invented_standard_size`, `formatting`.

Key behaviours:

- **Answer-first:** if the visitor asked a detected fact question, the reply must contain the
  written answer tokens, or it is blocked. Handoff lines are exempt because they transfer the
  question to a person.
- **One question per message:** more than one question is blocked.
- **No prices, dates, discounts, or promises to check.** Time phrases are only allowed when
  they exist in canonical facts (e.g. 12–15 business days).
- **No invented claims or numbers:** every number and claim word must appear in the KB,
  written answers, chat history, or the visitor's own words.
- **No repeat asks:** re-asking a completed field is blocked (except an unconfirmed size).
- **No bot self-claims unless asked:** if asked, the reply must disclose AI.

### 4.8 Modes

| Mode | Behaviour | Spends money |
| --- | --- | --- |
| `fake` | Heuristic composer only; used by tests and replay | No |
| `live` | Real LLM + guarded replies returned | Only with `BOT_ALLOW_LIVE=1` + key |
| `dry_run` | Same composition as live, but returns no visitor-visible reply | Only with allow-live |
| `shadow` | Same as dry_run, logs the turn, returns empty replies | Only with allow-live |

`Config.real_llm_enabled` is the single gate; fake mode always wins. A live call also
requires `BOT_ALLOW_LIVE=1` and a key. `BOT_MAX_LLM_CALLS` caps real calls per server process
(0 = unlimited); a verifier rewrite consumes one more call. For `gpt-5-nano` the client omits
`temperature`/`max_tokens`, sends `max_completion_tokens` and `reasoning_effort: minimal`, and
logs model, latency and token usage per call.

### 4.9 SalesIQ compatibility

- Accepts `trigger`, `message`, close handlers, and `failure`; ignores unknown handlers.
- Conversation key: `visitor.uvid` → `active_conversation_id` → `visitor_id` → `conversation_id`.
- Reply JSON: `{"action":"reply","replies":[{"text":...}]}`.
- Handoff JSON (when enabled): `{"action":"forward","operators":[...],"replies":[...]}`.
- Signature: RSA-SHA256 over the raw body, header aliases supported; optional `cryptography` dependency (see G4).

### 4.10 Local chat UI

`GET /` serves `chatbot/web/index.html` when `BOT_UI=1` (default). It is a self-contained
page with no build step and no CDN:

- chat transcript, persona name on each bot reply, handoff banner;
- a debug panel showing reply source, guard issues, rejected drafts, collected fields,
  accepted/rejected field updates, retrieved KB chunks, and timing;
- New chat button; Enter sends, Shift+Enter adds a line.

`POST /api/start` and `POST /api/chat` call the same `Orchestrator` as the webhook, so the UI
exercises the real pipeline in fake mode. It is gated by `BOT_UI`; set `BOT_UI=0` on deployed
environments. The SalesIQ webhook is unchanged.

Handoff behaviour differs by channel: a `quote` handoff locks the composer because the
conversation is complete, while local-UI `human` / `complex` / `max_turns` / `stalled` /
`declined` handoffs clear on the next message and the chat continues. The webhook (SalesIQ)
stays handed off.

---

## 5. Validation so far (Phase 0)

### 5.1 Tests

`python -m pytest chatbot/tests -q` → **68 passed**, 1 Starlette/httpx deprecation warning.

Coverage includes: state extraction and validation, guard rejection/acceptance, handoff logic,
fake-mode replies, webhook reply/close/failure/signature paths, the local UI start/chat flow and
its `BOT_UI=0` switch, live-LLM payloads for reasoning vs chat models, the call cap, and the
regression cases found during replay (pouch typo, pack-count quantity, bare minimum,
finish-vs-style, signs, display trays, materials/extras/custom questions, unknown size without
a re-asked unit question, size unit follow-up merging into the stored size, contact refusal
handing off instead of repeating the email question, a live field echo not overwriting an
answered field, complex-inquiry handoff, international shipping and the "and what it costs"
question-count false positive, food-box recommendation, style options for "no preference",
questions not stored as style/product answers, the context-question reply, field repair,
below-standard quantity continuing the script, and local-UI resume vs webhook lock after
handoff).

### 5.2 300-chat replay (fake mode)

Report: `chatbot/out/replay_20261029_202926.md` (re-run after the size-unit, contact-refusal
and question-extraction fixes in 5.6–5.8)

| Metric | Result |
| --- | --- |
| Chats replayed | 300 |
| Replies | 1,230 |
| Avg replies / chat | 4.10 |
| Avg words / reply | 15.3 |
| Replies containing a question | 89% |
| Blockers / fallbacks | **0 / 2** |
| Replies with no KB hit | 108 (8.8%) |
| Rejected drafts | 1 `unanswered_question`, 1 `question_already_answered` |
| Warnings | 44 `repeated_wording`, 23 `possibly_unanswered_question`, 1 `long_reply` |

Handoffs: stalled 85, quote 32, max_turns 9, human 7, complex 3, declined 1.
Personas: 33–34 chats each.

The one `question_already_answered` fallback replaced a draft that re-asked for a size the
visitor had already supplied in a long spec message. The `unanswered_question` fallback
replaced a draft that ignored "which one is cheaper?" and only asked the style question.
Since the below-minimum handoff was removed, low-quantity chats continue the script instead of
stopping. After the unit follow-up, contact-refusal and question-extraction fixes, stalled
conversations fell to 85 (from 111 before the unit fix) and `possibly_unanswered_question`
warnings fell from 28 to 23. Style is now captured from answers given later in the chat (93
chats, up from 67), while product is no longer assigned from questions (272 vs 298), which is
the intended trade: a question about boxes no longer switches an existing bag order to boxes.

### 5.3 What this proves — and what it does not

**Proves:** the deterministic pipeline is internally consistent; every reply passes every rule;
state collection, handoffs, persona rotation and the SalesIQ response shape work end to end.

**Does not prove:** sales quality, real-LLM behaviour, latency, cost, or performance against the
production baseline. Fake mode measures rule compliance and pipeline behaviour only. The live
path was validated against a local mock of the OpenAI wire format (5.4) and has since been run
by the owner on real chats (5.5, 5.6), but there is still no representative live sample and no
measured latency or cost. `cli llm-check` remains a one-call credential/model check.

Remaining fake-mode warnings are context limitations (e.g. "what are my options" after a finish
question; "do you have anything for pills?"). A live model with the transcript and KB should
handle these; they should be re-checked in Phase 2/3, not patched blindly now.

### 5.4 Live path against a local mock (no spend)

A throwaway mock OpenAI server (same `POST /v1/chat/completions` contract) was used to run the
real live branch end to end with `BOT_MODE=live BOT_ALLOW_LIVE=1 BOT_MAX_LLM_CALLS=10`. Results:

- capture of the outgoing payload confirmed the reasoning-model shape:
  `model=gpt-5-nano`, no `temperature`, no `max_tokens`, `max_completion_tokens=800`,
  `reasoning_effort=minimal`, `response_format=json_schema`;
- turn 1 ("I need custom boxes") returned `source: live` with the expected size question and
  no guard issues; turn 2 ("What is the minimum order?") returned `source: live`, the correct
  MOQ answer plus the size question, `minimum_stated` flagged, no issues;
- no fallbacks and no blockers were triggered, and the call counter enforced the cap.

This proves the transport, schema parsing, prompt assembly, guard pass and state update work
together. It does not prove the real model's wording, latency or cost. The mock server and its
logs were deleted after the run; no paid call was made.

### 5.5 First real live chat (owner-run, 2026-10-29)

The owner enabled `live` locally and asked "can you ship orders to china?". The turn landed on
`fallback` and the debug panel showed `possibly_unanswered_question` plus a rejected draft with
`multiple_questions`. Three defects were behind it:

1. no canon fact for international shipping, and the shipping triggers missed the verb "ship"
   and country names, so the question was not recognised and the KB excerpts were never used;
2. `count_questions` read the KB-correct clause "…and what it costs when they send the quote"
   as a second question, so the live draft was blocked even though it had one real question;
3. the fallback therefore sent only the next script question.

Fix: a new `intl_shipping` canon fact carrying the KB policy wording; country/international
triggers; domestic/international topic de-duplication; a negative lookahead so indirect
"what it costs" clauses are not counted as questions. The repeated live draft now passes the
guards, and both the heuristic and fallback paths answer with the international wording plus
one question. Covered by four new tests.

### 5.6 Second real live chat (owner-run, 2026-10-29)

The owner ran the "dry meat box" script end to end in live mode: suggestion question → size →
"not sure" → "i dont have" → finish → quantity 300 → the bot said a specialist would take over
and the input went dead. Four defects were behind it:

1. **No suggestion.** "suggest me best box for dry meat" matched no canon topic; the prompt only
   asked the next script question, so the answer was missing (fixed with the `food_boxes` fact:
   food-grade SBS folding carton, mailer or kraft, team confirms the spec with the quote).
2. **Junk field values.** "not sure" was stored verbatim and "i dont have" was stored as style;
   the size value also triggered a second "inches, cm or mm?" question after it had already been
   confirmed as unknown, and the following number landed in style. Fixed: unknown size becomes
   `to be confirmed` with the custom-size explanation, "I don't have…" at style/material becomes
   `no preference` with a short options list, the unit question is skipped for a confirmed
   unknown size, and product stores the family label.
3. **Chat locked after handoff.** Quantity 300 triggered a `below_minimum` handoff, and the UI
   disables the composer after any handoff. Fixed: the handoff is removed entirely; the reply
   states the standard MOQ with the smaller-runs line and asks the next question. In the local
   UI only the final `quote` handoff locks the composer; other handoffs resume on the next
   message. The webhook still stays handed off.
4. **MOQ wording.** The owner supplied the production chat wording: "Our standard MOQ is 1,000
   per size (500 each if you have multiple designs), but we do smaller runs too, so just tell me
   the quantity you need." It is now the confirmed canonical answer.

Re-running the same six-turn script in fake mode now gives: food-grade suggestion + size
question → custom-size explanation + style question → style options + finish question → quantity
question → MOQ + SKUs question → material question, with no handoff and no guard issues.

### 5.7 Third real live chat (owner-run, 2026-10-29)

The owner ran a full spec in live mode: "i need 3 design boxes" → "100 x 150" → "mm" → "flat" →
"gloss" → "1000" → "no preference" → then the bot asked for email. The owner replied "no i don;t
want it" twice; the bot repeated the email question, then moved to phone. The debug panel showed
Style as `no preference` and Size as `100 x 150` without the unit. Three defects:

1. **Contact refusal loop.** There was no refusal detection at the contact questions, and a
   re-ask is allowed while the field is open, so the bot kept pushing email and then phone.
   Fixed: at the email/phone/name question, a refusal ("no I don't want it", "no thanks", "not
   interested", plain "no") closes both contact attempts and hands off as `declined` with "No
   problem — let me bring a packaging specialist in to help with the rest." The live composer is
   skipped on that turn, so it cannot ask again.
2. **Live field echo overwrote an answer.** The live model repeats every detail it knows in
   `fields`; on the material turn it returned `style: "no preference"`, and because the word
   "preference" appeared in the visitor's message, validation accepted it and replaced the stored
   `flat`. Fixed: LLM-provided fields may only fill an open field or the field being asked; an
   echo cannot overwrite a completed answer. This also removes the noisy re-accepted/rejected
   fields on every live turn.
3. **Size unit was lost.** The "inches, cm or mm?" follow-up counted as the second size attempt,
   so `finalize_stalled` marked the unitless `100 x 150` as confirmed; the visitor's "mm" was then
   ignored. Fixed: the unit follow-up is not counted as a repeated size ask, and a unit-only
   answer is merged into the stored size (`100 x 150 mm`, status answered).

The same sequence in fake mode, and in the browser UI, now ends with Size `100 x 150 mm`, Style
`flat`, and a `declined` handoff after the first refusal with the composer still enabled locally.
Covered by three tests in this round (68 total after 5.8).

### 5.8 Fourth real live chat (owner-run, 2026-10-29)

The owner asked for a dry-meat suggestion and then ordered bags: "suggest me something suite for
dry meat" → "bags" → "12 x 51" → "cm" → "what style of boxes do you have" → "i want standup
style bags" → "for what? bag or box?". The bot answered the box-style question, then stored the
question itself as Style, switched Product to boxes, lost the stand-up answer, and finally
answered "for what? bag or box?" with the next script question (quantity). Four defects:

1. **Questions were stored as answers.** When the Style question was open, any message that was
   not a finish/material was saved as Style, including "what style of boxes do you have". The
   same text also switched Product from bags to boxes because product extraction ran on any
   mention. Fixed: a message that is a question no longer fills Style/Material/Extras, and it
   cannot switch an already-answered Product. Style answers are normalized (`standup` →
   `stand-up`, `flat bottom` → `flat-bottom`) and captured even when they arrive on a later
   turn ("i want standup style bags" now stores `stand-up`). A saved junk value is repaired on
   the next turn.
2. **The style question had no answer path.** "What style of boxes do you have" matched no
   canon fact, so the heuristic only asked the next script question. Fixed: a new `styles`
   fact lists the KB's bag styles (stand-up, flat, flat-bottom, side gusset, pinch bottom) and
   box styles (display, mailer, gift, kraft, square, cosmetic, apparel). The answer-first guard
   now blocks a reply that ignores it, and when the visitor asks about the other product the
   reply answers that product and then asks the style question for the product they are
   ordering.
3. **"for what? bag or box?" had no answer.** This is a clarification about the open question,
   not a script answer. Fixed: a context-question path answers "For your stand-up bags." and
   repeats the open question, without calling the live model and without using up the field's
   attempts. The same guard covers "which one?", "what do you mean?", and "sorry, what?".
4. **The dry-meat suggestion only covered boxes.** The visitor asked for something suitable
   and then chose bags, but the fact only offered SBS/mailer/kraft boxes. Fixed: the food
   recommendation now offers a food-grade mylar pouch or a food-grade SBS folding carton, and
   it triggers on "dry meat" even when no product is named.

The same sequence plus a finish answer in fake mode now gives: pouch-or-carton suggestion +
product question → bag size → unit → box styles answered + bag style question → `stand-up`
stored → finish question → "For your stand-up bags. What finish..." → quantity question. There
are no guard issues and Product never leaves bags. Covered by six new tests (68 total).

---

## 6. Gaps and risks (honest register)

| # | Gap | Impact | Mitigation | Phase |
| --- | --- | --- | --- | --- |
| G1 | Live LLM path not tested at scale | Prompt/guard behaviour on real traffic unknown; possible false blocks | Owner-run live chats fixed four defect rounds (5.5–5.8); run the keyed micro-run with call cap | 2 |
| G2 | No judge comparison yet | Can't claim "better than production" | Same judge, same 300 chats | 3 |
| G3 | 4 facts unsigned (location, hours, payments, samples) | Wrong-fact risk in live chat | Sales sign-off / overrides file | 1 |
| G4 | `cryptography` not in requirements; signature verification fails closed when key is set | Webhook 401 on deploy | Add dependency + tests, or run behind verified proxy | 4 |
| G5 | PII masking covers email/phone only | Addresses/names may reach the LLM | Decide policy; extend regex if required | 2 |
| G6 | No dollar-budget report (call cap exists) | Spend is capped by calls, not currency | Token usage is logged; add a per-run cost summary | 3 |
| G7 | SQLite single-node store | Multi-instance Railway breaks persona counter/state | Single replica first; Postgres if scaling | 4 |
| G8 | Handoff forwards only the reply line | Operator loses context in the forwarded payload | Include summary or dashboard link | 4 |
| G9 | No rate limiting or body-size limit | Abuse/DoS surface | Add middleware at deploy | 4 |
| G10 | No deployment artifact (Dockerfile/Railway config) | Can't shadow/canary | Add Dockerfile + healthcheck | 4 |
| G11 | No metrics beyond `/health` + events table | Blind operation | Add request/latency/error counters | 4 |
| G12 | 8.8% of fake replies had no KB hit | Some questions answered from canon only | Retrieval tuning after live data | 3 |
| G13 | Golden set is small (88) with caps | Limited prompt guidance | Refresh from new judged chats | 6 |
| G14 | No load/latency test | Unknown p95 under concurrency | Small load test before canary | 4 |
| G15 | No multilingual output (production translates EN→6+ languages) | Non-English visitors get English, unlike production | Decide D9; if required, translate after guards pass, like production | 1 |

---

## 7. Plan from here

### Phase 1 — Review and fact lock (no code; 1–2 days, mostly waiting on sales)

**Goal:** freeze the facts and the scope before spending money.

- [ ] Review this document; adjust targets and phases.
- [ ] Answer the 4 sign-off items (Section 8.1); write decisions to
      `chatbot/data/canon_overrides.json` (no code edit needed) or update `canon.py`.
- [ ] Decide the open questions D1–D9 (Section 8.2), especially disclosure, deployment target,
      and the definition of "multi-agent".
- [ ] Re-run `cli ingest`, tests, and replay after fact changes.

**Exit criteria:** every fact is either confirmed or has approved fallback wording; D1–D6
answered; targets accepted.

### Phase 2 — Live micro-run (one-time spend approval)

**Goal:** prove the real LLM + guard pipeline works before any quality claim.

- [x] Add a hard LLM call cap and token logging (`BOT_MAX_LLM_CALLS`, done).
- [x] Validate the live branch against a local mock of the OpenAI wire format (no spend, 5.4).
- [ ] Add `.env` locally with the user's key; never commit it.
- [ ] Run `cli llm-check` once to verify the key and model.
- [ ] Replay 20–30 representative chats in `live` mode with `BOT_ALLOW_LIVE=1` and a call cap.
- [ ] Inspect: sources (`live` vs `live-rewrite` vs `fallback`), blockers, rewrite loops,
      latency p95, token usage, and any guard false positives.
- [ ] Fix prompt/guard issues found; keep regression tests.

**Exit criteria:** 30 chats complete; 0 final blockers; no repeated rewrite loops; p95 < 6 s;
spend under an approved cap (proposal: US$0.10); at least 80% of replies come from `live`
rather than fallback.

**Approval gate:** explicit approval for this run and its budget before the first API call.

### Phase 3 — Judge comparison vs production

**Goal:** apples-to-apples quality measurement.

- [ ] Build a batch runner that exports new-bot conversations in the same shape the existing
      `server/` judge consumes (masked).
- [ ] Reuse the same judge prompt/rubric and model as the 300-chat baseline (fair comparison).
- [ ] Run 100 chats first; inspect disagreements; fix clear defects.
- [ ] Run the full 300; human spot-check ~30 to estimate judge agreement.

**Exit criteria (proposed):** correct ≥ 55%, wrong ≤ 15%, `ignored_question` ≤ 10, 0 blockers,
lead capture ≥ production on the same chats. If targets are missed, iterate prompt/retrieval
before deployment.

**Approval gate:** budget for judge calls (the judge itself is a paid LLM run).

### Phase 4 — Shadow on production traffic

**Goal:** observe real traffic with zero visitor impact.

- [ ] Add Dockerfile + Railway service config; deploy with `BOT_MODE=shadow`.
- [ ] Verify SalesIQ allows a second webhook or a mirrored event stream. If not, shadow via
      daily export replay instead.
- [ ] Collect 3–7 days of real turns; compose replies but return nothing to visitors.
- [ ] Review: crashes, latency, handoff rate, guard issues, PII in logs, retrieval misses.
- [ ] Add basic metrics/error counters and rate limiting.

**Exit criteria:** 7 days without crashes; p95 < 6 s; ≥ 95% of turns composed; sampled shadow
quality ≥ Phase 3 target; no PII in logs.

**Approval gate:** deployment to a shared environment.

### Phase 5 — Canary, then full live

**Goal:** put the bot in front of a small slice of real visitors, then all of them.

- [ ] Enable `live` for a small slice or off-hours; forward handoffs to the operator with context.
- [ ] Keep the production bot as the fallback path and document the rollback switch.
- [ ] Monitor daily: error rate, blockers/fallbacks, handoff rate, lead capture, complaints.
- [ ] Expand after one clean week.

**Exit criteria:** one clean canary week; lead capture ≥ production; no visitor complaints
attributable to the new bot; rollback tested.

### Phase 6 — Continuous QA loop

- Weekly replay of the last 7 days of new chats; judge a sample; mine new failure types.
- Add regression tests for every fixed failure; refresh golden examples from newly judged-correct chats.
- Update `kb/` monthly or when facts change; re-run ingest and sign-off.
- Track the scorecard in Section 1.

---

## 8. Decisions needed from you

### 8.1 Facts awaiting sales sign-off

| Key | Current written answer | Conflict to resolve |
| --- | --- | --- |
| `location` | Facility in Rosenberg, Texas | Production facts say Houston |
| `hours` | Monday–Friday, 9am–5pm | Production facts say 24/7 support |
| `payments` | ACH, wire, Zelle; card via link with 3% fee | Site lists cards/PayPal; 3% is script-only |
| `samples` | Sample/proof options included with the quote | Production wording differs |

**Needed:** one confirmed answer per row, or "keep current wording until confirmed".
`moq` is now confirmed (2026-10-29) using the production chat wording: standard 1,000 per size,
500 each with multiple designs, smaller runs possible, banners no minimum.

### 8.2 Open decisions (brainstorm list)

| # | Question | Options | Recommendation |
| --- | --- | --- | --- |
| D1 | Who wins when `kb/` and production facts conflict? | KB / production / sales lead | Sales lead confirms; KB is default until then; no live launch with unsigned facts |
| D2 | Budget for the live micro-run | 30 chats / 100 chats / no spend | 30 chats, gpt-5-nano, hard cap US$0.10 |
| D3 | Judge methodology | Existing `server/` judge / new rubric | Existing judge, same model, same 300 chats + human spot-check |
| D4 | What "multiple agents round-robin" means | Persona rotation (current) / per-persona prompts or models | Keep persona rotation first; revisit only if quality data supports it |
| D5 | Handoff transport | Reply-only / forward to operator | Reply-only in shadow; forward with context in canary |
| D6 | Deployment target | New Railway service / replace production | New service; production bot untouched until canary passes |
| D7 | AI disclosure policy | Volunteer AI / answer only when asked (current) | Confirm with owner/legal; current rule blocks volunteering and requires disclosure when asked |
| D8 | Contact collection | Email first, phone fallback (current) | Keep |
| D9 | Language support | English only / match production (detect + translate outbound) | Confirm; English only for Phase 2–3, then copy production's translate-after-guard approach if required |
| D10 | Success weighting | Correctness first / lead capture first | Correctness first, lead capture as a guardrail |

---

## 9. Runbook

```bash
# Rebuild the KB index (39 docs → 60 chunks) and list facts needing sign-off
python -m chatbot.bot.cli ingest

# List sign-off facts as JSON
python -m chatbot.bot.cli signoff

# One tiny live OpenAI call to verify the key and model (paid, fractions of a cent)
# Requires .env: BOT_MODE=live, BOT_ALLOW_LIVE=1, BOT_LLM_API_KEY=...
python -m chatbot.bot.cli llm-check

# Run the offline replay (fake mode; no API calls)
python -m chatbot.bot.cli replay --limit 300

# One message
python -m chatbot.bot.cli ask --conversation-id test-1 --start --text "Do you have a minimum?"

# Interactive chat
python -m chatbot.bot.cli chat

# Print conversations from a replay database
python -m chatbot.bot.cli transcript --db chatbot/out/replay_20261029_202926.sqlite3 --limit 3

# Run the local UI and webhook
python -m chatbot.bot.cli serve --host 127.0.0.1 --port 8000
# then open http://127.0.0.1:8000/ for the chat UI

# Tests
python -m pytest chatbot/tests -q
```

Key env vars (`.env`): `BOT_MODE` (`fake` default), `BOT_UI` (local chat page), `BOT_ALLOW_LIVE` (spend switch),
`BOT_LLM_API_KEY`, `BOT_LLM_MODEL`, `BOT_MAX_LLM_CALLS`, `BOT_TIMEOUT_S`, `BOT_MAX_TURNS`, `BOT_TOP_K`,
`BOT_SALESIQ_PUBLIC_KEY`, `BOT_ALLOW_UNVERIFIED`, `BOT_FORWARD_ON_HANDOFF`,
`BOT_HANDOFF_OPERATOR`.

---

## 10. Glossary

- **Blocker:** a reply the system refuses to send because it breaks a rule.
- **Fallback:** the safe deterministic reply sent when a draft is blocked.
- **Judged chat:** a real conversation scored correct / partly / wrong by the QA judge.
- **Fake mode:** heuristic composer, zero API calls; measures rules, not sales quality.
- **Shadow:** the bot composes replies on real traffic but visitors never see them.
- **Answer-first:** answer the visitor's question before asking the next script question.
