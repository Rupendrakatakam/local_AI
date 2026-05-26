"""
chat.py — Terminal chat interface for FileChat.
Batch 1 additions:
  - Ollama offline alert at startup (#8)
"""

import sys
import datetime
import subprocess
import requests
from pathlib import Path
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
  [yellow]help[/yellow]          Show this message
  [yellow]stats[/yellow]         Show index statistics
  [yellow]/open N[/yellow]       Open result N in its default app
  [yellow]/copy N[/yellow]       Copy path of result N to clipboard
  [yellow]exit[/yellow]          Quit
"""

_last_results: list[FileResult] = []


# ── Ollama health check (#8) ──────────────────────────────────────────────────
def check_ollama() -> bool:
    try:
        r = requests.get("http://localhost:11434", timeout=3)
        return r.status_code < 500
    except Exception:
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────
def fmt_mtime(mtime: float) -> str:
    return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")


def tilde_path(path: str) -> str:
    """Replace /home/username with ~ for readability."""
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def display_results(results: list[FileResult]) -> None:
    global _last_results
    _last_results = results

    if not results:
        console.print(Panel(
            "[yellow]No files found.[/yellow] Try different keywords.",
            border_style="yellow"
        ))
        return

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        show_lines=False,
    )
    table.add_column("#",         style="dim",         width=3,  justify="right")
    table.add_column("File Name", style="bold green",  min_width=20)
    table.add_column("Path",      style="white",       min_width=30)
    table.add_column("Size",      style="cyan",        width=9,  justify="right")
    table.add_column("Modified",  style="dim",         width=17)

    for i, r in enumerate(results, 1):
        table.add_row(
            str(i), r.name, tilde_path(r.path),
            r.size_human, fmt_mtime(r.mtime)
        )

    console.print(table)
    console.print(f"[dim]  {len(results)} result(s) — /open N to open, /copy N to copy path[/dim]\n")


def show_stats() -> None:
    s = db_stats()
    if not s["ready"]:
        # Check if scan is still in progress
        boot_file = Path("/tmp/filefinder.booting")
        if boot_file.exists():
            count = boot_file.read_text().strip()
            console.print(Panel(
                f"[yellow]⏳ Initial scan in progress — {count} files indexed so far.[/yellow]\n"
                f"[dim]This only happens once after install. Wait a minute and try again.[/dim]",
                title="Index Stats", border_style="yellow", width=65,
            ))
        else:
            console.print("[red]Index not ready. Is the indexer running?[/red]")
        return

    ollama_ok = check_ollama()
    ollama_line = "[green]✓ Ollama online[/green]" if ollama_ok else "[yellow]⚠ Ollama offline — using fast regex fallback[/yellow]"

    console.print(Panel(
        f"[green]✓[/green] Index ready\n"
        f"[cyan]{s['total']:,}[/cyan] files indexed\n"
        f"[dim]DB: {s['db_path']}[/dim]\n"
        f"{ollama_line}",
        title="Index Stats",
        border_style="cyan",
        width=65,
    ))


def open_result(idx: int) -> None:
    if not _last_results or idx < 1 or idx > len(_last_results):
        console.print(f"[red]No result #{idx}. Run a search first.[/red]")
        return
    path = _last_results[idx - 1].path
    try:
        subprocess.Popen(["xdg-open", path])
        console.print(f"[green]Opening:[/green] {tilde_path(path)}")
    except FileNotFoundError:
        console.print("[red]xdg-open not found. Are you on a desktop environment?[/red]")


def copy_result(idx: int) -> None:
    if not _last_results or idx < 1 or idx > len(_last_results):
        console.print(f"[red]No result #{idx}. Run a search first.[/red]")
        return
    path = _last_results[idx - 1].path
    # Try xclip, then xsel
    for tool, args in [("xclip", ["-selection", "clipboard"]), ("xsel", ["--clipboard", "--input"])]:
        try:
            proc = subprocess.run([tool] + args, input=path.encode(), timeout=3)
            if proc.returncode == 0:
                console.print(f"[green]Copied to clipboard:[/green] {tilde_path(path)}")
                return
        except FileNotFoundError:
            continue
    console.print("[yellow]Install xclip or xsel for clipboard support:[/yellow] sudo apt install xclip")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    console.print(Panel(
        Text.from_markup(
            "[bold cyan]FileChat[/bold cyan]  [dim]powered by phi3:mini[/dim]\n"
            "[dim]Type [/dim][yellow]help[/yellow][dim] for usage, [/dim][yellow]exit[/yellow][dim] to quit.[/dim]"
        ),
        border_style="cyan",
        width=60,
    ))

    # (#8) Ollama check at startup
    if not check_ollama():
        console.print(Panel(
            "[yellow]⚠ Ollama is not running.[/yellow]\n"
            "[dim]Natural language search will fall back to fast regex matching.\n"
            "To enable full NL search: [/dim][cyan]ollama serve[/cyan]",
            border_style="yellow",
            width=60,
        ))
    else:
        console.print("[dim]  Ollama online ✓[/dim]")

    # Index check — show progress if still scanning
    s = db_stats()
    boot_file = Path("/tmp/filefinder.booting")
    if not s["ready"] and boot_file.exists():
        count = boot_file.read_text().strip()
        console.print(f"[yellow]  ⏳ Initial scan in progress ({count} files so far)…[/yellow]\n")
    elif s["ready"]:
        console.print(f"[dim]  Index ready — {s['total']:,} files[/dim]\n")
    else:
        console.print("[yellow]  ⚠ Index not found. Is the indexer running?[/yellow]\n")

    session = PromptSession()

    while True:
        try:
            query = session.prompt(
                [("class:prompt", " You ❯ ")], style=PROMPT_STYLE
            ).strip()
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

        # /open N
        if low.startswith("/open"):
            parts = low.split()
            if len(parts) == 2 and parts[1].isdigit():
                open_result(int(parts[1]))
            else:
                console.print("[yellow]Usage: /open N  (e.g. /open 2)[/yellow]")
            continue

        # /copy N
        if low.startswith("/copy"):
            parts = low.split()
            if len(parts) == 2 and parts[1].isdigit():
                copy_result(int(parts[1]))
            else:
                console.print("[yellow]Usage: /copy N  (e.g. /copy 1)[/yellow]")
            continue

        with console.status("[cyan]Searching…[/cyan]", spinner="dots"):
            results = search(query)

        display_results(results)


if __name__ == "__main__":
    main()