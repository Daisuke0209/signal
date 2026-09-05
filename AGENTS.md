<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Project context

Last updated: 2026-09-05

### Product

The application is named **Signal**.

Signal is a real-time sales-assistance application. It understands an ongoing
customer conversation and suggests what the sales representative should ask or
say next. It captures Google Meet tab audio and the representative's microphone on Mac,
transcribes the conversation, and automatically suggests questions, responses,
and confirmation items. An agent searches previously uploaded PDFs and shows
document/page evidence. Signal is intended for real use as well as learning.

### Primary goal

This project is preparation for an OpenAI Forward Deployed Engineer system
design interview. The goal is to understand the following topics by designing
and implementing them:

- full-stack application architecture
- agents and orchestration
- retrieval-augmented generation (RAG)
- authentication and authorization
- state management
- tool calling
- approval for operations with side effects
- human handoff
- failure handling
- logging and tracing

Explaining the design intent and tradeoffs is more important than maximizing
feature completeness.

### Working approach

- Start with the overall architecture and explicit responsibility boundaries.
- Implement one small, explainable capability at a time.
- Before implementation, explain why the proposed design fits and what the
  reasonable alternatives are.
- Avoid generating large amounts of code at once.
- The user has authorized direct implementation, GitHub Issue/PR creation, and
  reviewed merges for the agreed product scope.
- Use three GPT-5.6 Terra subagents for Issue planning, sequential implementation,
  and independent review/merge, with the parent coordinating architecture.
- Keep Issues and PRs small and functional. Use isolated worktrees, communicate
  dependencies, and review/test the exact PR head before merging.
- Record meaningful architectural decisions and their tradeoffs in the repo.

### GitHub issue format

- Review previous issues before creating a new issue.
- Write issues concisely in Japanese.
- Use the sections `目的`, `対象`, and `完了条件`.
- Do not add a `対象外` section.

### Minimum product scope

- user login
- real-time conversation and transcription
- persistent conversation state
- suggested next questions
- suggested next responses
- agentic search over preuploaded PDFs, with document/page evidence
- tool calling
- user approval before side effects
- authentication and authorization
- human handoff
- failure handling
- logging and tracing

### Agreed implementation direction

The 2026-09-05 product agreement supersedes the earlier text-first milestone.
Live transcription and PDF access are part of the initial usable application.

1. Finish conversation read/lifecycle APIs and the desktop sales workspace.
2. Add PDF registration, page extraction, authorized search and source viewing.
3. Capture Google Meet tab audio and microphone audio on Mac Chrome and persist
   live transcripts. Text input remains a diagnostic/recovery path.
4. Automatically orchestrate PDF investigation and question/response/confirmation
   suggestions; preserve current conversation state and reject stale results.
5. Complete approved in-app confirmation requests, human handoff, recovery,
   traces, and end-to-end verification.

Use a minimalist light UI on a full second monitor: transcript on the left,
next questions, response examples and confirmation items on the right. Keep
PDF management and conversation history in separate views.

See `docs/product-and-architecture.md` for the agreed experience, responsibility
boundaries, tradeoffs and acceptance checklist. Features in that document are
planned until their individual Issues are implemented and verified.

### Current status

- Auth/AuthZ foundation tables exist for organizations, users, and memberships.
- The backend is implemented in Python with FastAPI, SQLAlchemy, and Alembic.
- Python dependencies and commands are managed with uv.
- An idempotent demo-data seed creates an organization, user, and admin
  membership with a hashed password.
- Database-backed session creation, validation, deletion, and integration tests
  are implemented in Python.
- Login/logout/current-user APIs and a Next.js login screen are implemented.
- Organization-authorized conversation creation and message append APIs exist,
  with persistent participants, ordered messages and integration tests.
- Next.js is the frontend and calls the Python API over HTTP.

### Current design direction

Authentication uses the existing opaque database-backed session token. This
keeps expiration, revocation and Auth/AuthZ boundaries explicit for learning.
Framework-managed authentication remains a future alternative if operational
needs outweigh that educational benefit; do not rebuild existing auth now.

Keep backend application logic in `backend/src/signal_api`. Use FastAPI for the
HTTP boundary, SQLAlchemy for persistence, Alembic for migrations, pytest for
tests, Ruff for linting and formatting, and mypy for type checking. Do not add
new database or authentication logic to the Next.js application.

Keep this section focused on durable project goals, agreed design decisions,
the learning approach, and milestone status. Update it when those facts change.
