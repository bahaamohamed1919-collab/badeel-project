"""Start the website:  python run.py   then open http://127.0.0.1:5000"""
import os
import threading
import webbrowser

from badeel import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    url = f"http://127.0.0.1:{port}"
    print(f"\n  Badeel is running at {url}")
    print("  Keep this window open. Close it (or press Ctrl+C) to stop the site.\n")
    if os.environ.get("BADEEL_OPEN_BROWSER") == "1":
        threading.Timer(1.5, webbrowser.open, [url]).start()
    # debug stays off unless you ask for it: debug mode must never run online.
    app.run(host="127.0.0.1", port=port, debug=os.environ.get("BADEEL_DEBUG") == "1")
