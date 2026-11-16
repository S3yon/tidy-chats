#!/usr/bin/env python3
"""tidy-chats entry point for hooks and skills: `keeper.py hook <Event>` or `keeper.py <command>`."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from tidy_chats import cli
except Exception:  # a broken install must never block a chat
    if len(sys.argv) > 1 and sys.argv[1] == "hook":
        print(json.dumps({}))
        sys.exit(0)
    raise

if __name__ == "__main__":
    sys.exit(cli.main(sys.argv[1:]))
