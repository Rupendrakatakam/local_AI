"""
chat.py — Terminal chat interface for FileChat.
Batch 2 completions:
  - #7:  Persistent command history (arrow-up across sessions)
  - #2:  Pagination (10 results per page)
  - #21: ~ path expansion (already done, kept)
  - #3:  /open N  (already done, kept)
  - #4:  /copy N  (already done, kept)
Fixes:
  - Long filenames truncated cleanly with ellipsis instead of wrapping
  - Table adapts to terminal width
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
from prompt_toolkit.history import FileHistory      # #7

console = Console()

PROMPT_STYLE = Style.from_dict({"prompt": "bold ansigreen"})
HISTORY_FILE = Path.home() / ".config" / "filefinder" / "history"   # #7
PAGE_SIZE    = 10   # #2

HELP_TEXT = """
[bold cyan]FileChat[/bold cyan] — Find any file in your home directory

[bold]Search examples:[/bold]
  where is resume.pdf
  find my python scripts
  can you find the image named rupendra
  show me all PDFs

[bold]Commands:[/bold]
  [yellow]help[/yellow]          Show this message
  [yellow]stats[/yellow]         Show index statistics
  [yellow]/open N[/yellow]       Open result N in its default app
  [yellow]/copy N[/yellow]       Copy path of result N to clipboard
  [yellow]exit[/yellow]          Quit

