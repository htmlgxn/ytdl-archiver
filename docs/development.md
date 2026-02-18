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
```

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
│   ├── textual_app.py
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
