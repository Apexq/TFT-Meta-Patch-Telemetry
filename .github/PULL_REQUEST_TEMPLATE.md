## Summary

<!-- Describe what changed and why. -->

## Scope

- [ ] Django Web / Chat Platform (`apps/`, `templates/`, `config/`)
- [ ] Telemetry & RAG Engine (`src/`)
- [ ] CI / Workflows (`.github/`)
- [ ] Tests (`tests/`)

## Verification

- [ ] `python manage.py check` passes with zero errors
- [ ] `python manage.py makemigrations --check --dry-run` reports no missing migrations
- [ ] `pytest` passes cleanly without skipped assertions
- [ ] Verified no Riot policy violations (zero numerical augment win/placement metrics exposed)
- [ ] Verified no secrets, credentials, or local developer paths introduced
