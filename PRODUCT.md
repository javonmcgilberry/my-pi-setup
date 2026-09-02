# Product authority

This repository provides a small, deterministic way to reproduce Javon's Pi
configuration without owning the products that configuration installs.

## Requirements

- Preserve ordinary preferences changed through Pi while reapplying only
  manifest-declared managed settings.
- Install extension products through native Pi package sources.
- Keep the Webflow skill in the shared Agent Skills discovery root without a
  duplicate Pi skill registration.
- Keep routine updates free of commits and product test suites.
- Keep setup idempotent, dry-runnable, backup-aware, and drift-verifiable.
- Never copy credentials or runtime data into tracked configuration.

Product behavior belongs to the owning package repository. This repository
documents only installation, configuration, and recovery boundaries.
