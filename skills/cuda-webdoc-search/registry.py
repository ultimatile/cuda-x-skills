"""Shared registry loading for cuda-webdoc-search scripts."""

import os
import tomllib

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REGISTRY_PATH = os.path.join(_SCRIPT_DIR, "registry.toml")


def load_registry(path):
    """Load registry TOML file.

    Returns:
        Parsed registry dict on success, or a string error message on failure.
    """
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return f"registry not found: {path}"
    except tomllib.TOMLDecodeError as e:
        return f"failed to parse registry {path}: {e}"
    except Exception as e:
        return f"failed to read registry {path}: {e}"
