"""
chat.py — Terminal chat interface for FileChat.
Batch 4:
  #20 /re <pattern> — regex search bypass (no LLM, no cascade)
  #22 Boot progress bar — live display during initial scan
"""

import re
import sys
import time
import sqlite3
import datetime
import subprocess
import threading
import requests
from pathlib import Path
from search import search, db_stats, FileResult, toggle_hidden, get_show_hidden, DB_PATH
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich import box
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import Completer, Completion

console      = Console()
HISTORY_FILE = Path.home() / ".config" / "filefinder" / "history"
PAGE_SIZE    = 15

HELP_TEXT = """
[bold cyan]FileChat[/bold cyan] — Find any file in your home directory

[bold]Search examples:[/bold]
  where is resume.pdf
  find image named rupendra
  type:video                    [dim]all videos[/dim]
  type:code rupendra            [dim]code files matching name[/dim]
  /re .*LQR.*\\.pdf$            [dim]regex search — bypasses LLM[/dim]

[bold]Commands:[/bold]
  [yellow]help[/yellow]          This message
  [yellow]stats[/yellow]         Index + Ollama status
  [yellow]/hidden[/yellow]       Toggle hidden files on/off
  [yellow]/service[/yellow]      Show indexer daemon status
  [yellow]/re <pattern>[/yellow] Regex search (case-insensitive)
  [yellow]/alias[/yellow]         Manage shortcuts (set/rm/list)
  [yellow]/open N[/yellow]       Open result N in default app
  [yellow]/copy N[/yellow]       Copy path of result N to clipboard
  [yellow]exit[/yellow]          Quit

[bold]Pagination:[/bold]  [yellow]n[/yellow] next  [yellow]p[/yellow] prev  [yellow]q[/yellow] quit
"""

_last_results: list[FileResult] = []
_last_query:   str = ""
_current_page: int = 0
_total_pages:  int = 0

# ── Live file count badge (#9) ────────────────────────────────────────────────
_live_count = "…"
_count_lock = threading.Lock()


def _refresh_count_loop() -> None:
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
    count  = get_live_count()
    hidden = " H" if get_show_hidden() else ""
    return [
        ("class:badge",  f" [{count}{hidden}]"),
        ("class:prompt", " You ❯ "),
    ]


PROMPT_STYLE = Style.from_dict({
    "badge":  "ansidarkgray",
    "prompt": "bold ansigreen",
})


# ── Suggestion completer ──────────────────────────────────────────────────────
class SuggestionCompleter(Completer):
    """Autocomplete from search history stored in behavior.db."""
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.strip()
        if len(text) < 2:
            return
        try:
            from suggestions import get_suggestions
            for s in get_suggestions(text, limit=5):
                yield Completion(s, start_position=-len(text))
        except Exception:
            pass


# ── Regex search (#20) ────────────────────────────────────────────────────────
def _regex_search(pattern: str, limit: int = 50) -> list[FileResult]:
    """
    Bypass LLM and cascade entirely.
    Uses a Python regex UDF registered on each shard's SQLite connection.
    """
    from db_utils import get_all_shard_paths
    shards = get_all_shard_paths()
    if not shards:
        console.print("[red]Index not ready.[/red]")
        return []
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        console.print(f"[red]Invalid regex:[/red] {e}")
        return []

    all_results = []
    for shard_path in shards:
        try:
            conn = sqlite3.connect(shard_path)

            def regex_match(pat: str, value: str) -> int:
                try:
                    return 1 if compiled.search(value) else 0
                except Exception:
                    return 0

            conn.create_function("REGEXP", 2, regex_match)
            conn.row_factory = sqlite3.Row

            hidden_clause = "" if get_show_hidden() else "AND name NOT LIKE '.%'"
            rows = conn.execute(
                f"SELECT path, name, extension, size, mtime FROM files "
                f"WHERE REGEXP(?, name) AND size > 0 {hidden_clause} "
                f"ORDER BY mtime DESC LIMIT ?",
                (pattern, limit),
            ).fetchall()
            conn.close()
            all_results.extend([FileResult(**dict(r)) for r in rows])
        except Exception:
            pass
    all_results.sort(key=lambda x: x.mtime, reverse=True)
    return all_results[:limit]


