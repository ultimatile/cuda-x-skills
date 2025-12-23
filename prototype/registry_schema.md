# Registry Schema (TOML)

This document defines the minimal TOML schema for library registry entries used by the mapper/extractor.

## Top-level

The file is a list of `[[library]]` tables.

## Required fields

- `name` (string): Stable key used by CLI and code (e.g. `--source cccl`). Treat as immutable.
- `doc_type` (string): Parser strategy. Allowed values:
  - `sphinx`
  - `doxygen`
  - `mdbook`
  - `custom`

At least one of the following must be present:
- `inventory_urls` (array of string): Sphinx inventory endpoints (objects.inv).
- `index_url` (string): Entry point HTML page for index scraping.

## Optional fields

- `description` (string): Human-readable label used in logs/UI.
- `base_urls` (array of string): Base URLs for resolving relative links.
- `match_threshold` (float): Fuzzy match threshold (0-100). Default: 60.0
- `enabled` (bool): Toggle entry. Default: true
- `tags` (array of string): Free-form metadata, e.g. `["open", "vendor:nvidia"]`.
- `auth` (string): Authentication hint, e.g. `none`, `cookie`, `token`.

## Example

```toml
[[library]]
name = "cccl"
description = "CCCL libcudacxx"
doc_type = "sphinx"
inventory_urls = [
  "https://nvidia.github.io/cccl/libcudacxx/objects.inv",
  "https://nvidia.github.io/cccl/objects.inv"
]
base_urls = [
  "https://nvidia.github.io/cccl/libcudacxx/",
  "https://nvidia.github.io/cccl/"
]
match_threshold = 60.0
tags = ["open", "vendor:nvidia"]
```
