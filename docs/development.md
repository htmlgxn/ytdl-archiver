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

## Setup wizard (ratatui) development
Build the setup wizard binary:
```bash
cargo build --manifest-path rust/setup_tui/Cargo.toml --release
python scripts/stage_setup_tui_binary.py
```

The staged binary is copied into `src/ytdl_archiver/setup/bin/` and bundled into wheels.
The staging script writes a platform-tagged filename (for example,
`ytdl-archiver-setup-tui-linux-x86_64`) and the runtime bridge picks the matching one.
Source installs also try an auto-build fallback at setup runtime unless
`YTDL_ARCHIVER_SETUP_TUI_AUTOBUILD=0` is set.

The wizard binary requires file arguments. `cargo run` without args is expected to fail:
```bash
cargo run --manifest-path rust/setup_tui/Cargo.toml -- \
  --defaults /tmp/defaults.json \
  --result /tmp/result.json
```

UI behavior notes:
- Normal terminal sizes render a centered one-page progressive form (visual 4:3 target) with instructional section titles and dimmed inactive sections.
- Small terminals fall back to a paged step-by-step layout.
- Setup defaults prefer browser cookie import with Firefox preselected.

## Project structure
```text
src/ytdl_archiver/
├── cli.py
├── output.py
├── exceptions.py
├── config/
│   ├── defaults.toml
│   └── settings.py
├── setup/
│   ├── models.py
│   ├── templates.py
│   ├── writer.py
│   ├── fallback_prompts.py
│   └── runner.py
└── core/
    ├── archive.py
    ├── cookies.py
    ├── downloader.py
    ├── metadata.py
    └── utils.py

tests/
├── conftest.py
├── test_cli/
├── test_config/
├── test_core/
├── test_integration/
└── test_output/
```