# ── Boot progress bar (#22) ───────────────────────────────────────────────────
def _show_boot_progress() -> None:
    """
    If the indexer is still doing its initial scan, show a live progress
    bar that reads from /tmp/filefinder.booting every 500ms.
    """
    boot_file = Path("/tmp/filefinder.booting")
    if not boot_file.exists():
        return

    console.print()
    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]Indexing home directory…[/cyan]"),
        BarColumn(bar_width=30),
        TextColumn("[cyan]{task.fields[count]}[/cyan] files"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("scan", total=None, count="0")
        while boot_file.exists():
            try:
                count_str = boot_file.read_text().strip()
                progress.update(task, count=count_str)
            except Exception:
                pass
            time.sleep(0.5)
        progress.update(task, count=get_live_count())

    console.print(f"[green]  ✓ Index ready — {get_live_count()} files[/green]\n")


def _show_embedding_progress() -> None:
    """
    If embeddings are being processed, show a one-time progress snapshot.
    """
    try:
        from embedder import get_pipeline
        pipeline = get_pipeline()
        progress = pipeline.get_progress()
        if progress["total"] > 0 and progress["pct"] < 100:
            console.print(
                f"[dim]  ⚡ Embeddings: {progress['done']:,}/{progress['total']:,} "
                f"({progress['pct']}%) — {progress['queued']} queued, {progress['errors']} errors[/dim]"
            )
        elif progress["total"] > 0:
            console.print(f"[dim]  ⚡ Embeddings: {progress['done']:,} files embedded ✓[/dim]")
    except ImportError:
        pass
    except Exception:
        pass


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


# ── Table rendering ───────────────────────────────────────────────────────────
def _render_page(results: list[FileResult], page: int, total_pages: int) -> None:
    w = console.width or 100
    name_w = 30 if w >= 120 else 24 if w >= 90 else 18
    path_w = 45 if w >= 120 else 35 if w >= 90 else 25

    start        = page * PAGE_SIZE
    end          = min(start + PAGE_SIZE, len(results))
    page_results = results[start:end]

    table = Table(
        box=box.ROUNDED, show_header=True,
        header_style="bold cyan", border_style="dim",
        show_lines=False, expand=False,
    )
    table.add_column("#",         style="dim",        width=3,      justify="right")
    table.add_column("File Name", style="bold green", width=name_w, no_wrap=True, overflow="ellipsis")
    table.add_column("Path",      style="white",      width=path_w, no_wrap=True, overflow="ellipsis")
    table.add_column("Size",      style="cyan",       width=9,      justify="right", no_wrap=True)
    table.add_column("Modified",  style="dim",        width=16,     no_wrap=True)
    table.add_column("Match",     width=7,            justify="right", no_wrap=True)

    for i, r in enumerate(page_results, start + 1):
        # Color the match score
        score = getattr(r, 'score', 0.0)
        if score >= 60:
            score_str = f"[bold green]{score:.0f}%[/bold green]"
        elif score >= 30:
            score_str = f"[yellow]{score:.0f}%[/yellow]"
        elif score > 0:
            score_str = f"[dim]{score:.0f}%[/dim]"
        else:
            score_str = "[dim]—[/dim]"

        table.add_row(
            str(i),
            trunc(r.name, name_w),
            trunc(tilde_path(r.path), path_w),
            r.size_human,
            fmt_mtime(r.mtime),
            score_str,
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


def display_results(results: list[FileResult], session: PromptSession, is_fuzzy: bool = False) -> None:
    global _last_results, _current_page, _total_pages

    if not results:
        console.print(Panel(
            "[yellow]No files found.[/yellow] Try different keywords, "
            "[yellow]/hidden[/yellow] for hidden files, or [yellow]/re pattern[/yellow] for regex.",
            border_style="yellow",
        ))
        return

    if is_fuzzy:
        console.print("\n[yellow]⚠ No exact matches. Showing fuzzy/approximate results:[/yellow]")

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


# ── Command handlers ──────────────────────────────────────────────────────────
def show_stats() -> None:
    s = db_stats()
    if not s["ready"]:
        console.print("[red]Index not ready. Run: systemctl --user start filefinder[/red]")
        return
    ollama_s = "[green]✓ Ollama online[/green]" if check_ollama() else "[yellow]⚠ Ollama offline — regex fallback[/yellow]"
    hidden_s = "[cyan]ON[/cyan]" if get_show_hidden() else "[dim]OFF[/dim]"
    try:
        from embedder import get_pipeline
        pipeline = get_pipeline()
        progress = pipeline.get_progress()
        embed_s = f"[blue]Embeddings: {progress['done']:,}/{progress['total']:,} ({progress['pct']}%) — {progress['errors']} errors[/blue]"
    except ImportError:
        embed_s = "[yellow]Embeddings: not available (missing dependencies)[/yellow]"

    console.print(Panel(
        f"[green]✓[/green] Index ready — [cyan]{s['total']:,}[/cyan] files\n"
        f"[dim]DB: {s['db_path']}[/dim]\n"
        f"{ollama_s}\n"
        f"Hidden files: {hidden_s}\n"
        f"{embed_s}",
        title="Index Stats", border_style="cyan", width=65,
    ))


def show_service() -> None:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "status", "filefinder", "--no-pager", "-l"],
            capture_output=True, text=True, timeout=5,
        )
        out    = (r.stdout or r.stderr).strip()
        lines  = "\n".join(out.splitlines()[:8])
        color  = "green" if "active (running)" in out else "red"
        console.print(Panel(lines, title="Indexer Service", border_style=color, width=70))
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def open_result(idx: int) -> None:
    if not _last_results or idx < 1 or idx > len(_last_results):
        console.print(f"[red]No result #{idx}.[/red]")
        return
    path = _last_results[idx - 1].path
    try:
        subprocess.Popen(["xdg-open", path])
        console.print(f"[green]Opening:[/green] {tilde_path(path)}")
        try:
            from behavior import record_open
            record_open(_last_query, path)
        except ImportError:
            pass
            
        try:
            from audit import log_action
            log_action("OPEN_CLI", f"Path: {path}, Source Query: {_last_query}")
        except Exception:
            pass
    except FileNotFoundError:
        console.print("[red]xdg-open not found.[/red]")


