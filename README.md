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

## Development

```bash
cd skills/cuda-webdoc-search
make check    # lint + typecheck + test
make test     # tests only
make coverage # tests with coverage report
make lint     # ruff check + format
make typecheck # pyright
```
