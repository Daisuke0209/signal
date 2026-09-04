<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Project context

Last updated: 2026-09-04

### Product

The application is named **Signal**.

Signal is a real-time sales-assistance application. It understands an ongoing
customer conversation and suggests what the sales representative should ask or
say next. When necessary, it retrieves internal product information through RAG
and shows supporting evidence.

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
- Prefer guiding the user through commands and implementation so they can do the
  work themselves. Make changes directly only when the user explicitly asks.
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
- RAG over internal product information, with evidence
- tool calling
- user approval before side effects
- authentication and authorization
- human handoff
- failure handling
- logging and tracing

### Agreed implementation order

1. Authentication and database-backed session management
2. Text-based conversations and conversation state
3. LLM-generated question and response suggestions
4. RAG with source attribution
5. Real-time transcription
6. Tool calling and approval flows
7. Human handoff and failure handling
8. Logging, tracing, and evaluation

Starting with manually entered text keeps the initial agent and state-management
work independent from speech-provider and real-time transport complexity.

### Current status

- Auth/AuthZ foundation tables exist for organizations, users, and memberships.
- The backend is implemented in Python with FastAPI, SQLAlchemy, and Alembic.
- Python dependencies and commands are managed with uv.
- An idempotent demo-data seed creates an organization, user, and admin
  membership with a hashed password.
- Database-backed session creation, validation, deletion, and integration tests
  are implemented in Python.
- Next.js is the frontend and calls the Python API over HTTP.

### Current design direction

For the authentication milestone, compare a framework-managed approach such as
Auth.js with an opaque, database-backed session token. The database-backed
option is the initial preference for this educational project because it makes
session lifecycle, cookie security, revocation, and Auth/AuthZ boundaries
explicit. Revisit this decision before implementation and document the final
choice rather than treating it as settled architecture.

Keep backend application logic in `backend/src/signal_api`. Use FastAPI for the
HTTP boundary, SQLAlchemy for persistence, Alembic for migrations, pytest for
tests, Ruff for linting and formatting, and mypy for type checking. Do not add
new database or authentication logic to the Next.js application.

Keep this section focused on durable project goals, agreed design decisions,
the learning approach, and milestone status. Update it when those facts change.