def copy_result(idx: int) -> None:
    if not _last_results or idx < 1 or idx > len(_last_results):
        console.print(f"[red]No result #{idx}.[/red]")
        return
    path = _last_results[idx - 1].path
    for tool, args in [
        ("xclip", ["-selection", "clipboard"]),
        ("xsel",  ["--clipboard", "--input"]),
    ]:
        try:
            if subprocess.run([tool] + args, input=path.encode(), timeout=3).returncode == 0:
                console.print(f"[green]Copied:[/green] {tilde_path(path)}")
                try:
                    from behavior import record_copy
                    record_copy(path)
                except ImportError:
                    pass
                return
        except FileNotFoundError:
            continue
    console.print("[yellow]Install xclip:[/yellow] sudo apt install xclip")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    # Start count refresh thread
    threading.Thread(target=_refresh_count_loop, daemon=True).start()
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
            "[yellow]⚠ Ollama not running.[/yellow]\n"
            "[dim]Fast regex fallback active. To enable NL: [/dim][cyan]ollama serve[/cyan]",
            border_style="yellow", width=60,
        ))
    else:
        console.print("[dim]  Ollama online ✓[/dim]")

    # (#22) Show live boot progress if scan is running
    _show_boot_progress()

    # Show embedding progress snapshot
    _show_embedding_progress()

    s = db_stats()
    if s["ready"]:
        console.print(f"[dim]  Index ready — {s['total']:,} files[/dim]\n")
    else:
        console.print("[yellow]  ⚠ Index not found. Is the indexer running?[/yellow]\n")

    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    session = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        completer=SuggestionCompleter(),
    )

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
        if low == "/hidden":
            state = toggle_hidden()
            console.print(f"  Hidden files: {'[cyan]ON[/cyan]' if state else '[dim]OFF[/dim]'}")
            continue
        if low == "/rebuild":
            console.print("[yellow]Rebuilding FTS5 + trigrams across all shards...[/yellow]")
            try:
                from db_utils import get_all_shard_paths
                from indexer import _generate_trigrams
                total_files = 0
                for shard_path in get_all_shard_paths():
                    try:
                        conn = sqlite3.connect(shard_path)
                        conn.execute("DELETE FROM files_fts")
                        conn.execute("INSERT INTO files_fts(rowid, name, path) SELECT rowid, name, path FROM files")
                        conn.execute("DELETE FROM name_trigrams")
                        rows = conn.execute("SELECT rowid, name FROM files").fetchall()
                        batch = []
                        for rid, name in rows:
                            for tg in _generate_trigrams(name):
                                batch.append((tg, rid))
                        conn.executemany("INSERT INTO name_trigrams (trigram, file_id) VALUES (?, ?)", batch)
                        conn.commit()
                        conn.close()
                        total_files += len(rows)
                    except Exception as e:
                        console.print(f"[yellow]Skipped shard {shard_path.name}: {e}[/yellow]")
                console.print(f"[green]✓ Rebuilt FTS5 + trigrams for {total_files:,} files across {len(get_all_shard_paths())} shards[/green]")
            except Exception as e:
                console.print(f"[red]Rebuild failed: {e}[/red]")
            continue
        if low == "/privacy clear":
            try:
                from behavior import privacy_clear
                privacy_clear()
                console.print("[green]✓ Behavioral data cleared.[/green]")
            except ImportError:
                console.print("[yellow]behavior module not available[/yellow]")
            continue
        if low == "/service":
            show_service()
            continue
        if low.startswith("/open"):
            parts = low.split()
            open_result(int(parts[1])) if len(parts) == 2 and parts[1].isdigit() else console.print("[yellow]Usage: /open N[/yellow]")
            continue
        if low.startswith("/copy"):
            parts = low.split()
            copy_result(int(parts[1])) if len(parts) == 2 and parts[1].isdigit() else console.print("[yellow]Usage: /copy N[/yellow]")
            continue

        if low.startswith("/alias"):
            parts = query.split(maxsplit=3)
            try:
                from aliases import set_alias, get_alias, remove_alias, list_aliases
                if len(parts) >= 2 and parts[1].lower() == "list":
                    aliases = list_aliases()
                    if aliases:
                        for k, v in aliases.items():
                            console.print(f"  [cyan]{k}[/cyan] -> {v}")
                    else:
                        console.print("  [dim]No aliases set.[/dim]")
                elif len(parts) >= 3 and parts[1].lower() == "rm":
                    if remove_alias(parts[2]):
                        console.print(f"  [green]Removed alias '{parts[2]}'[/green]")
                    else:
                        console.print(f"  [yellow]Alias '{parts[2]}' not found[/yellow]")
                elif len(parts) >= 4 and parts[1].lower() == "set":
                    set_alias(parts[2], parts[3])
                    console.print(f"  [green]Alias '{parts[2]}' set to {parts[3]}[/green]")
                else:
                    console.print("  [yellow]Usage: /alias set NAME PATH | /alias rm NAME | /alias list[/yellow]")
            except ImportError:
                console.print("[yellow]aliases module not available[/yellow]")
            continue

        # (#20) Regex bypass
        if low.startswith("/re "):
            pattern = query[4:].strip()
            if not pattern:
                console.print("[yellow]Usage: /re <pattern>   e.g. /re .*LQR.*\\.pdf$[/yellow]")
                continue
            with console.status("[cyan]Regex search…[/cyan]", spinner="dots"):
                results = _regex_search(pattern)
            display_results(results, session, is_fuzzy=False)
            continue

        global _last_query
        _last_query = query
        with console.status("[cyan]Searching…[/cyan]", spinner="dots"):
            results, is_fuzzy = search(query, limit=50)

        # Record search in behavior DB for suggestions and analytics
        try:
            from behavior import record_search
            record_search(query, len(results))
        except ImportError:
            pass

        display_results(results, session, is_fuzzy)


if __name__ == "__main__":
    main()