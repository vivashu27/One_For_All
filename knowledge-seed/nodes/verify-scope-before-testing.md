---
id: verify-scope-before-testing
title: Verify scope and rules before touching anything
type: lesson
tags: [scope, rules-of-engagement, safety, ethics, process]
vuln_class: []
related: [recon-attack-surface-workflow, impact-first-reporting]
confidence: seed
reinforced: 0
created: 2026-10-11
updated: 2026-10-11
source: seed
---

# Verify scope and rules before touching anything

**Summary:** The fastest way to waste an assessment — or get banned/legal-ed — is to
test an out-of-scope asset or break a program rule. Confirm scope first, every time.

## What happens when you skip it
Hours burned on an out-of-scope subdomain; valid-looking bugs marked N/A; automated
scanning on a program that forbids it; destructive testing on prod data.

## Takeaway
Before recon or testing, read and pin:
- In-scope vs out-of-scope assets (domains, apps, APIs, mobile) — wildcards included.
- Prohibited actions (automated scanning rate limits, DoS, social engineering,
  physical, data exfil limits).
- Required markers: test-account rules, and any mandated identifier in a custom
  header (for attested/Intigriti/HackerOne programs, include the required username).
- Which test email to register with per the program/platform.

## Apply next time
Keep a one-line scope note at the top of the engagement; re-check before any new
asset. When demonstrating impact, use the **minimum** proof needed — don't pivot
into real third-party data. Feed confirmed in-scope surface into
[[recon-attack-surface-workflow]].

## Related
[[recon-attack-surface-workflow]] — scope gates recon · [[impact-first-reporting]]
— scope-correct proof makes reports accepted faster.
