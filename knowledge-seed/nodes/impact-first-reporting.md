---
id: impact-first-reporting
title: Impact-first report writing
type: reporting
tags: [reporting, impact, cvss, poc, triage, process]
vuln_class: []
related: [idor-id-enumeration, oauth-account-takeover, ssrf-cloud-metadata, verify-scope-before-testing]
confidence: seed
reinforced: 0
created: 2026-10-11
updated: 2026-10-11
source: seed
---

# Impact-first report writing

**Summary:** Reports get accepted and paid faster when they lead with concrete
business impact and a clean, reproducible PoC — not with theory or hedging language.

## Principle
Triagers skim. Put the real-world consequence in the first two sentences, then prove
it. Avoid "could potentially / may allow / it might be possible" — state what you
*did* and what an attacker *gets*.

## Template
1. **Title** — vuln + asset + impact in one line.
2. **Summary / impact** — who can do what to whom, and why it matters to the business.
3. **Asset affected** — exact endpoint/parameter/component.
4. **Steps to reproduce** — numbered, copy-pasteable; include any **valid demo data**
   the repro needs (e.g. the specific `userID`/`orderID` values used), two test
   accounts where relevant, exact requests/responses.
5. **Proof of concept** — minimal evidence that a boundary was actually crossed
   (the other user's data returned, the token obtained) — not just a 200.
6. **Impact rating** — CVSS (incl. v4.0) with vector + short justification.
7. **Remediation** — specific, actionable fix.

## Avoid
- Theoretical/self-hedging language and missing repro data.
- Over-claiming severity without demonstrated impact (downgrades trust).
- Leaking unrelated third-party data in the PoC — keep proof minimal and in scope
  ([[verify-scope-before-testing]]).

## Related
Strong-impact write-ups for [[idor-id-enumeration]], [[oauth-account-takeover]],
[[ssrf-cloud-metadata]].
