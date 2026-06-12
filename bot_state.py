"""
bot_state.py
────────────
Shared state between app.py and bot threads.
Import stop_event in any bot module to support the Stop button.
"""
import threading

stop_event = threading.Event()   # set() → bots should exit their loops
