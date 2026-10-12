# Loom walkthrough script (approximately 7 minutes)

Use the supplied accounts from [ASSIGNMENT.md](./ASSIGNMENT.md). Hide passwords,
bearer tokens, browser storage, and environment variables while recording.
This is a recording script, not a claim that a Loom video has been recorded.

## 0:00-0:45 - Scope and reproduction

**Show:** the assignment, `git remote -v`, and the commit/diff.

"I worked in my personal fork, not Base360-AI's original repository. I traced
the dashboard through the API, cache, authentication, reservation service,
database configuration, schema, and seed data. The initial ten regression
tests failed. A direct call also reproduced an important hidden problem:
database failures returned fabricated financial totals instead of an error."

## 0:45-2:15 - Cross-client leakage

**Show:** the old and new cache key in
[cache.py](./backend/app/services/cache.py), then both account dashboards.

"Properties use a composite ID and tenant key. Both clients legitimately own
`prop-001`, but the old Redis key contained only that property ID. Whichever
client warmed the cache could supply the other client's next response.

The new versioned key includes tenant, property, year and month. Cache hits
also validate ownership, and both database queries filter by tenant. Legacy
keys are never read. Missing or ambiguous tenant membership is rejected rather
than defaulting to tenant A.

I also removed the password-free non-fixture login path and unsigned-token
fallback. Authentication cache hits still verify token signature and expiry.
The identity endpoint reuses the authenticated tenant rather than resolving a
different tenant by email. Browser financial requests use the current session,
bypass browser caches, and discard responses from an earlier account."

**Demo:** Sunset `prop-001` is 2250.00 / four bookings. Log out, log in as Ocean:
its own `prop-001` is 0.00 / zero bookings. Refresh repeatedly. Select Ocean's
lakeside property to show its own 1776.50 / four bookings. Explain that the
foreign-property tests return 404 without disclosing another client's totals.

## 2:15-3:45 - March and DST

**Show:** [reservations.py](./backend/app/services/reservations.py), the seed
check-in just before March UTC, and the month selector.

"The monthly helper was an unused zero placeholder with naive boundaries.
The dashboard did not send a reporting month at all. The total calculation
also used nonexistent Supabase database settings, the wrong async pool API,
and a fabricated fallback. I repaired the existing connection pool to use
`DATABASE_URL` and real PostgreSQL queries.

Revenue belongs to the property-local month of check-in. In Paris,
2024-02-29 23:30 UTC is already March 1, so the seeded 1250 booking belongs in
March. Paris's March UTC interval is February 29 at 23:00 through March 31 at
22:00. New York's is March 1 at 05:00 through April 1 at 04:00.

Each boundary is constructed in the property's IANA timezone and converted
independently to UTC. The end is exclusive, preventing double-counting. The
tests include bookings immediately before, exactly at, and immediately before
and at the end of these intervals."

**Demo:** Sunset March reports 2250.00; February reports 0.00. Return to March.
Explain that API requests with no month/year still return all-time summaries.

## 3:45-4:45 - Exact cents

**Show:** `SUM(total_amount)`, `round_revenue`, the API response shape, and
[formatRevenue.ts](./frontend/src/utils/formatRevenue.ts).

"The database already stores exact NUMERIC values with three decimal places.
The old API converted the raw total to float and the frontend rounded with
`Math.round(amount * 100)`. That loses half-cent correctness, such as 1.005.

Now PostgreSQL sums the original amounts, then Decimal rounds the report once
with ROUND_HALF_UP. 333.333 plus 333.333 plus 333.334 is exactly 1000.00, not
999.99 from rounding individual bookings. Positive and negative half-cent
tests cover the rounding rule.

The numeric total remains for compatibility; an additive exact string drives
the display. The frontend formats integer digits and cents without binary
money arithmetic. Mixed currencies are explicitly rejected rather than
silently relabelled USD."

## 4:45-6:15 - Verification

**Show:** the actual backend test output, frontend precision tests, Docker
service status, and saved baseline comparisons.

"The expanded backend suite has 19 passing tests, including the opt-in test
against real PostgreSQL and Redis with both supplied accounts. It exercises
cache hits in both orders, foreign-property denial, DST boundaries, exact
aggregation, invalid inputs, forged tokens, and expiry after warming the auth
cache. The five frontend precision/tenant-claim tests pass. The existing Vite production
build succeeds, and the Docker frontend and backend respond successfully.

I also ran lint and TypeScript checks rather than assuming the build implied
type safety. Repository-wide checks were already failing. I compared the
original source against the fixed source: no new diagnostics were introduced.
The original unrelated failures remain and are clearly reported; I did not
weaken rules or refactor the rest of the application."

Use the final assessment summary for the final diagnostic counts; do not
describe repository-wide lint or type checks as passing.

## 6:15-7:00 - Delivery and limits

**Show:** `git status`, `git log -1`, and the commit on the personal fork.

"The changes, regression tests, and documentation are committed and pushed
only to my fork. No new real credentials, tokens, environment files,
dependency folders, or generated frontend bundles are committed.

This remains the original assessment application, not a rebuild. The
development fixtures and public sample Docker credentials are not suitable
for production. A production Supabase connection was not available for an
end-to-end production-login check; password verification has regression
coverage with a controlled auth response. Existing repository-wide lint/type
issues and dependency audit warnings are outside these targeted fixes."
