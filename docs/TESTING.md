# Testing

<!-- Fill this in after BED-60 (scaffolding) is complete. -->

## Strategy

- TDD: tests written before implementation
- pytest with -x flag for fail-fast
- Test files co-located or in tests/ directory

## Running Tests

```bash
# Full suite
uv run pytest -x

# Single test
uv run pytest -x -k "test_name"

# With coverage
uv run pytest --cov=packages/parser/src
```

## Test Structure

<!-- Document test directory layout after scaffolding -->

## Fixtures

<!-- Document shared test fixtures (sample repos, map.json examples) -->
