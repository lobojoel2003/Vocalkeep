# Contributing to Vocalkeep

Thank you for helping. Vocalkeep is used by people at a hard time in their lives, so the bar is
simple: **it must be gentle, reliable and private.**

## Ways to help

- **Try it and tell us** what was confusing, tiring or broken ([open an issue](https://github.com/lobojoel2003/Vocalkeep/issues/new/choose)).
  Please never attach recordings or voice banks.
- **Words**: everything the app says should be short, plain and kind. Suggestions are welcome.
- **Sentence sets for other languages**: original or permissively licensed sentences, reviewed by
  a native speaker (see `shared/prompts/` and `scripts/annotate_prompts.py`).
- **Code**: the app (Rust + Svelte), the core library, or the voice builder (Python).

## Development setup

You need Rust (the version in `rust-toolchain.toml` is installed automatically), Node.js 20+,
and Python 3.10+. On Linux, Tauri also needs:

```bash
sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev libasound2-dev patchelf
```

### Recording app

```bash
cd desktop
npm install
npm run tauri dev        # the real app
npm run dev              # just the interface in a browser, with a demo voice bank
```

Checks (all run in CI):

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cd desktop && npm run lint && npm run check && npm test && npm run build
```

### Voice builder

```bash
cd pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy src && pytest
```

### Shared data

- Change thresholds in `shared/quality.json`, then run `python3 scripts/sync-shared.py` to update
  the Python package's copy. Both implementations are tested against `shared/fixtures/`.
- After editing sentence sets, run `python3 scripts/annotate_prompts.py` (needs `espeak-ng`).
- `python3 scripts/make_fixtures.py` regenerates the test recordings.

### Screenshots

The README screenshots are rendered from the interface's demo mode:

```bash
cd desktop && npm run dev &
NODE_PATH=$(npm root -g) npm run screenshots
```

## Pull requests

- Keep changes focused, with tests for behaviour changes.
- Use [Conventional Commits](https://www.conventionalcommits.org/) for messages
  (`feat:`, `fix:`, `docs:`, `ci:`, `chore:`…).
- Add a line under `## [Unreleased]` in `CHANGELOG.md` for anything people will notice.
- By contributing you agree your work is released under GPL-3.0-or-later (sentence sets under CC0).

See [docs/architecture.md](docs/architecture.md) for how the pieces fit together and
[docs/releasing.md](docs/releasing.md) for versions and releases.
