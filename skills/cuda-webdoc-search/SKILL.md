---
name: cuda-webdoc-search
description: CUDA-X library documentation search and topology mapping tool. Searches across CUDA libraries (cuBLAS, cuFFT, cuDNN, etc.) using Sphinx inventory files and provides intelligent cross-library navigation.
license: MIT
---

# CUDA-X Documentation Search

## Overview

This skill provides intelligent search and navigation across CUDA-X library documentation. It uses Sphinx inventory files to enable cross-library symbol lookup and provides topology mapping for related functions across different CUDA libraries.

## Features

- **Cross-library search**: Find symbols across cuBLAS, cuFFT, cuDNN, TensorRT, and other CUDA-X libraries
- **Topology mapping**: Discover related functions and concepts across libraries
- **Registry-based**: Configurable library registry with metadata and documentation URLs
- **Fuzzy matching**: Intelligent symbol matching with similarity scoring

## Quick Start

```bash
# Search for a symbol across all libraries
uv run topology_mapper.py --keywords "cublasGemm"

# Extract structure from specific library
uv run structure_extractor.py --library cublas
```

## Registry Configuration

The `registry.toml` file contains metadata for all supported CUDA-X libraries:

```toml
[[library]]
name = "cublas"
description = "GPU-accelerated basic linear algebra (BLAS) library"
doc_type = "sphinx"
inventory_urls = ["https://docs.nvidia.com/cuda/cublas/objects.inv"]
base_urls = ["https://docs.nvidia.com/cuda/cublas/"]
```

## Scripts

- `topology_mapper.py`: Main search and mapping functionality
- `structure_extractor.py`: Library structure extraction and analysis
- `registry.toml`: Library registry configuration
- `references/registry_schema.md`: Registry format specification
