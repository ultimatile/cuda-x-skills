# CUDA-X Skills Repository

Custom skills for Claude to search CUDA-X library documentation.

## cuda-webdoc-search

When working with CUDA-X libraries (cuBLAS, cuTENSOR, cuTensorNet, cuSOLVER, etc.), coding agents can search their documentation to find relevant APIs, check function signatures, and provide direct links to official docs.

## Installation

```bash
# For Claude Code (~/.claude/skills/)
./install-skills.sh --all

# For Codex (~/.codex/skills/)
./install-skills.sh --codex --all

# Symlink for development
./install-skills.sh --symlink --all
```

## Testing

```bash
cd skills/cuda-webdoc-search
uv run --group test pytest tests/ -v
```

With coverage:

```bash
uv run --group test pytest tests/ --cov=. --cov-report=term-missing
```
