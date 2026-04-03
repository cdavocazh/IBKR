#!/usr/bin/env python3
"""Hide /relogin_ibkr: silent ignore for unauthorized users (no 'Unauthorized' reply)."""

for bot_path in [
    "/root/Finl_Agent_CC/telegram_claude_bot.py",
    "/root/Claude_OAuth_bot/telegram_bot.py",
]:
    print(f"Patching {bot_path}...")
    with open(bot_path, "r") as f:
        content = f.read()

    # Change "Unauthorized." reply to silent return
    old = '''    if cmd == "relogin_ibkr":
        if chat_id != "1130846055":
            send_message(chat_id, "Unauthorized.")
            return'''

    new = '''    if cmd == "relogin_ibkr":
        if chat_id != "1130846055":
            return'''

    if old in content:
        content = content.replace(old, new, 1)
        with open(bot_path, "w") as f:
            f.write(content)
        print("  -> Silent ignore for unauthorized users")
    else:
        print("  -> Pattern not found, skipping")

print("Done.")
