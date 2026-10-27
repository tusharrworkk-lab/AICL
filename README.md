# ACIL — Agent Context Intelligence Layer

ACIL is a modular monolith for collecting agent execution evidence and turning validated recovery strategies into reusable context. The current implementation covers Milestones 1 through 7 plus shared recurrence, global evaluation candidates, deterministic journey judging, blocker metrics, and shared strategy promotion: tenant-scoped API-key authentication, project management, canonical trace-event ingestion, deterministic failure grouping, evaluation-driven strategy validation, context compilation, an MCP server, provider adapters, opt-in de-identified recurrence aggregation, redaction, idempotency, batching, PostgreSQL migrations, and an executable FastAPI service.

## Run locally

```bash
uv sync --extra dev --extra llm
uv run alembic upgrade head
uv run python -m acil.bootstrap
uv run uvicorn acil.main:app --reload
```

For PostgreSQL, run `docker compose up -d postgres`, set `ACIL_DATABASE_URL`, then run `alembic upgrade head` before starting the API.

All API keys are stored as SHA-256 hashes. Every project and event query includes the authenticated tenant id; cross-tenant project ids, sessions, and events therefore return 404. Event attributes redact common secret-shaped keys and are capped at 32 KiB. Duplicate event IDs are returned idempotently without creating another row.

Available trace endpoints are `POST /v1/events`, `POST /v1/events/batch`, and `GET /v1/sessions/{session_id}/trace`. Failure endpoints are `GET /v1/failures` and `GET /v1/failures/{failure_id}`. Evaluation endpoints are `GET /v1/evaluations` and `POST /v1/evaluations/{id}/run`; strategy endpoints are `GET /v1/strategies`, `GET /v1/strategies/{id}`, and `POST /v1/strategies/{id}/activate`. Context compilation is available at `POST /v1/context/compile`, with structured and optional Markdown output. MCP tools are `get_execution_context`, `get_known_failures`, `get_validated_strategies`, `report_execution_outcome`, `report_failure_for_review`, and `evaluate_action_risk`. API events may include an `api_url` attribute: ACIL removes its query, fragment, and credentials, stores a tenant-private host/path template, and uses only a stable target fingerprint for global recurrence and preflight matching. `evaluate_action_risk` returns aggregate warning or confirmation guidance without exposing another tenant's traces. Failed events are grouped using a stable SHA-256 fingerprint over observed action, error category, native tool, environment fingerprint, API target fingerprint, and tool capabilities. The generic JSON event shape is the canonical integration boundary; provider-specific adapters are planned for a later milestone.

The automated suite uses SQLite for fast deterministic tests. PostgreSQL migration syntax is validated with Alembic against SQLite compatibility mode; a live PostgreSQL integration test is still required before production deployment. PostgreSQL row-level security and transaction-scoped tenant settings remain a hardening task for the next database milestone. Failure records contain observed evidence only; no arbitrary commands are executed by evaluation runs. The predefined recovery strategy is evaluated from caller-supplied action evidence and only then moves from `CANDIDATE` to `VALIDATED`, followed by explicit activation. The context compiler returns only active, applicable strategies and records each request in `context_requests`.

Global learning is disabled by default per tenant. Enable it with `POST /v1/tenant/learning` and `{"enabled": true}`. Opted-in failures contribute only abstract fields to `global_failure_patterns`; raw event attributes, commands, source code, and tenant project identifiers are not returned by `GET /v1/global/failures`.

Global evaluation endpoints are `GET /v1/global/evaluations` and `POST /v1/global/evaluations/{id}/run`. The credential-free deterministic judge reports action coverage and blockers. Passing runs validate a global strategy; `POST /v1/global/strategies/{id}/activate` promotes it to shared active knowledge. An injectable `JourneyJudge` interface in `acil/judge.py` is ready for an optional LLM-backed implementation; the core suite does not require model credentials and does not execute commands.

