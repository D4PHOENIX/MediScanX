# agent_service

The MediScanX clinical assistant: a LangGraph agent on Google Gemini that answers questions about a patient's results and general medical questions, grounded in a retrieval corpus of thoracic and pulmonary literature. Internal only — clients reach it through `POST /api/v1/agent/chat` on the gateway.

FastAPI · Python 3.11 · LangGraph · langchain-google-genai · psycopg / asyncpg · transformers (MedCPT) · pgvector

## Layout

```
src/app/
├── main.py                 lifespan: DB pool, graph build, checkpointer setup
├── api/routes.py           POST /chat (SSE)
├── api/stream_mapper.py    LangGraph events → SSE frames
├── api/health.py           GET /, /healthz, /ready
├── agent/graph.py          system prompt, tool registry, graph wiring
├── agent/state.py          AgentState
├── agent/powersync.py      writes final messages to chat_messages
├── agent/tools/            rag_tool, ml_tools, temporal, fusion, labels
└── core/                   config, security, exceptions, embedding_contract
```

## The graph

```
request ─► agent (Gemini, 9 tools bound) ──tool_calls──► tools (ToolNode) ──┐
                 ▲                                                          │
                 └──────────────────────────────────────────────────────────┘
           agent ──final answer──► sync_powersync ─► END
```

- **Model:** `ChatGoogleGenerativeAI`, `temperature=0`, streaming; the model name comes from `GOOGLE_MODEL`.
- **State:** `AgentState(MessagesState)` with `patient_id`, `current_scan_id`, `execution_step`, `multimodal_metadata`, `rag_citations`; messages accumulate through the `add_messages` reducer.
- **Memory:** `AsyncPostgresSaver` checkpoints the full state per `thread_id` into the `checkpoints*` tables. The system prompt is injected only on the first turn of a thread.
- **Display copy:** `sync_powersync` writes the user and assistant text, with citations, to `chat_messages`, which PowerSync replicates to the phone.

## System prompt rules

1. Search the clinical knowledge base first for every medical question.
2. Synthesise and cite document titles when results are relevant.
3. When retrieval finds nothing useful, answer from general knowledge behind a fixed disclaimer.
4. Never refuse a medical question; never diagnose definitively ("findings suggestive of").
5. Flag fused risk ≥ 0.85 as CRITICAL; say plainly when a label is missing or a trend is indeterminate.

## Tools

| Tool | Purpose |
|---|---|
| `search_clinical_guidelines(query, finding_label?)` | Glossary match + MedCPT vector search (+ optional rerank); returns citations |
| `run_cxr_inference`, `run_ecg_inference`, `run_skin_inference` (`scan_id`) | Re-run a model on one of the caller's stored scans |
| `list_recent_scans(limit)` | The caller's most recent scans |
| `calculate_temporal_progression(current_scan_id, previous_scan_id?)` | `improving` / `worsening` / `unchanged` / `changed` / `indeterminate`, with confidence delta and days between |
| `query_patient_metrics()` | The caller's profile |
| `fuse_multimodal_findings(...)` | Weighted multimodal risk (same rules as the gateway) |
| `orchestrate_fusion(scan_ids)` | Load selected scans, then fuse them |

**Tenant isolation:** the user id is never a model-filled argument. The route injects `auth_user_id` from the verified JWT into the run config, and every tool filters its SQL by it. `/chat` also rejects a `patient_id` that differs from the token and a `thread_id` owned by someone else (403).

## Retrieval

Single source of truth: `core/embedding_contract.py`.

| Setting | Value |
|---|---|
| Query encoder | `ncbi/MedCPT-Query-Encoder` ([CLS] pooling, L2-normalised) |
| Corpus encoder | `ncbi/MedCPT-Article-Encoder` (offline seeder; the two encoders only work as a pair) |
| Reranker | `ncbi/MedCPT-Cross-Encoder`, enabled with `RERANK_ENABLED=true` |
| Dimension / max length | 768 / 512 tokens |

Per query: an exact glossary lookup when a finding label is supplied, then `match_rag_corpus($1::halfvec(768), 0.1, 20, NULL, 'thoracic')` — a deliberately low similarity floor for recall — then, when enabled, a cross-encoder rerank to the top 5. The corpus (`rag_corpus`, 49,875 rows: PubMed 30,016, textbooks 16,022, Open-i reports 3,826, glossary 11) is built by `notebooks/rag-corpus-seeder.ipynb`. Models load once per process.

## Streaming

`stream_mapper.py` maps `astream_events(version="v2")` to SSE:

| Event | When |
|---|---|
| `text` | each generated token |
| `ui_trigger` (`tool_call`, `cxr_result`, `result`, `pdf_generated`) | a complete tool call or a tool result the app should render |
| `error` | a typed failure |
| `: keepalive` | every 15 s of silence, so proxies keep the connection open |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/chat` | `{messages, patient_id?, thread_id?, current_scan_id?, execution_step?, multimodal_metadata?}` → `text/event-stream` |
| GET | `/healthz` · `/ready` · `/` | liveness, readiness (graph compiled), metadata |

## Configuration

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY`, `GOOGLE_MODEL` | LLM |
| `DATABASE_URL` | Postgres for tools and the checkpointer — Supabase **session pooler** (set from `AGENT_DATABASE_URL` in Compose) |
| `SUPABASE_URL`, `SUPABASE_SECRET_KEY` | Storage downloads for the inference tools; JWKS issuer |
| `CXR_SERVICE_URL`, `ECG_SERVICE_URL`, `SKIN_SERVICE_URL` | Internal model services |
| `RERANK_ENABLED` | Cross-encoder rerank (default off) |
| `HOST`, `PORT` | Default `0.0.0.0:8005` |
| `DEV_MODE`, `DEV_TOKEN_SECRET` | Local testing only |

## Run and test

```bash
uv sync --all-extras
uv run uvicorn app.main:app --app-dir src --reload --port 8005
uv run pytest -q                      # 86 passed
```

The first start downloads the MedCPT models from Hugging Face.
