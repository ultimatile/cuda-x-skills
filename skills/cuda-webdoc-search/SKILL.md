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
uv run topology_mapper.py --source <library> --stats
```

This returns domain counts: `cpp` (C++ APIs), `c` (C APIs), `py` (Python bindings), `std` (doc labels).

### Search for APIs

```bash
uv run topology_mapper.py --source <library> --domains <domain> --keywords <terms> --fuzzy
```

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

## Examples

### Find tensor decomposition APIs in cuTensorNet

```bash
uv run topology_mapper.py --source cuquantum --stats
# Shows: cpp:3179, py:1172, std:3378, c:4

uv run topology_mapper.py --source cuquantum --domains cpp --keywords SVD QR --fuzzy
# Returns: cutensornetTensorSVD, cutensornetTensorQR, etc.
```

### Find GEMM functions in cuBLAS

```bash
uv run topology_mapper.py --source cublas --stats
# Shows: std:36 (only doc labels, no cpp/c domain)

uv run topology_mapper.py --source cublas --domains std --keywords gemm
# Returns: cublas-t-gemm, cublas-t-gemmex, etc. (doc section labels)
```

## Output Format

JSON output includes:

- `source`: Library name
- `total_found`: Total APIs in filtered domains
- `filtered_count`: APIs matching keywords
- `candidates`: List of matching APIs with `group` (name), `url`, `domain`, `role`

## Files

- `topology_mapper.py` - Main search script
- `registry.toml` - Library metadata (URLs, doc types)
- `structure_extractor.py` - Extract doc structure from a URL
