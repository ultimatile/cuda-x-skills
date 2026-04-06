# cuda-webdoc-search

Search CUDA-X library documentation (cuBLAS, cuTENSOR, cuSOLVER, etc.) to find API symbols, functions, and types.

## Installation

### As a standalone tool (recommended)

```bash
uv tool install "cuda-webdoc-search @ git+https://github.com/ultimatile/cuda-x-skills.git#subdirectory=skills/cuda-webdoc-search"
```

`cws` is then available globally:

```bash
cws search cuquantum --keywords "SVD" --fuzzy --limit 10
cws audit --source cublas
cws get https://docs.nvidia.com/... --section "cutensornetTensorSVD"
```

To uninstall:

```bash
uv tool uninstall cuda-webdoc-search
```

### One-shot with uvx

No installation needed — runs in a temporary environment:

```bash
uvx --from "cuda-webdoc-search @ git+https://github.com/ultimatile/cuda-x-skills.git#subdirectory=skills/cuda-webdoc-search" cws search cublas --stats
```

## Subcommands

| Command | Description |
|---------|-------------|
| `cws search` | Search API symbols across CUDA-X library documentation |
| `cws audit` | Audit registry entries for endpoint health |
| `cws get` | Extract documentation content as brace-delimited text tree |

Run `cws <command> --help` for full option details.

## Quick examples

```bash
# Check what domains a library has
cws search cuquantum --stats

# Fuzzy search for SVD functions in C++ APIs
cws search cuquantum --domains cpp --keywords "SVD" --fuzzy --limit 10

# Cross-library search
cws search cusolver cudss --keywords "svd" --fuzzy --limit 10

# Extract documentation for a specific function
cws get "https://docs.nvidia.com/cuda/cuquantum/latest/cutensornet/api/functions.html" \
  --section "cutensornetTensorSVD"

# Audit all registry entries
cws audit
```

## Registry

Library metadata is defined in `registry.toml`. Each entry specifies:
- Documentation source type (`sphinx`, `doxygen`, `sphinx_noinv`, `pdf`)
- Inventory/index URLs
- Tags for alias resolution (e.g., `thrust` resolves to `cccl`)

See `registry.toml` for the full list of supported libraries.

## Development

From this directory:

```bash
uv run cws search cublas --stats   # run locally
uv run pytest tests/               # tests
uv run pytest tests/ --cov         # tests with coverage
```