The optional LLM judge runs through Amazon Bedrock. Install the optional dependency with `uv sync --extra bedrock`, configure either `BEDROCK_API_KEY` or the standard AWS IAM/SSO credential chain, and request `judge_provider: "bedrock"` in the global evaluation request. It defaults to the India cross-Region inference profile `in.moonshotai.kimi-k3` in `ap-south-1` and uses Bedrock's Converse API. Set `BEDROCK_MAX_OUTPUT_TOKENS` to at least `256` for the structured judge JSON response. It sends bounded, redacted abstract evidence, expected actions, observed actions, and outcome; it returns a reliability score, blockers, improvement suggestions, and structured user-action requests such as a scoped missing tool credential. LLM analysis is never treated as tool execution: strategy promotion additionally requires the deterministic ordered-action/outcome gate to pass. Without usable AWS credentials or Bedrock model access, the endpoint returns `503` and the deterministic judge remains available.

## Isolated evaluation runner

The optional runner is off by default. When explicitly enabled, `POST /v1/global/evaluations/{id}/execute` runs only ACIL's fixed `CHECK_DEPENDENCIES`, `PREPARE_ENVIRONMENT`, and `RUN_TESTS` templates in a prebuilt Docker image selected by server configuration. It has no network, no host mounts, a read-only root filesystem, dropped Linux capabilities, a non-root UID, process/memory/CPU limits, and a timeout. The image must contain the target repository at `/workspace`, `uv`, a locked dependency definition, and pytest. Container output is never persisted or sent to Gemini.

Set `ACIL_EVALUATION_RUNNER_ENABLED=true` and `ACIL_EVALUATION_DOCKER_IMAGE` only after reviewing and publishing that evaluation image. Gemini analyzes the isolated run's safe evidence after execution but never generates Docker commands or controls the runner. A passing Gemini assessment cannot promote a strategy unless ACIL's deterministic evidence gate also passes.

For a controlled Python target repository, copy `examples/evaluation-target.Dockerfile` into the repository and build it from that repository's root:

```bash
docker build -f evaluation-target.Dockerfile -t acil-evaluation-target:local .
export ACIL_EVALUATION_RUNNER_ENABLED=true
export ACIL_EVALUATION_DOCKER_IMAGE=acil-evaluation-target:local
```

Then invoke `POST /v1/global/evaluations/{id}/execute` with `{"judge_provider":"gemini"}`. Do not use an image that contains production credentials, host-mounted source, or unreviewed code.

Run the stdio MCP server with:

```bash
uv run python -m acil.mcp_server
```

MCP clients should pass an ACIL API key to each tool. The server authenticates the key, resolves its tenant, and checks project ownership before reading or writing any data.

## Local operations console

The built-in console is intentionally a small, API-key-scoped log viewer rather than a separate frontend service. Start ACIL, then open `http://127.0.0.1:8000/`. Enter `http://127.0.0.1:8000` and the development key `acil-dev-key` (or your configured `ACIL_API_KEY`). It displays only projects and execution evidence authorized by that key, including recent trace events, failure patterns, strategies, and compiled context.

It can create a project and inject a clearly labelled **simulated** missing-dependency trace to demonstrate the learning loop. This creates a candidate strategy; use the API or your test agent to submit a successful evaluation before the strategy can be activated. The console never receives or bypasses a tenant boundary: every data request uses the entered Bearer key.

Provider adapters are available through `acil.adapters` and the normalized HTTP endpoint `POST /v1/events/normalized`. Supported adapter names are `generic`, `claude_code`, and `codex`. They accept observable JSON events and return the canonical ACIL event model. They intentionally do not capture hidden model reasoning. Claude Code stream or hook events and Codex CLI JSONL item events should be treated as best-effort observable inputs; provider schemas may evolve, so unsupported fields are preserved only in bounded attributes and the integration boundary remains the canonical event model.
