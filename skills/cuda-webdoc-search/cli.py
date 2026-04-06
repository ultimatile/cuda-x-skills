"""CUDA-X Documentation Search Tools — unified CLI entry point."""

import json as json_mod
import sys
from importlib.metadata import version
from typing import Annotated, Optional

import typer

import registry
from audit import audit
from get import get_doc
from search import search


def _version_callback(value: bool):
    if value:
        print(f"cws {version('cuda-webdoc-search')}")
        raise typer.Exit()


app = typer.Typer(help="CUDA-X Documentation Search Tools")


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = None,
):
    pass


app.command("search")(search)
app.command("audit")(audit)
app.command("get")(get_doc)


@app.command("list")
def list_sources(
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    registry_path: Annotated[
        str,
        typer.Option("--registry", help="Registry TOML path"),
    ] = registry.DEFAULT_REGISTRY_PATH,
):
    """List available documentation sources from the registry."""
    reg = registry.load_registry(registry_path)
    if isinstance(reg, str):
        print(f"Error: {reg}", file=sys.stderr)
        raise typer.Exit(1)

    libraries = reg.get("library", [])

    if json:
        entries = [
            {
                "name": lib.get("name", ""),
                "doc_type": lib.get("doc_type", ""),
                "description": lib.get("description", ""),
                "tags": lib.get("tags", []),
            }
            for lib in libraries
        ]
        print(json_mod.dumps(entries, indent=2))
    else:
        import shutil

        cols = shutil.get_terminal_size((120, 24)).columns
        prefix_width = 20 + 14  # name + doc_type columns
        desc_width = max(cols - prefix_width, 20)
        print(f"{'name':<20} {'doc_type':<14} {'description'}")
        print("-" * min(cols, 120))
        for lib in libraries:
            name = lib.get("name", "")
            doc_type = lib.get("doc_type", "")
            desc = lib.get("description", "")
            tags = lib.get("tags", [])
            if tags:
                desc += f" [{', '.join(tags)}]"
            if len(desc) > desc_width:
                desc = desc[: desc_width - 3] + "..."
            print(f"{name:<20} {doc_type:<14} {desc}")


if __name__ == "__main__":
    app()
