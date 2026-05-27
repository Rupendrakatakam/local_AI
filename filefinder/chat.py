"""
chat.py — Terminal chat interface for FileChat.
Batch 3:
  #17 /hidden toggle
  #13 /service command
  #9  Live file count badge in prompt (cached, refreshed every 60s)
"""

import sys
import time
import datetime
import subprocess
import threading
import requests
from pathlib import Path
from search import search, db_stats, FileResult, toggle_hidden, get_show_hidden
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.history import FileHistory

console = Console()

PROMPT_STYLE = Style.from_dict({"prompt": "bold ansigreen"})
HISTORY_FILE = Path.home() / ".config" / "filefinder" / "history"
PAGE_SIZE    = 10

HELP_TEXT = """
[bold cyan]FileChat[/bold cyan] — Find any file in your home directory

[bold]Search examples:[/bold]
  where is resume.pdf
  find my python scripts
  find image named rupendra
  type:video        [dim]← all videos[/dim]
  type:code         [dim]← all code files[/dim]
  type:image rupendra  [dim]← images with 'rupendra' in name[/dim]

[bold]Commands:[/bold]
  [yellow]help[/yellow]          Show this message
  [yellow]stats[/yellow]         Show index + Ollama status
  [yellow]/hidden[/yellow]       Toggle hidden files on/off
  [yellow]/service[/yellow]      Show indexer daemon status
  [yellow]/open N[/yellow]       Open result N in default app
  [yellow]/copy N[/yellow]       Copy path of result N to clipboard
  [yellow]exit[/yellow]          Quit

[bold]Pagination:[/bold]  After results, press [yellow]n[/yellow] next / [yellow]p[/yellow] prev / [yellow]q[/yellow] quit
"""

_last_results: list[FileResult] = []
_current_page: int = 0
_total_pages:  int = 0

# ── Live file count badge (#9) ────────────────────────────────────────────────
_live_count:    str  = "…"
_count_lock          = threading.Lock()


def _refresh_count_loop() -> None:
    """Background thread: refresh file count every 60 seconds."""
    global _live_count
    while True:
        try:
            s = db_stats()
            new = f"{s['total']:,}" if s["ready"] else "?"
        except Exception:
            new = "?"
        with _count_lock:
            _live_count = new
        time.sleep(60)


def get_live_count() -> str:
    with _count_lock:
        return _live_count


def _make_prompt() -> list[tuple[str, str]]:
    count = get_live_count()
    hidden_marker = " [H]" if get_show_hidden() else ""
    return [
        ("class:badge", f" [{count} files{hidden_marker}]"),
        ("class:prompt", " You ❯ "),
    ]


PROMPT_STYLE = Style.from_dict({
    "badge":  "ansidarkgray",
    "prompt": "bold ansigreen",
})


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
    return s if len(s) <= max_len else s[:max_len - 1] + "…"


# ── Table display with pagination ─────────────────────────────────────────────
def _render_page(results: list[FileResult], page: int, total_pages: int) -> None:
    term_width = console.width or 100
    if term_width >= 120:
        name_w, path_w = 30, 45
    elif term_width >= 90:
        name_w, path_w = 24, 35
    else:
        name_w, path_w = 18, 25

    start        = page * PAGE_SIZE
    end          = min(start + PAGE_SIZE, len(results))
    page_results = results[start:end]

    table = Table(
        box=box.ROUNDED, show_header=True,
        header_style="bold cyan", border_style="dim",
        show_lines=False, expand=False,
    )
    table.add_column("#",          style="dim",        width=3,      justify="right")
    table.add_column("File Name",  style="bold green", width=name_w, no_wrap=True, overflow="ellipsis")
    table.add_column("Path",       style="white",      width=path_w, no_wrap=True, overflow="ellipsis")
    table.add_column("Size",       style="cyan",       width=9,      justify="right", no_wrap=True)
    table.add_column("Modified",   style="dim",        width=16,     no_wrap=True)

    for i, r in enumerate(page_results, start + 1):
        table.add_row(
            str(i),
            trunc(r.name, name_w),
            trunc(tilde_path(r.path), path_w),
            r.size_human,
            fmt_mtime(r.mtime),
        )

    console.print(table)
    if total_pages > 1:
        console.print(
            f"[dim]  Page {page+1}/{total_pages}  ({start+1}–{end} of {len(results)}) — "
            f"[yellow]n[/yellow] next  [yellow]p[/yellow] prev  [yellow]q[/yellow] done[/dim]\n"
        )
    else:
        console.print(
            f"[dim]  {len(results)} result(s) — "
            f"[yellow]/open N[/yellow] open  [yellow]/copy N[/yellow] copy path[/dim]\n"
        )


