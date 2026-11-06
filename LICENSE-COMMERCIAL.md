# KERN — Commercial License

Copyright (c) 2026 Vital Kalinousky. All rights reserved.

KERN is **dual-licensed** (the standard model for infrastructure that is free for
open source and paid for in closed products):

| Use | License |
|:--|:--|
| Open source, research, teaching, evaluation, personal projects | **GNU AGPL-3.0-or-later** — free of charge, full source in `LICENSE` |
| Embedding in a **closed** product, closed CI/CD pipeline, or a network service whose source you do not publish | **Commercial license — required** (this file) |
| SaaS / hosted verification where users interact with KERN over a network | **Commercial license — required** (AGPL §13 would otherwise force you to publish your whole integration) |

## Why AGPL and not a permissive license

AGPL keeps KERN 100% open source and OSI-approved, while closing the loophole
where a company ships a closed service built on it and publishes nothing. If your
lawyers cannot accept AGPL, that is exactly the case this commercial license
exists for.

## What a commercial license grants

* use inside closed-source products and internal pipelines, without the AGPL
  obligation to publish your integration;
* no copyleft on your own code that merely links to or calls `kernc`/`kerna`;
* a written statement of the **exact guarantees and named limits** of the version
  you ship (see `docs/LIMITS.md`) — KERN never claims more than it proves;
* priority on fixes for defects you report.

## What it does NOT change

Verification results are statements about the code that was checked, with the
limits named in `docs/LIMITS.md` (`trusted > 0` for bit-vector proofs, `known_fp`
for false accusations, `skipped` for what was not modelled). No license buys a
claim the tool cannot back with a measurement.

## Contact

Open an issue titled `commercial license` in the repository, or contact the
copyright holder directly. Nothing here is legal advice; a signed agreement
replaces this page.
