"""CUDA-X Documentation Search Tools — unified CLI entry point."""

from importlib.metadata import version
from typing import Annotated, Optional

import typer

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


if __name__ == "__main__":
    app()
