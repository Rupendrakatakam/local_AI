# FileChat — Your Private, AI-Powered File Search Engine

> **Motto**: *"Find anything on your computer, instantly, privately, and intelligently."*

---

## What Is FileChat?

FileChat is a **local-first, AI-powered file search engine** that runs entirely on your own machine. Think of it like having a super-smart assistant sitting inside your computer who knows where every single file is, remembers which ones you use the most, and can understand what you're looking for even if you describe it vaguely.

Unlike cloud-based search tools (Google Drive, Dropbox search, Windows Search), FileChat:
- **Never sends your data anywhere.** Everything stays on your machine.
- **Learns from you.** It remembers what you open and boosts those files.
- **Understands meaning.** You can say "show me that machine learning report" and it finds the right PDF, even if "machine learning" isn't in the filename.

---

## Who Is This For?

| Person | Why They Need FileChat |
|--------|----------------------|
| **Students** | Hundreds of lecture notes, assignments, and PDFs scattered across folders. FileChat finds them instantly by topic. |
| **Developers** | Thousands of code files, configs, and scripts. FileChat handles fuzzy/typo searches and understands natural language. |
| **Researchers** | Papers, datasets, and notes organized chaotically. Semantic search finds related documents by *meaning*, not just filename. |
| **Privacy-conscious users** | People who refuse to let Google/Microsoft index their files. FileChat is 100% offline. |
| **Power users** | Anyone with 100K+ files who is tired of slow, dumb file explorers. |

---

## The Problem We Solve

Your computer has **hundreds of thousands of files**. The built-in search tools (Nautilus, `find`, Windows Search) are:
1. **Slow** — They scan the filesystem on every search.
2. **Dumb** — They only match exact filenames. Search "resume" and miss "CV_2024_final.pdf".
3. **Forgetful** — They don't know that you open `report.pdf` every morning.
4. **Blind to content** — They can't search *inside* PDFs or understand what a document is *about*.

FileChat fixes all four problems.

---

## Our Target & Objectives

### Primary Target
Build a file search system that is **faster than any built-in OS search**, **smarter than keyword matching**, and **completely private** — running 100% locally with zero cloud dependencies.

### Objectives (All Achieved ✅)

| # | Objective | Status |
|---|-----------|--------|
| 1 | Sub-millisecond search across 670K+ files | ✅ Done (FTS5 + SQLite) |
| 2 | Typo-tolerant fuzzy matching | ✅ Done (Trigram engine) |
| 3 | Natural language queries ("find my tax report") | ✅ Done (Ollama LLM) |
| 4 | Semantic search by meaning, not just filename | ✅ Done (MiniLM embeddings) |
| 5 | Learn from user behavior | ✅ Done (RFM scoring) |
| 6 | Premium browser-based GUI | ✅ Done (Flask + Glassmorphism UI) |
| 7 | Zero cloud dependencies | ✅ Done (all local) |
| 8 | Self-diagnosing and repairable | ✅ Done (doctor.py) |

---

## Documentation Index

| Document | What It Covers |
|----------|---------------|
| [FEATURES.md](./FEATURES.md) | Every feature explained with how it works |
| [HOW_IT_WORKS.md](./HOW_IT_WORKS.md) | Technical architecture in simple terms |
| [GETTING_STARTED.md](./GETTING_STARTED.md) | Step-by-step setup and usage guide |
| [PROS_AND_CONS.md](./PROS_AND_CONS.md) | Honest strengths and limitations |
| [PERFORMANCE.md](./PERFORMANCE.md) | Speed benchmarks and system impact |
| [FUTURE_ROADMAP.md](./FUTURE_ROADMAP.md) | Every possible future upgrade with justification |

---

## Quick Start (TL;DR)

```bash
# Install everything
bash setup.sh

# Use the terminal interface
python3 chat.py

# Or launch the web GUI
./filechat-gui

# Run diagnostics
python3 doctor.py
```

---

*Built with ❤️ by Rupendra — 80 updates, 5 phases, 100% local AI.*