[bold]Pagination:[/bold]  After results appear, press [yellow]n[/yellow] (next) / [yellow]p[/yellow] (prev) / [yellow]q[/yellow] (quit paging)
"""

_last_results:  list[FileResult] = []
_current_page:  int = 0
_total_pages:   int = 0


# ── Helpers ───────────────────────────────────────────────────────────────────
def check_ollama() -> bool:
    try:
        return requests.get("http://localhost:11434", timeout=3).status_code < 500
    except Exception:
        return False


def fmt_mtime(mtime: float) -> str:
    return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")


def tilde_path(path: str) -> str:
    home = str(Path.home())
    return ("~" + path[len(home):]) if path.startswith(home) else path


def trunc(s: str, max_len: int) -> str:
    """Truncate with ellipsis instead of wrapping."""
    return s if len(s) <= max_len else s[:max_len - 1] + "…"


# ── Table display with pagination (#2) ───────────────────────────────────────
def _render_page(results: list[FileResult], page: int, total_pages: int) -> None:
    """Render one page of results."""
    term_width = console.width or 100

    # Adapt column widths to terminal size
    if term_width >= 120:
        name_w, path_w = 30, 45
    elif term_width >= 90:
        name_w, path_w = 24, 35
    else:
        name_w, path_w = 18, 25

    start = page * PAGE_SIZE
    end   = min(start + PAGE_SIZE, len(results))
    page_results = results[start:end]

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        show_lines=False,
        expand=False,
    )
    table.add_column("#",        style="dim",        width=3,      justify="right")
    table.add_column("File Name", style="bold green", width=name_w, no_wrap=True, overflow="ellipsis")
    table.add_column("Path",     style="white",      width=path_w, no_wrap=True, overflow="ellipsis")
    table.add_column("Size",     style="cyan",       width=9,      justify="right", no_wrap=True)
    table.add_column("Modified", style="dim",        width=16,     no_wrap=True)

    for i, r in enumerate(page_results, start + 1):
        table.add_row(
            str(i),
            trunc(r.name, name_w),
            trunc(tilde_path(r.path), path_w),
            r.size_human,
            fmt_mtime(r.mtime),
        )

    console.print(table)

    # Pagination footer
    if total_pages > 1:
        console.print(
            f"[dim]  Page {page + 1}/{total_pages}  "
            f"({start + 1}–{end} of {len(results)}) — "
            f"[yellow]n[/yellow] next  [yellow]p[/yellow] prev  [yellow]q[/yellow] done[/dim]\n"
        )
    else:
        console.print(
            f"[dim]  {len(results)} result(s) — "
            f"[yellow]/open N[/yellow] to open  [yellow]/copy N[/yellow] to copy path[/dim]\n"
        )


def display_results(results: list[FileResult], session: PromptSession) -> None:
    global _last_results, _current_page, _total_pages

    if not results:
        console.print(Panel(
            "[yellow]No files found.[/yellow] Try different keywords.",
            border_style="yellow",
        ))
        return

    _last_results = results
    _total_pages  = (len(results) + PAGE_SIZE - 1) // PAGE_SIZE
    _current_page = 0

    _render_page(results, _current_page, _total_pages)

    # Pagination loop (#2)
    if _total_pages > 1:
        while True:
            try:
                key = session.prompt(
                    [("class:prompt", " [n/p/q] ❯ ")], style=PROMPT_STYLE
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                break

            if key == "n" and _current_page < _total_pages - 1:
                _current_page += 1
                _render_page(results, _current_page, _total_pages)
            elif key == "p" and _current_page > 0:
                _current_page -= 1
                _render_page(results, _current_page, _total_pages)
            elif key in ("q", ""):
                break
            else:
                # Treat anything else as a new search query — return it to main loop
                # by pushing it as the next query (handled by returning the key)
                return key   # caller will re-process


def show_stats() -> None:
    s = db_stats()
    boot_file = Path("/tmp/filefinder.booting")

    if not s["ready"]:
        if boot_file.exists():
            count = boot_file.read_text().strip()
            console.print(Panel(
                f"[yellow]⏳ Initial scan in progress — {count} files so far.[/yellow]\n"
                "[dim]Wait a moment and try again.[/dim]",
                title="Index Stats", border_style="yellow", width=65,
            ))
        else:
            console.print("[red]Index not ready. Is indexer running? Run: systemctl --user start filefinder[/red]")
        return

    ollama_line = (
        "[green]✓ Ollama online[/green]" if check_ollama()
        else "[yellow]⚠ Ollama offline — fast regex fallback active[/yellow]"
    )
    console.print(Panel(
        f"[green]✓[/green] Index ready\n"
        f"[cyan]{s['total']:,}[/cyan] files indexed\n"
        f"[dim]DB: {s['db_path']}[/dim]\n"
        f"{ollama_line}",
        title="Index Stats", border_style="cyan", width=65,
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
        console.print("[red]xdg-open not found.[/red]")


def copy_result(idx: int) -> None:
    if not _last_results or idx < 1 or idx > len(_last_results):
        console.print(f"[red]No result #{idx}. Run a search first.[/red]")
        return
    path = _last_results[idx - 1].path
    for tool, args in [
        ("xclip", ["-selection", "clipboard"]),
        ("xsel",  ["--clipboard", "--input"]),
    ]:
        try:
            proc = subprocess.run([tool] + args, input=path.encode(), timeout=3)
            if proc.returncode == 0:
                console.print(f"[green]Copied:[/green] {tilde_path(path)}")
                return
        except FileNotFoundError:
            continue
    console.print("[yellow]Install xclip:[/yellow] sudo apt install xclip")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    console.print(Panel(
        Text.from_markup(
            "[bold cyan]FileChat[/bold cyan]  [dim]powered by phi3:mini[/dim]\n"
            "[dim]Type [/dim][yellow]help[/yellow][dim] for usage, "
            "[/dim][yellow]exit[/yellow][dim] to quit.[/dim]"
        ),
        border_style="cyan", width=60,
    ))

    # Ollama check
    if not check_ollama():
        console.print(Panel(
            "[yellow]⚠ Ollama is not running.[/yellow]\n"
            "[dim]Falling back to fast regex matching.\n"
            "To enable NL search: [/dim][cyan]ollama serve[/cyan]",
            border_style="yellow", width=60,
        ))
    else:
        console.print("[dim]  Ollama online ✓[/dim]")

    # Index status
    s = db_stats()
    boot_file = Path("/tmp/filefinder.booting")
    if not s["ready"] and boot_file.exists():
        count = boot_file.read_text().strip()
        console.print(f"[yellow]  ⏳ Scan in progress ({count} files so far)…[/yellow]\n")
    elif s["ready"]:
        console.print(f"[dim]  Index ready — {s['total']:,} files[/dim]\n")
    else:
        console.print("[yellow]  ⚠ Index not found. Is the indexer running?[/yellow]\n")

    # (#7) Persistent history
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    session = PromptSession(history=FileHistory(str(HISTORY_FILE)))

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
        if low.startswith("/open"):
            parts = low.split()
            if len(parts) == 2 and parts[1].isdigit():
                open_result(int(parts[1]))
            else:
                console.print("[yellow]Usage: /open N[/yellow]")
            continue
        if low.startswith("/copy"):
            parts = low.split()
            if len(parts) == 2 and parts[1].isdigit():
                copy_result(int(parts[1]))
            else:
                console.print("[yellow]Usage: /copy N[/yellow]")
            continue

        with console.status("[cyan]Searching…[/cyan]", spinner="dots"):
            results = search(query)

        display_results(results, session)


if __name__ == "__main__":
    main()
