"""
hotkey.py — Global keyboard shortcut listener for FileChat.
Press Ctrl+Space to open the FileChat search interface in the default browser.
"""
import webbrowser
from pynput import keyboard
from config_loader import get as cfg

PORT = int(cfg("gui_port", 5000))
URL = f"http://127.0.0.1:{PORT}"

def on_activate_search():
    print(f"Hotkey activated! Opening {URL}...")
    webbrowser.open(URL)

def main():
    hotkey = '<ctrl>+<space>'
    print(f"FileChat Hotkey Listener starting...")
    print(f"Press {hotkey} to search.")
    
    with keyboard.GlobalHotKeys({
        hotkey: on_activate_search
    }) as h:
        h.join()

if __name__ == "__main__":
    main()
