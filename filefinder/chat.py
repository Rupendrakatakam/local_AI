"""
chat.py — Terminal chat interface for FileChat.
Usage: python chat.py
"""

import sys
import datetime
from search import search, db_stats, FileResult
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style

console = Console()

PROMPT_STYLE = Style.from_dict({
    "prompt": "bold ansigreen",
})

HELP_TEXT = """
[bold cyan]FileChat[/bold cyan] — Find any file in your home directory

[bold]Examples:[/bold]
  where is resume.pdf
  find my python scripts
  where is that notes file
  show me all PDFs
  find config.json

[bold]Commands:[/bold]
  [yellow]help[/yellow]    Show this message
  [yellow]stats[/yellow]   Show index statistics
  [yellow]exit[/yellow]    Quit
"""


def fmt_mtime(mtime: float) -> str:
    return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")


def display_results(results: list[FileResult]) -> None:
    if not results:
        console.print(Panel("[yellow]No files found.[/yellow] Try different keywords.", border_style="yellow"))
        return

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        show_lines=False,
    )
    table.add_column("#",         style="dim",          width=3,  justify="right")
    table.add_column("File Name", style="bold green",   min_width=20)
    table.add_column("Path",      style="white",        min_width=30)
    table.add_column("Size",      style="cyan",         width=9,  justify="right")
    table.add_column("Modified",  style="dim",          width=17)

    for i, r in enumerate(results, 1):
        table.add_row(str(i), r.name, r.path, r.size_human, fmt_mtime(r.mtime))

    console.print(table)
    console.print(f"[dim]  {len(results)} result(s)[/dim]\n")


def show_stats() -> None:
    s = db_stats()
    if not s["ready"]:
        console.print("[red]Index not ready. Is the indexer running?[/red]")
        return
    console.print(Panel(
        f"[green]✓[/green] Index is ready\n"
        f"[cyan]{s['total']:,}[/cyan] files indexed\n"
        f"[dim]DB: {s['db_path']}[/dim]",
        title="Index Stats",
        border_style="cyan",
        width=60,
    ))


def main() -> None:
    console.print(Panel(
        Text.from_markup(
            "[bold cyan]FileChat[/bold cyan]  [dim]powered by phi3:mini[/dim]\n"
            "[dim]Type [/dim][yellow]help[/yellow][dim] for usage, [/dim][yellow]exit[/yellow][dim] to quit.[/dim]"
        ),
        border_style="cyan",
        width=60,
    ))

    # Quick index check
    s = db_stats()
    if not s["ready"]:
        console.print("[yellow]⚠ Index not found. Make sure indexer.py is running.[/yellow]\n")
    else:
        console.print(f"[dim]  Index ready — {s['total']:,} files[/dim]\n")

    session = PromptSession()

    while True:
        try:
            query = session.prompt([("class:prompt", " You ❯ ")], style=PROMPT_STYLE).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            sys.exit(0)

        if not query:
            continue

        low = query.lower()

        if low in ("exit", "quit", "bye", "/bye"):
            console.print("[dim]Goodbye.[/dim]")
            break

        if low == "help":
            console.print(HELP_TEXT)
            continue

        if low == "stats":
            show_stats()
            continue

        with console.status("[cyan]Searching…[/cyan]", spinner="dots"):
            results = search(query)

        display_results(results)


if __name__ == "__main__":
    main()
