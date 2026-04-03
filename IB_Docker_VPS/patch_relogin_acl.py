#!/usr/bin/env python3
"""Patch both bots to restrict /relogin_ibkr to chat_id 1130846055 only."""

ALLOWED_CHAT_ID = "1130846055"

for bot_path in [
    "/root/Finl_Agent_CC/telegram_claude_bot.py",
    "/root/Claude_OAuth_bot/telegram_bot.py",
]:
    print(f"Patching {bot_path}...")
    with open(bot_path, "r") as f:
        content = f.read()

    old = '''    if cmd == "relogin_ibkr":
        threading.Thread(target=run_relogin_ibkr, args=(chat_id,), daemon=True).start()
        return'''

    new = f'''    if cmd == "relogin_ibkr":
        if chat_id != "{ALLOWED_CHAT_ID}":
            send_message(chat_id, "Unauthorized.")
            return
        threading.Thread(target=run_relogin_ibkr, args=(chat_id,), daemon=True).start()
        return'''

    if old in content:
        content = content.replace(old, new, 1)
        with open(bot_path, "w") as f:
            f.write(content)
        print(f"  -> Restricted to chat_id {ALLOWED_CHAT_ID}")
    else:
        print("  -> Pattern not found, skipping")

print("Done.")
