# Developer Assignment: Property Revenue Dashboard

## Background

You've joined our property management team as a junior developer. Our company manages properties for multiple clients across different time zones, and we've recently launched a new revenue dashboard system.

## The Situation

Yesterday, our CEO received some concerning calls from two of our biggest clients:

**Client A (Sunset Properties)** called saying: *"The revenue numbers on your dashboard don't match our internal records. We're showing different totals for March, and we're worried about accuracy for our board meeting next week."*

**Client B (Ocean Rentals)** mentioned: *"Something strange is happening - sometimes when we refresh the page, we see revenue numbers that look like they belong to another company. This is a serious privacy concern."*

Additionally, our finance team mentioned they've noticed some revenue totals that seem "slightly off" by a few cents here and there, but they couldn't pin down exactly when or why.

## Your Assignment

The development lead is tied up with another critical project, so you've been asked to investigate these issues. The system went live recently and there might be some bugs that weren't caught during initial testing.

**Your job**: Figure out what's going wrong and fix it.

## What You Have

### Environment Setup
```bash
# Start the development environment
docker-compose up --build

# Access the application
# Frontend: http://localhost:3000  
# Backend API: http://localhost:8000/docs
```

### Client Access Credentials

To investigate the issues, you have access to both client accounts:

**Client A (Sunset Properties)**
```
Email: sunset@propertyflow.com
Password: client_a_2024
```

**Client B (Ocean Rentals)**  
```
Email: ocean@propertyflow.com
Password: client_b_2024
```

### System Overview
- Multi-tenant architecture with isolated client data
- Revenue calculations based on property reservations
- Caching layer for improved performance
- Properties located in different time zones globally
- Financial reporting for monthly and annual summaries

## The Data

The system currently manages:
- Several property management companies as clients
- Multiple properties per client (some with similar naming/IDs)
- Reservation bookings with various amounts and currencies
- Properties spanning different time zones (Paris, New York, etc.)

## What's Expected

1. **Investigate** the reported issues by logging in as each client
2. **Identify** any bugs in the system
3. **Fix** the problems you find
4. **Create a Loom video** (5-10 minutes max) explaining your findings and fixes

## Deliverables

### Video Walkthrough (Required)
Record a **concise Loom video** demonstrating:
- What bugs you discovered and how you found them
- The root cause of each issue
- Your fix for each problem
- A quick demonstration that the fixes work

**Keep it short**: 5-10 minutes maximum. We value clarity and conciseness.

### Important Notes
- **Do NOT rebuild the system** - this is a debugging exercise
- Focus on identifying and fixing existing code issues
- Use the existing codebase structure and patterns
- Test your fixes with the provided client credentials

## Technical Notes

The codebase includes:
- Backend services for revenue calculations
- Caching mechanisms for performance
- Frontend dashboard for displaying data
- Database with client and property information

All the code, database schema, and sample data are provided in this repository.

---

**Important**: The clients are expecting a resolution quickly. Take your time to understand the system, but remember that data accuracy and privacy are critical in property management.

Good luck!

## Fixed revenue behavior and verification

Revenue is recognized in the **property's local calendar month of check-in**.
The backend converts the first local midnight of that month and the next month
independently to UTC and queries the half-open interval `[start, end)`. This
accounts for DST without using the server's timezone.

`GET /api/v1/dashboard/summary?property_id=prop-001&month=3&year=2024`
returns a monthly report. Omitting both date parameters preserves the original
all-time summary. Supplying only one date parameter is rejected.

The existing numeric `total_revenue` field is preserved. The additive
`total_revenue_exact` string contains the exact two-decimal report total; the
frontend formats this string without floating-point arithmetic. PostgreSQL
`NUMERIC` values are summed before one `Decimal`/`ROUND_HALF_UP` rounding step.
Different currencies are not silently combined; mixed-currency reports return
HTTP 422 rather than inventing an exchange rate.

All property and reservation queries include the authenticated tenant. Redis
keys include tenant, property, and reporting period, use a new namespace that
does not read old tenant-free entries, and validate cached ownership. Missing
tenant context fails closed. Database/cache outages return HTTP 503, not mock
financial figures. Browser financial requests bypass session caches, and stale
UI responses are discarded when the account or report changes.

The supplied accounts are development fixtures, enabled only with
`ENVIRONMENT=development` and no configured Supabase URL. Non-fixture logins
verify the password through Supabase. Tokens require a valid signature and
expiry even on authentication cache hits. Production must configure its own
private `SECRET_KEY` (at least 32 bytes); the public development key is rejected
outside development. The sample Docker configuration is not a production
deployment.

### Regression tests

No additional test framework is required: backend tests use Python `unittest`;
frontend tests use Node's built-in test runner.

```powershell
docker compose up --build -d
docker compose exec -T backend python -m unittest discover -s tests -v
```

The database/Redis integration test is opt-in. To run it with both supplied
accounts without copying credentials into new source files:

```powershell
$accounts = [regex]::Matches((Get-Content ASSIGNMENT.md -Raw), 'Email: (\S+)\s+Password: (\S+)')
$env:CLIENT_A_EMAIL = $accounts[0].Groups[1].Value
$env:CLIENT_A_PASSWORD = $accounts[0].Groups[2].Value
$env:CLIENT_B_EMAIL = $accounts[1].Groups[1].Value
$env:CLIENT_B_PASSWORD = $accounts[1].Groups[2].Value
docker compose exec -T -e RUN_REVENUE_INTEGRATION=1 -e CLIENT_A_EMAIL -e CLIENT_A_PASSWORD -e CLIENT_B_EMAIL -e CLIENT_B_PASSWORD backend python -m unittest discover -s tests -v
```

With frontend dependencies installed, run `npm run test:revenue` from
`frontend`. In this assessment, frontend validation ran inside the existing
Docker build stage to avoid changing the repository's tracked `node_modules`.

Integration coverage includes both account logins and identity endpoints,
cache misses/hits in both client orders, the shared property ID, denied foreign
properties, Paris and New York DST/month boundaries, sub-cent aggregation,
mixed currencies, invalid date parameters, forged tokens, and expiry after
warming the auth cache. Temporary fixture rows and their cache entries are
removed afterward. Sunset's seeded March `prop-001` report is **2250.00 with
four reservations**; Ocean's own `prop-001` has **0.00 and zero reservations**.

### Existing validation limitations

The original source already fails repository-wide lint/type checks. Baseline
comparison found 333 TypeScript diagnostic lines, 579 ESLint errors and 31
warnings, and 109 Ruff diagnostics. These unrelated issues were not swept into
the revenue fix. See the walkthrough for the verified final results and
remaining limitations.