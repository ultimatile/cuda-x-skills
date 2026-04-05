"""CUDA-X Documentation Search Tools — unified CLI entry point."""

import typer

from audit import audit
from get import get_doc
from search import search

app = typer.Typer(help="CUDA-X Documentation Search Tools")

app.command("search")(search)
app.command("audit")(audit)
app.command("get")(get_doc)


if __name__ == "__main__":
    app()
