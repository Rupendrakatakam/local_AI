"""
tray.py — System tray icon for FileChat GUI.
Provides a quick menu to open the UI in browser, check stats, or quit.
"""
import sys
import webbrowser
from search import db_stats
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw

def create_icon_image():
    """Generate a simple 64x64 blue magnifying glass icon."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Magnifying glass circle
    draw.ellipse([10, 10, 40, 40], outline=(0, 212, 255), width=4)
    # Magnifying glass handle
    draw.line([35, 35, 55, 55], fill=(0, 212, 255), width=5)
    return img

def action_open_browser(icon, item):
    webbrowser.open("http://127.0.0.1:5000")

def action_show_stats(icon, item):
    try:
        s = db_stats()
        # In a real app, you might show a notification or update the menu text
        # For now we'll just log it to stdout
        print(f"FileChat Stats: {s['total']} files indexed. Ready: {s['ready']}")
    except Exception as e:
        print(f"Failed to get stats: {e}")

def action_quit(icon, item):
    icon.stop()
    print("Tray icon stopped.")
    # Exit the script which will allow the bash wrapper to cleanup Flask
    sys.exit(0)

def main():
    menu = pystray.Menu(
        item("Open FileChat", action_open_browser, default=True),
        item("Stats (CLI)", action_show_stats),
        pystray.Menu.SEPARATOR,
        item("Quit", action_quit)
    )
    
    icon = pystray.Icon("FileChat", create_icon_image(), "FileChat Search", menu)
    icon.run()

if __name__ == "__main__":
    main()
