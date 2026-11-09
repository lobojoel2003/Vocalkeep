## What this changes

<!-- A sentence or two, in plain words. -->

## Why

<!-- The problem it solves, or the issue it closes (Closes #…). -->

## How it was checked

- [ ] `cargo test --workspace` and `cargo clippy --workspace --all-targets -- -D warnings`
- [ ] `npm run lint && npm run check && npm test` in `desktop/`
- [ ] `ruff check . && mypy src && pytest` in `pipeline/`
- [ ] Tried in the app (screenshots welcome for interface changes)

## Notes for reviewers

<!-- Anything that needs a closer look: wording shown to people, licences, file formats. -->
