<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Project context

Last updated: 2026-09-06

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
- Use GPT-5.6 Terra for every subagent. Two implementation lanes cover the
  conversation/audio/agent UI and PDF/search capabilities; a separate reviewer
  handles review/merge. The PDF implementer also owns Issue creation within the
  available concurrency limit. The parent coordinates architecture and ordering.
- When implementation or review discovers additional required work, send its
  rationale, scope, acceptance criteria, dependencies and blocking status to the
  Issue owner. The Issue owner checks existing Issues before creating one, and
  the parent prioritizes it. Fixes needed by an existing Issue stay in its PR.
- Every UI-changing Issue must contain a screenshot of the actual running app
  with test data. Link the Issue from the PR; the reviewer verifies the screenshot
  reflects the final UI before merge. Use immutable image URLs so branch cleanup
  does not break the image. Never publish credentials or customer data.
- After merge, verify the linked Issue is closed and delete the remote work
  branch. The owner switches a clean worktree away from the merged branch and
  safely deletes the local branch without discarding uncommitted work.
- Report open Issues, newly created Issues/PRs, merged PRs and estimated remaining
  time every ten minutes. This run's baseline is GitHub Issue/PR number 22.
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

- FastAPI/SQLAlchemy/Alembic owns authentication, organization authorization,
  conversations, selected PDF scope, suggestions, approvals, handoffs and summaries.
  Next.js owns the UI, browser audio capture and presentation state.
- Opaque database sessions, login/logout and organization-authorized conversation
  creation, ordered message persistence, retrieval and ending are implemented.
- PDF upload, page extraction and authorized keyword search are implemented.
  The suggestion agent can search and read selected documents with page evidence.
- Browser tab and microphone capture, Realtime transcription relay, final-message
  persistence and SSE automatic suggestion updates are implemented. Provider tests
  and real API smoke checks exist; actual Meet plus physical microphone acceptance
  and real-world latency targets remain unverified.
- Approval and in-app handoff APIs, claim/respond authorization and idempotency,
  ended-conversation summary generation/retry, and ID-only domain traces are merged.
- Remaining UI integration, screenshot evidence and manual acceptance are tracked
  separately from backend completion. Do not treat an open Draft PR as shipped.
- See `docs/implementation-status.md` for the dated verification matrix, known
  limitations and the next manual acceptance steps.

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
