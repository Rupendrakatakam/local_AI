"""
tui_pt.py — Full-screen prompt_toolkit fallback TUI for FileChat.
"""
import sys
import subprocess
import datetime
from pathlib import Path
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import Frame, TextArea
from prompt_toolkit.styles import Style

from search import search

def fmt_mtime(mtime: float) -> str:
    return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")

def get_preview_text(path_str: str) -> str:
    path = Path(path_str)
    if not path.exists():
        return "File not found."
    ext = path.suffix.lower()
    
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"):
        return f"[Image File]\n\nPath: {path}\nSize: {path.stat().st_size} bytes"
        
    text_exts = {".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", 
                 ".yaml", ".yml", ".sh", ".rs", ".go", ".c", ".cpp", ".h", ".csv"}
    if ext in text_exts or not ext:
        try:
            return path.read_text(errors="replace")[:2000]
        except Exception as e:
            return f"Could not read text: {e}"
            
    if ext == ".pdf":
        try:
            import fitz
            doc = fitz.open(path)
            content = doc[0].get_text()[:1000] if len(doc) > 0 else "No text found on first page."
            return f"PDF - {len(doc)} pages\n\n{content}"
        except ImportError:
            return "PyMuPDF not installed for PDF previews (pip install pymupdf)."
        except Exception as e:
            return f"Failed to read PDF: {e}"
            
    return f"No preview available for {ext} files."


# State
class AppState:
    results = []
    selected_idx = 0
    query = ""

state = AppState()

search_input = TextArea(height=1, prompt='Search: ', multiline=False)
results_text = FormattedTextControl(text="Type to search...")
preview_text = FormattedTextControl(text="Preview will appear here.")

results_window = Window(content=results_text, always_hide_cursor=True)
preview_window = Window(content=preview_text, always_hide_cursor=True)

def update_ui():
    if not state.query:
        results_text.text = "Type to search..."
        preview_text.text = ""
        state.results = []
        return
        
    state.results, _ = search(state.query, limit=50)
    
    if not state.results:
        results_text.text = "No results found."
        preview_text.text = ""
        state.selected_idx = 0
        return
        
    # Ensure selected_idx is valid
    state.selected_idx = max(0, min(state.selected_idx, len(state.results) - 1))
    
    # Format results
    lines = []
    for i, r in enumerate(state.results):
        prefix = "> " if i == state.selected_idx else "  "
        name = r.name[:30].ljust(30)
        lines.append(f"{prefix}{name} | {r.size_human:>8} | {fmt_mtime(r.mtime)}")
        
    results_text.text = "\n".join(lines)
    
    # Update preview
    selected_path = state.results[state.selected_idx].path
    preview_text.text = get_preview_text(selected_path)


def on_text_changed(buf):
    state.query = buf.text
    state.selected_idx = 0
    update_ui()

search_input.buffer.on_text_changed += on_text_changed


kb = KeyBindings()

@kb.add('c-c')
def _(event):
    event.app.exit()

@kb.add('down')
def _(event):
    if state.results:
        state.selected_idx = min(state.selected_idx + 1, len(state.results) - 1)
        update_ui()

@kb.add('up')
def _(event):
    if state.results:
        state.selected_idx = max(state.selected_idx - 1, 0)
        update_ui()

@kb.add('enter')
def _(event):
    if state.results:
        path = state.results[state.selected_idx].path
        subprocess.Popen(["xdg-open", path])
        try:
            from behavior import record_open
            record_open(state.query, path)
        except ImportError:
            pass


root_container = HSplit([
    Frame(search_input, title="FileChat (prompt_toolkit)"),
    VSplit([
        Frame(results_window, title="Results (Up/Down to navigate)"),
        Frame(preview_window, title="Preview"),
    ])
])

layout = Layout(root_container, focused_element=search_input)

style = Style([
    ('frame.border', '#888888'),
])

app = Application(
    layout=layout,
    key_bindings=kb,
    full_screen=True,
    style=style,
    mouse_support=True
)

if __name__ == '__main__':
    app.run()
