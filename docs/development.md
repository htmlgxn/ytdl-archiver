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
