#!/usr/bin/env python3
"""CLI wrapper for natural-language /IBKR Telegram prompts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ibkr.telegram_portfolio import DEFAULT_STATE_PATH, IBKRTelegramService


def main() -> int:
    parser = argparse.ArgumentParser(description="Handle a natural-language /IBKR prompt.")
    parser.add_argument("prompt", nargs="*", help="Prompt text following /IBKR")
    parser.add_argument("--chat-id", default="default", help="Telegram chat id used for local watchlist state")
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH), help="Override the watchlist/alert state file")
    args = parser.parse_args()

    prompt = " ".join(args.prompt).strip()
    service = IBKRTelegramService(state_path=args.state_path)
    print(service.handle_prompt(prompt, chat_id=str(args.chat_id)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
