# Conventions

How work gets done in this repository.

## Branches

Named for what they do, in plain words, lowercase with hyphens.

```
patient-search
appointment-booking
opd-queue-tokens
fix-duplicate-patient-numbers
prescription-pdf
```

Not `feature/PROJ-123`, not `chore/update-stuff`. Somebody reading the branch list should be able to tell what is in flight.

## Commits

Present tense, specific to what changed, written for a person reading `git log` in six months.

```
add phone number search to the patient list
stop the queue from refetching when the tab is hidden
fix invoice balance not updating after a partial payment
move appointment validation out of the route handler
```

Avoid restating the diff, listing every file, or reaching for words like *comprehensive*, *robust*, *seamless* or *enhance*. A subject line under about 70 characters, and a body only when the reasoning is not obvious from the change.

If a commit needs a long explanation of what it does, it is probably two commits.

## Pull requests

Everything lands through a PR. No direct pushes to `main`.

The title says what it does — "Let receptionists search patients by phone number" — and the description covers what changed, why, how to verify it, and anything deliberately left out. Screenshots for UI work; before and after where a layout changed.

`main` stays deployable. A PR that leaves the app broken is not ready, however small the remaining piece is.

## Python

- `ruff` for linting and formatting. `mypy` in strict mode.
- Type hints everywhere. `Any` needs a comment explaining why.
- Route handlers stay thin: parse, call one service, return. Business logic in services, queries in repositories.
- Functions do one thing. A function that needs a section comment is two functions.
- Custom exceptions from `core/exceptions`, mapped centrally to error codes. No `HTTPException` scattered through services.
- Pydantic models for every request and response. No raw dicts crossing a boundary.
- Never `select(Model)` without tenant scoping outside the platform admin path.

## TypeScript

- `strict: true`. `any` is a review conversation.
- Server Components by default; `"use client"` only where interactivity requires it.
- All server state through TanStack Query. None in `useState` or context.
- Zod schemas in `schemas/`, shared between form validation and inferred types.
- Components under roughly 200 lines. Past that, something wants extracting.
- No business logic in components. Formatting, calculation and rules belong in `lib/`.
- Named exports, except for Next.js pages and layouts.
- Files `kebab-case`, components `PascalCase`, hooks `use-*`.

## Tests

Written with the feature, not after it.

Covered without exception: money arithmetic, appointment validation, queue state transitions, permission checks, and tenant isolation. Those are the places where a bug is expensive rather than annoying.

Backend tests run against a real Postgres instance, not SQLite — exclusion constraints, enums and `NUMERIC` behave differently, and testing against a different database tests the wrong thing.

Playwright covers the golden path end to end. It is the check that the pieces still fit together.

Tests use obviously synthetic data. Nothing that could be mistaken for a real person.

## Comments

Explain why, never what.

```python
# Neon's pooler runs in transaction mode, so prepared statements
# can land on a different backend than the one that created them.
connect_args = {"statement_cache_size": 0}
```

Not:

```python
# set statement cache size to 0
connect_args = {"statement_cache_size": 0}
```

No commented-out code, no `TODO` without an owner and a reason, no section-divider banners.

## Environment

Every variable goes in `.env.example` with an empty value and a comment on what it is and where to get it. `.env` is never committed. Adding a variable means updating the example in the same PR.

No credential, key or connection string appears in source. The repository is public — anything committed is compromised permanently, and the response is rotation, not deletion.

## Definition of done

A feature is not finished because the endpoint returns 200. It is finished when all of this is true:

- Model and migration exist
- API endpoint exists, validated with Pydantic
- Permission check enforced server-side
- Tenant scoping enforced at the repository
- Frontend exists and is wired to the real API
- Loading, empty and error states exist
- Success feedback exists
- Works on tablet and mobile
- Keyboard accessible with visible focus
- Tests cover the logic that matters
- Docs updated if behaviour changed

No placeholder buttons. No hard-coded responses standing in for an endpoint. If something is not built, it is behind a flag or absent — not faked.