def display_results(results: list[FileResult], session: PromptSession) -> None:
    global _last_results, _current_page, _total_pages

    if not results:
        console.print(Panel(
            "[yellow]No files found.[/yellow] Try different keywords or [yellow]/hidden[/yellow] to include hidden files.",
            border_style="yellow",
        ))
        return

    _last_results = results
    _total_pages  = (len(results) + PAGE_SIZE - 1) // PAGE_SIZE
    _current_page = 0

    _render_page(results, _current_page, _total_pages)

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


# ── Commands ──────────────────────────────────────────────────────────────────
def show_stats() -> None:
    s = db_stats()
    boot_file = Path("/tmp/filefinder.booting")

    if not s["ready"]:
        if boot_file.exists():
            count = boot_file.read_text().strip()
            console.print(Panel(
                f"[yellow]⏳ Scan in progress — {count} files so far.[/yellow]",
                title="Index Stats", border_style="yellow", width=65,
            ))
        else:
            console.print("[red]Index not ready. Run: systemctl --user start filefinder[/red]")
        return

    ollama_line = (
        "[green]✓ Ollama online[/green]" if check_ollama()
        else "[yellow]⚠ Ollama offline — fast regex fallback active[/yellow]"
    )
    hidden_line = "[cyan]Hidden files: ON[/cyan]" if get_show_hidden() else "[dim]Hidden files: OFF (use /hidden to toggle)[/dim]"
    console.print(Panel(
        f"[green]✓[/green] Index ready\n"
        f"[cyan]{s['total']:,}[/cyan] files indexed\n"
        f"[dim]DB: {s['db_path']}[/dim]\n"
        f"{ollama_line}\n"
        f"{hidden_line}",
        title="Index Stats", border_style="cyan", width=65,
    ))


def show_service_status() -> None:
    """#13 — show systemd service status."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "status", "filefinder", "--no-pager", "-l"],
            capture_output=True, text=True, timeout=5,
        )
        output = result.stdout or result.stderr
        # Show just the key lines, not the full wall of text
        lines = output.strip().splitlines()
        summary = "\n".join(lines[:8])
        border = "green" if "active (running)" in output else "red"
        console.print(Panel(summary, title="Indexer Service", border_style=border, width=70))
    except FileNotFoundError:
        console.print("[red]systemctl not found. Are you on a systemd system?[/red]")
    except Exception as e:
        console.print(f"[red]Error checking service: {e}[/red]")


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
    # (#9) Start background count refresh thread
    t = threading.Thread(target=_refresh_count_loop, daemon=True)
    t.start()
    # Prime the count immediately
    try:
        s = db_stats()
        with _count_lock:
            _live_count = f"{s['total']:,}" if s["ready"] else "?"
    except Exception:
        pass

    console.print(Panel(
        Text.from_markup(
            "[bold cyan]FileChat[/bold cyan]  [dim]powered by phi3:mini[/dim]\n"
            "[dim]Type [/dim][yellow]help[/yellow][dim] for usage, "
            "[/dim][yellow]exit[/yellow][dim] to quit.[/dim]"
        ),
        border_style="cyan", width=60,
    ))

    if not check_ollama():
        console.print(Panel(
            "[yellow]⚠ Ollama is not running.[/yellow]\n"
            "[dim]Falling back to fast regex. To enable NL search: [/dim][cyan]ollama serve[/cyan]",
            border_style="yellow", width=60,
        ))
    else:
        console.print("[dim]  Ollama online ✓[/dim]")

    s = db_stats()
    boot_file = Path("/tmp/filefinder.booting")
    if not s["ready"] and boot_file.exists():
        count = boot_file.read_text().strip()
        console.print(f"[yellow]  ⏳ Scan in progress ({count} files so far)…[/yellow]\n")
    elif s["ready"]:
        console.print(f"[dim]  Index ready — {s['total']:,} files[/dim]\n")
    else:
        console.print("[yellow]  ⚠ Index not found. Is the indexer running?[/yellow]\n")

    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    session = PromptSession(history=FileHistory(str(HISTORY_FILE)))

    while True:
        try:
            query = session.prompt(_make_prompt(), style=PROMPT_STYLE).strip()
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

        if low == "/hidden":                          # #17
            state = toggle_hidden()
            label = "[cyan]ON[/cyan] — hidden files included" if state else "[dim]OFF[/dim] — hidden files excluded"
            console.print(f"  Hidden files: {label}")
            continue

        if low == "/service":                         # #13
            show_service_status()
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
            results, is_fuzzy = search(query)

        if is_fuzzy and results:
            console.print("[dim yellow]  🔍 Showing approximate matches (fuzzy search)[/dim yellow]")
        display_results(results, session)


if __name__ == "__main__":
    main()
