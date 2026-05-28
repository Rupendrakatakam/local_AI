"""
tui.py — Full-screen Textual TUI for FileChat.
Requires textual: pip install textual
"""
import sys
import os
import subprocess
import datetime
from pathlib import Path

try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, Vertical
    from textual.widgets import Header, Footer, Input, DataTable, Markdown, Static, Label
    from textual.binding import Binding
    from textual.coordinate import Coordinate
    from textual import work
except ImportError:
    print("Textual is not installed. Please run: pip install textual")
    sys.exit(1)

from search import search, db_stats

def fmt_mtime(mtime: float) -> str:
    return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")

def get_preview_text(path_str: str) -> str:
    path = Path(path_str)
    if not path.exists():
        return "File not found."
    ext = path.suffix.lower()
    
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"):
        return f"![Image]({path})"
        
    text_exts = {".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", 
                 ".yaml", ".yml", ".sh", ".rs", ".go", ".c", ".cpp", ".h", ".csv"}
    if ext in text_exts or not ext:
        try:
            content = path.read_text(errors="replace")[:2000]
            if ext == ".md":
                return content
            lang = ext.lstrip(".") if ext else "text"
            return f"```{lang}\n{content}\n```"
        except Exception as e:
            return f"Could not read text: {e}"
            
    if ext == ".pdf":
        try:
            import fitz
            doc = fitz.open(path)
            content = doc[0].get_text()[:1000] if len(doc) > 0 else "No text found on first page."
            return f"**PDF - {len(doc)} pages**\n\n```text\n{content}\n```"
        except ImportError:
            return "PyMuPDF not installed for PDF previews (pip install pymupdf)."
        except Exception as e:
            return f"Failed to read PDF: {e}"
            
    return f"No preview available for {ext} files."


class FileChatApp(App):
    CSS = """
    Screen {
        background: #0f111a;
    }
    
    #search-container {
        height: 3;
        margin: 1;
    }
    
    #search-input {
        width: 100%;
        border: round $accent;
    }
    
    #main-container {
        height: 100%;
        layout: horizontal;
    }
    
    #results-table {
        width: 60%;
        height: 100%;
        border: solid $primary;
    }
    
    #preview-container {
        width: 40%;
        height: 100%;
        border: solid $secondary;
        padding: 1;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("enter", "open_selected", "Open File"),
        Binding("slash", "focus_search", "Search"),
    ]

    def __init__(self):
        super().__init__()
        self.results = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="search-container"):
            yield Input(placeholder="Search files... (Press / to focus)", id="search-input")
        with Horizontal(id="main-container"):
            yield DataTable(id="results-table")
            with Vertical(id="preview-container"):
                yield Markdown("Select a file to preview", id="preview-markdown")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "FileChat TUI"
        table = self.query_one(DataTable)
        table.add_columns("Name", "Path", "Size", "Date")
        table.cursor_type = "row"
        self.query_one(Input).focus()
        
    @work(exclusive=True, thread=True)
    def perform_search(self, query: str) -> None:
        if not query:
            self.call_from_thread(self._clear_results)
            return
            
        results, is_fuzzy = search(query, limit=50)
        self.call_from_thread(self._update_results, results)

    def _clear_results(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self.results = []
        self.query_one("#preview-markdown", Markdown).update("Select a file to preview")

    def _update_results(self, results) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self.results = results
        for r in results:
            table.add_row(r.name, r.path, r.size_human, fmt_mtime(r.mtime))
        if results:
            self._update_preview(results[0].path)

    def on_input_changed(self, event: Input.Changed) -> None:
        self.perform_search(event.value)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self.results and event.cursor_row < len(self.results):
            path = self.results[event.cursor_row].path
            self._update_preview(path)

    def _update_preview(self, path: str) -> None:
        md = self.query_one("#preview-markdown", Markdown)
        md.update(get_preview_text(path))

    def action_focus_search(self) -> None:
        self.query_one(Input).focus()

    def action_open_selected(self) -> None:
        table = self.query_one(DataTable)
        # Check if table has focus or results
        if self.results and table.cursor_row is not None and table.cursor_row < len(self.results):
            path = self.results[table.cursor_row].path
            subprocess.Popen(["xdg-open", path])
            query = self.query_one(Input).value
            try:
                from behavior import record_open
                record_open(query, path)
            except ImportError:
                pass


if __name__ == "__main__":
    app = FileChatApp()
    app.run()
