# CUDA-X Skills Repository

Custom skills for Claude to search CUDA-X library documentation.

## cuda-webdoc-search

When working with CUDA-X libraries (cuBLAS, cuTENSOR, cuTensorNet, cuSOLVER, etc.), coding agents can search their documentation to find relevant APIs, check function signatures, and provide direct links to official docs.

### Install

```bash
uv tool install "cuda-webdoc-search @ git+https://github.com/ultimatile/cuda-x-skills.git#subdirectory=skills/cuda-webdoc-search"
```

```bash
cws search cuquantum --keywords "SVD" --fuzzy --limit 10
cws audit --source cublas
```

See [skills/cuda-webdoc-search/README.md](skills/cuda-webdoc-search/README.md) for full usage and development instructions.

## Skills Installation (for Claude Code / Codex)

```bash
claude plugin marketplace add ultimatile/cuda-x-skills
claude plugin install cuda-x-skills
```
