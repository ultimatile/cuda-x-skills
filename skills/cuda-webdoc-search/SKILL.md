---
name: cuda-webdoc-search
description: Search CUDA-X library documentation (cuBLAS, cuTENSOR, cuTensorNet, cuSOLVER, etc.) to find API symbols, functions, and types. Use when you need to look up CUDA library APIs, discover available functions, or find documentation URLs for specific operations.
---

# CUDA-X Documentation Search Guide

## Overview

Search and discover APIs across CUDA-X library documentation by querying Sphinx inventory files. Use this skill when you need to find specific CUDA library functions, check available APIs, or get documentation links.

## When to Use

- Finding CUDA library APIs (e.g., "what SVD functions does cuTensorNet have?")
- Checking if a specific function exists in a library
- Getting documentation URLs for CUDA APIs
- Exploring available operations in a library

## Quick Reference

### Check Available Domains First

Before searching, check what domains (API types) are available:

```bash
uv run cws search <library> --stats
```

This returns domain counts: `cpp` (C++ APIs), `c` (C APIs), `py` (Python bindings), `std` (doc labels).

### Search for APIs

```bash
uv run cws search <library> --domains <domain> --keywords "<terms>" --fuzzy --limit 20
```

### Keyword Syntax (fzf subset)

- Space-separated terms are **AND** (all must match): `--keywords "SVD batch"`
- Use `|` for **OR** (requires shell quoting): `--keywords "SVD | QR"`
- AND binds tighter than OR: `--keywords "a b | c"` = (a AND b) OR c
- **Note**: Only AND/OR via `|` is supported. fzf operators `^`, `'`, `!`, `$` are not available.

### Available Libraries

See `registry.toml` for the full list. Common ones:

- `cuquantum` - cuTensorNet, cuStateVec (quantum/tensor network)
- `cublas` - BLAS operations
- `cusolver` - Dense/sparse solvers
- `cusparse` - Sparse matrix operations
- `cufft` - FFT operations
- `cudnn` - Deep learning primitives
- `cutlass` - GEMM templates
- `cuda_math` - Math functions

## Workflow

1. **Identify the library**: Determine which CUDA library likely contains the API
2. **Check domains**: Run `--stats` to see available domain types
3. **Search**: Use `--keywords` with `--fuzzy` for flexible matching
4. **Filter by domain**: Use `--domains cpp` for C++ APIs, `--domains c` for C APIs
5. **Extract details**: Use `cws get` to get full documentation content

## Examples

### Find tensor decomposition APIs in cuTensorNet

```bash
uv run cws search cuquantum --stats
# Shows: cpp:3179, py:1172, std:3378, c:4

uv run cws search cuquantum --domains cpp --keywords "SVD" --fuzzy --limit 10
# Returns: cutensornetTensorSVD, etc. (functions ranked above enumerators)

uv run cws search cuquantum --domains cpp --keywords "SVD | QR" --fuzzy
# Returns: entries matching SVD OR QR
```

### Search across multiple libraries

```bash
# "Where is SVD in CUDA-X?" — search cuSOLVER and cuDSS together
uv run cws search cusolver cudss --keywords "svd" --fuzzy --limit 10

# Mix any number of sources
uv run cws search cusolver cusparse cudss --keywords "solve" --fuzzy
```

Multi-source output uses `"sources"` (list) instead of `"source"` (string), and `"total_found"` becomes a per-source dict.

### Find GEMM functions in cuBLAS

```bash
uv run cws search cublas --stats
# Shows: std:36 (only doc labels, no cpp/c domain)

uv run cws search cublas --domains std --keywords "gemm"
# Returns: cublas-t-gemm, cublas-t-gemmex, etc. (doc section labels)
```

### Extract API documentation details

After finding a function URL, extract its full documentation:

```bash
uv run cws get <url> --section <function_name>
```

Example:

```bash
uv run cws get \
  "https://docs.nvidia.com/cuda/cuquantum/latest/cutensornet/api/functions.html" \
  --section "cutensornetTensorSVD"
```

Output is a brace-delimited text tree:

```
{
cutensornetTensorSVD
{
cutensornetStatus_t cutensornetTensorSVD {
const cutensornetHandle_t handle
const cutensornetTensorDescriptor_t descTensorIn
...
}
Performs SVD decomposition of a tensor. { ... }
Parameters { ... }
}
}
```

### Audit registry health

```bash
uv run cws audit                    # audit all sources
uv run cws audit --source cublas    # audit single source
```

## Output Format

### cws search

JSON output includes:

Single source:
- `source`: Library name (string)
- `total_found`: Total APIs in filtered domains
- `filtered_count`: APIs matching keywords
- `candidates`: List of matching APIs with `group` (name), `url`, `domain`, `role`

Multi-source (`cws search A B`):
- `sources`: Library names (list)
- `total_found`: Per-source totals (dict)
- `filtered_count`: Total APIs matching keywords across all sources
- `candidates`: Merged list (k-way merge by score if `--fuzzy`, else concatenated)

### cws get

Brace-delimited text tree where:
- `{` `}` denote hierarchy
- Text content is preserved
- Inline elements (code, links) are flattened to text

Options:
- `--section <id>`: Extract only a specific section
- `--main-only`: Extract only the main content area

## Files

- `cli.py` - Unified CLI entry point (`cws`)
- `search.py` - Search APIs across library inventories
- `audit.py` - Audit registry entries for endpoint health
- `get.py` - Extract documentation content as text tree
- `fetchers.py` - Data fetching for Sphinx/Doxygen sources
- `scoring.py` - Search ranking and filtering logic
- `registry.py` - Registry loading utility
- `registry.toml` - Library metadata (URLs, doc types)
