# Development

## Running Tests
```bash
uv run pytest
```

## Code Quality
```bash
uv run ruff check src tests
uv run ruff format src tests
uv run ty src
```

## Project Structure
```
src/ytdl_archiver/
├── config/          # Configuration management
├── core/            # Core functionality
├── cli.py           # Command line interface
└── exceptions.py    # Custom exceptions

tests/
├── test_cli/         # CLI tests
├── test_config/       # Configuration tests
├── test_core/         # Core functionality tests
├── test_integration/  # Integration tests
└── conftest.py       # Test configuration
```
