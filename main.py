"""Compatibility entry point for the local-only Netmon collector.

Historically ``uv run main.py`` launched a loop that sent every result to
Telegram or Discord.  Keeping this tiny wrapper preserves the familiar command
while routing it to the new SQLite-backed local collector.
"""

from collector import main


if __name__ == "__main__":
    main()
