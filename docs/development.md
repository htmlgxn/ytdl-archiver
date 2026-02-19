# Development

## Setup
```bash
uv sync --dev
```

## Run tests
```bash
uv run pytest
```

## Code quality
```bash
uv run ruff check .
uv run ruff format .
uv run ty check .
```

## Documentation maintenance
When changing behavior, update docs in the same change:
- `README.md` for quickstart/onboarding
- `docs/cli.md` for command/env reference
- `docs/configuration.md` for config semantics and defaults
- `MIGRATION.md` only for legacy-delta migration notes

Validation checks:
```bash
UV_CACHE_DIR=.uv-cache ytdl-archiver --help
UV_CACHE_DIR=.uv-cache ytdl-archiver archive --help
UV_CACHE_DIR=.uv-cache ytdl-archiver init --help
```

## Setup wizard (`ratatui`) development
Build and stage the setup wizard binary:
```bash
cargo build --manifest-path rust/setup_tui/Cargo.toml --release
python scripts/stage_setup_tui_binary.py
```

Staged binaries are copied to `src/ytdl_archiver/setup/bin/` and bundled in wheels using a platform-tagged name (example: `ytdl-archiver-setup-tui-linux-x86_64`).

Source installs can auto-build on setup execution unless disabled with:
```bash
YTDL_ARCHIVER_SETUP_TUI_AUTOBUILD=0
```

Manual wizard dev run (`cargo run` without args is expected to fail):
```bash
cargo run --manifest-path rust/setup_tui/Cargo.toml -- \
  --defaults /tmp/defaults.json \
  --result /tmp/result.json
```

Useful setup env vars:
- `YTDL_ARCHIVER_SETUP_TUI_BIN`: explicit setup binary path
- `YTDL_ARCHIVER_SETUP_TUI_AUTOBUILD`: enable/disable runtime auto-build (`1`/`0`)
- `YTDL_ARCHIVER_SETUP_TUI_BUILD_TIMEOUT`: auto-build timeout seconds (default `300`)

## Release packaging
Release CI is defined in `.github/workflows/release.yml` and does:
1. Build/stage setup binaries on each supported platform runner.
2. Collect binaries into a single wheel build job.
3. Build `sdist` and wheel with bundled setup binaries.
4. Verify wheel contents include all expected setup binaries.
5. Publish to PyPI on `v*` tags (Trusted Publishing).

Current constraint:
- `macos-x86_64` is temporarily excluded because the available GitHub-hosted runner configuration for Intel macOS is not currently supported in this repository/org environment.
- TODO: re-enable `macos-x86_64` once runner support is restored or a self-hosted Intel macOS runner is available.
- Release workflow checkout uses `persist-credentials: false` intentionally to avoid leaking GitHub auth headers into downstream Cargo Git/index operations.
- Release workflow forces `CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse` to avoid interactive Git auth prompts when resolving crates.

UI behavior notes:
- Normal terminal sizes render a centered one-page progressive form.
- Small terminals fall back to paged step-by-step rendering.
- Defaults prefer browser cookie refresh with Firefox preselected.

## Project structure
```text
src/ytdl_archiver/
├── __init__.py
├── __main__.py
├── cli.py
├── output.py
├── exceptions.py
├── config/
│   ├── defaults.toml
│   └── settings.py
├── setup/
│   ├── bin/
│   ├── fallback_prompts.py
│   ├── models.py
│   ├── ratatui_bridge.py
│   ├── runner.py
│   ├── templates.py
│   └── writer.py
└── core/
    ├── archive.py
    ├── cookies.py
    ├── downloader.py
    ├── metadata.py
    └── utils.py

docs/
├── index.md
├── cli.md
├── configuration.md
├── development.md
└── terminal-output.md

rust/
└── setup_tui/

install.sh
install.ps1

scripts/
└── stage_setup_tui_binary.py
```
