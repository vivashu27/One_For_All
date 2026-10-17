---
id: idor-id-enumeration
title: IDOR via ID enumeration & swapping
type: technique
tags: [idor, bola, access-control, api, enumeration]
vuln_class: [idor, bola]
related: [broken-access-control, burp-autorize, impact-first-reporting]
confidence: seed
reinforced: 0
created: 2026-10-11
updated: 2026-10-11
source: seed
---

# IDOR via ID enumeration & swapping

**Summary:** Replace an object identifier that belongs to your account with one
belonging to another account/tenant; if the server returns or mutates their data,
it is an IDOR (BOLA).

## When to use
Any request carrying an object reference you don't strictly own: numeric IDs, UUIDs,
slugs, filenames, base64/hashed IDs, or IDs buried in JSON bodies and GraphQL vars.

## Steps
1. Create two accounts (A and B). Capture a request from A that references A's object.
2. Swap A's ID for B's ID while keeping A's session. Watch for B's data in the
   response, or a successful mutation on B's object.
3. If IDs look random (UUID/hash), check for leaks elsewhere (other endpoints,
   emails, referers) — a "guessable" bug often starts as an "exposed ID" bug.
4. Test every verb: an endpoint may block `GET` but allow `PUT`/`PATCH`/`DELETE`.
5. Escalate scope: user→user, then user→admin, then tenant→tenant.

## Gotchas
- A 200 with empty data ≠ vuln; confirm you actually received *their* data.
- Soft auth: some apps return the object but redact fields — field-level IDOR still counts.
- Don't act on real third-party/production data beyond minimal proof — see
  [[verify-scope-before-testing]].

## Seen working
Classic in REST APIs and multi-tenant SaaS; automate with [[burp-autorize]].

## Related
[[broken-access-control]] — parent class · [[burp-autorize]] — detection ·
[[impact-first-reporting]] — prove the cross-account impact in the report.
