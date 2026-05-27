# Getting Started — Step-by-Step Setup & Usage Guide

This guide explains everything as if you've never used a terminal before. Follow each step carefully.

---

## Prerequisites (What You Need First)

Before installing FileChat, make sure you have:

1. **A Linux computer** (Ubuntu, Fedora, Arch, etc.)
2. **Python 3.10+** (type `python3 --version` in terminal to check)
3. **~2GB free disk space** (for dependencies and the database)
4. **An NVIDIA GPU** (optional but recommended — makes semantic search 5x faster)

---

## Step 1: Install Ollama (The Local AI Brain)

Ollama lets you run AI models on your own machine. FileChat uses it to understand natural language queries.

```bash
# Download and install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Start the Ollama server
ollama serve

# In a NEW terminal, download the AI model we use
ollama pull phi3:mini
```

**How to verify:** Open a terminal and type:
```bash
curl http://localhost:11434/api/tags
```
You should see JSON output listing `phi3:mini`. If you see an error, Ollama isn't running — go back and run `ollama serve`.

---

## Step 2: Install FileChat

```bash
# Navigate to the FileChat directory
cd ~/Rupendra/local_AI/filefinder

# Run the setup script (installs everything)
bash setup.sh
```

**What setup.sh does:**
1. Installs system Python packages (watchdog, rich, prompt_toolkit, requests)
2. Installs AI/ML packages (sentence-transformers, lancedb, pymupdf, mammoth)
3. Installs GUI packages (flask, pystray, pillow)
4. Registers the indexer as a background service (systemd)
5. Starts the indexer automatically

---

## Step 3: Wait for Initial Indexing

The first time FileChat runs, it needs to scan your entire home directory. This takes about 2-5 minutes depending on how many files you have.

**How to check progress:**
```bash
# Check if the indexer is running
systemctl --user status filefinder

# Watch the live log
journalctl --user -u filefinder -f
```

You'll see messages like:
```
Starting full scan of /home/rupendra ...
Full scan complete — 670055 files indexed.
Watching /home/rupendra for changes.
```

Once you see "Watching", you're ready to search!

---

## Step 4: Start Searching

### Option A: Terminal Interface (Fastest)

```bash
cd ~/Rupendra/local_AI/filefinder
python3 chat.py
```

You'll see:
```
┌──────────────────────────────────────────────────────┐
│ FileChat  powered by phi3:mini                       │
│ Type help for usage, exit to quit.                   │
└──────────────────────────────────────────────────────┘
  Ollama online ✓
  Index ready — 670,055 files

[670,055] 🔍 ›
```

Now just type what you're looking for:
```
where is my resume
find image named rupendra
type:pdf tax
type:video
```

### Option B: Web GUI (Prettiest)

```bash
cd ~/Rupendra/local_AI/filefinder
./filechat-gui
```

This opens a beautiful dark-mode search page in your web browser at `http://127.0.0.1:5000`.

### Option C: Just the Web Server (No Tray Icon)

```bash
python3 gui.py
# Then open http://127.0.0.1:5000 in your browser
```

---

## Step 5: Using the Terminal Interface

### Basic Search
Just type naturally:
```
where is resume.pdf
find python scripts about robotics
type:image sunset
```

### Commands Reference

| Command | What It Does |
|---------|-------------|
| `help` | Show the help menu |
| `stats` | Show index size, Ollama status, embedding progress |
| `/open 3` | Open the 3rd result in its default app |
| `/copy 5` | Copy the path of the 5th result to clipboard |
| `/hidden` | Toggle showing hidden files (dotfiles) on/off |
| `/re .*\.pdf$` | Search using a regex pattern (bypasses AI) |
| `/alias set NAME PATH` | Create a shortcut for a file |
| `/alias list` | Show all your shortcuts |
| `/alias rm NAME` | Delete a shortcut |
| `/rebuild` | Force-rebuild the search index (if it gets corrupted) |
| `/privacy clear` | Delete all behavioral tracking data |
| `/service` | Check if the background indexer is running |
| `exit` | Quit FileChat |

### Pagination
When results have more than 10 items:
- `n` → next page
- `p` → previous page
- `q` → back to search

---

## Step 6: Using the Web GUI

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `/` | Focus the search bar (from anywhere on the page) |
| `Esc` | Clear search or close the preview panel |
| `↑` / `↓` | Navigate through results |
| `Enter` | Open the selected file |

### Features
- **Live Search:** Results appear as you type (300ms delay for performance).
- **Preview Panel:** Click any result to see a preview on the right (text content, images, or PDF text).
- **Confidence Bars:** Green = highly relevant, Yellow = good match, Red = weak match.
- **Dark/Light Mode:** Toggle with the 🌓 button in the top-right corner.
- **Stats:** Click 📊 to see index statistics.

---

## Step 7: Running Diagnostics

If something feels wrong:

```bash
python3 doctor.py
```

This checks:
- ✅ Database exists and isn't corrupt
- ✅ FTS5 search index is in sync
- ✅ Trigram table is populated
- ✅ Behavior database is healthy
- ✅ Ollama is reachable
- ✅ All 11 Python dependencies are installed

If something is broken:
```bash
python3 doctor.py --repair
```

This automatically rebuilds the FTS5 and trigram tables.

---

## Troubleshooting

### "Ollama offline — regex fallback"
Ollama isn't running. Fix:
```bash
ollama serve
```

### "Index not found"
The indexer service isn't running. Fix:
```bash
systemctl --user start filefinder
```

### Search results are wrong or missing
Rebuild the index:
```bash
# In chat.py:
/rebuild

# Or from terminal:
python3 doctor.py --repair
```

### GUI won't start
Make sure Flask is installed:
```bash
pip install flask
python3 gui.py
```
