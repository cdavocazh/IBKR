#!/usr/bin/env python3
"""Patch both Telegram bots: rename /relogin to /relogin_ibkr, add to OAuth bot."""
import sys

RELOGIN_FUNC = '''
def run_relogin_ibkr(chat_id):
    """Restart IB Gateway to force re-authentication."""
    send_message(chat_id, "Restarting IB Gateway... Approve 2FA on IBKR Mobile within 60s.")
    try:
        r = subprocess.run(
            ["docker", "compose", "-f", "/root/ib-gateway/docker-compose.yml", "restart"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            send_message(chat_id, f"Docker restart failed: {r.stderr[:200]}")
            return
    except Exception as e:
        send_message(chat_id, f"Restart error: {e}")
        return

    # Wait for re-auth
    for i in range(1, 19):
        time.sleep(5)
        try:
            check = subprocess.run(
                ["/root/IBKR/venv/bin/python3", "-c",
                 "from ib_async import IB; ib=IB(); ib.connect('127.0.0.1', 4001, clientId=96, readonly=True, timeout=8); print('OK') if ib.managedAccounts() else print('NO'); ib.disconnect()"],
                capture_output=True, text=True, timeout=15,
            )
            if "OK" in check.stdout:
                send_message(chat_id, f"IB Gateway re-authenticated after {i*5}s.")
                return
        except Exception:
            pass

    send_message(chat_id, "IB Gateway did not re-authenticate within 90s. 2FA may not have been approved.")

'''

# === 1. Patch Finl_Agent bot: rename relogin -> relogin_ibkr ===
FINL_PATH = "/root/Finl_Agent_CC/telegram_claude_bot.py"
print(f"Patching {FINL_PATH}...")

with open(FINL_PATH, "r") as f:
    content = f.read()

# Remove old relogin command and function
content = content.replace(
    '    if cmd == "relogin":\n        threading.Thread(target=run_relogin, args=(chat_id,), daemon=True).start()\n        return\n',
    '    if cmd == "relogin_ibkr":\n        threading.Thread(target=run_relogin_ibkr, args=(chat_id,), daemon=True).start()\n        return\n',
)

# Replace old function with new
if "def run_relogin(" in content:
    # Find and replace the old function
    start = content.index("def run_relogin(")
    # Find the next function definition
    next_def = content.index("\ndef ", start + 1)
    content = content[:start] + RELOGIN_FUNC.lstrip() + content[next_def:]

with open(FINL_PATH, "w") as f:
    f.write(content)
print("  -> Renamed /relogin to /relogin_ibkr")

# === 2. Patch Claude OAuth bot: add /relogin_ibkr ===
OAUTH_PATH = "/root/Claude_OAuth_bot/telegram_bot.py"
print(f"Patching {OAUTH_PATH}...")

with open(OAUTH_PATH, "r") as f:
    content = f.read()

if "relogin_ibkr" in content:
    print("  -> /relogin_ibkr already exists, skipping")
else:
    # Add command routing after the health check block
    old = '    if cmd == "health":\n        threading.Thread(target=run_health_check, args=(chat_id,), daemon=True).start()\n        return'
    new = old + '''

    if cmd == "relogin_ibkr":
        threading.Thread(target=run_relogin_ibkr, args=(chat_id,), daemon=True).start()
        return'''
    content = content.replace(old, new, 1)

    # Add the function before run_health_check
    content = content.replace(
        "\ndef run_health_check(chat_id):",
        RELOGIN_FUNC + "\ndef run_health_check(chat_id):",
        1,
    )

    with open(OAUTH_PATH, "w") as f:
        f.write(content)
    print("  -> Added /relogin_ibkr command")

print("Done.")
