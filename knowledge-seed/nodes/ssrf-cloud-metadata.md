---
id: ssrf-cloud-metadata
title: SSRF to cloud metadata / internal services
type: technique
tags: [ssrf, cloud, metadata, aws, gcp, oob]
vuln_class: [ssrf]
related: [recon-attack-surface-workflow, payloadsallthethings, impact-first-reporting]
confidence: seed
reinforced: 0
created: 2026-10-11
updated: 2026-10-11
source: seed
---

# SSRF to cloud metadata / internal services

**Summary:** Coerce the server into making requests you control the destination of,
then pivot to cloud metadata endpoints or internal services for high impact.

## When to use
Any feature that fetches a URL server-side: webhooks, URL preview/unfurl, PDF/HTML
to image, import-from-URL, avatar-by-URL, SSO metadata, file fetchers, XML parsers.

## Steps
1. Point the fetch at a collaborator/OOB host (Burp Collaborator, interactsh) to
   confirm the server dials out — even blind SSRF is confirmable this way.
2. Try internal targets: `http://169.254.169.254/latest/meta-data/` (AWS IMDSv1),
   `http://metadata.google.internal/computeMetadata/v1/` (GCP, needs
   `Metadata-Flavor: Google`), `http://127.0.0.1`, internal RFC1918 ranges.
3. Bypass filters: alternate IP encodings (decimal/octal/hex), DNS rebinding,
   `[::]`, redirects (open redirect → SSRF chain), and URL parser confusion.
4. If IMDSv2 blocks you, report the SSRF itself and pivot to internal service
   discovery and port scanning via the vulnerable fetch.

## Gotchas
- Many targets now use IMDSv2 (token-required) — blind SSRF may still reach other
  internal services; don't call it dead too early.
- Keep OOB interactions in-scope and minimal.

## Related
[[payloadsallthethings]] — SSRF bypass payloads · [[recon-attack-surface-workflow]]
— find the URL-fetching features · [[impact-first-reporting]] — show the credential
or internal-access impact, not just the ping.
