#!/usr/bin/env python3
"""Patch the Telegram bot on VPS to add /relogin command."""

BOT_PATH = "/root/Finl_Agent_CC/telegram_claude_bot.py"

with open(BOT_PATH, "r") as f:
    content = f.read()

# 1. Add /relogin command routing after the status block
old_status = '    if cmd == "status":\n        threading.Thread(target=run_status, args=(chat_id,), daemon=True).start()\n        return'

new_status = old_status + '''

    if cmd == "relogin":
        threading.Thread(target=run_relogin, args=(chat_id,), daemon=True).start()
        return'''

if "relogin" not in content:
    content = content.replace(old_status, new_status, 1)
else:
    print("relogin already in bot, skipping routing patch")

# 2. Add run_relogin function before run_health_check
relogin_func = '''
def run_relogin(chat_id):
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

if "def run_relogin" not in content:
    content = content.replace("\ndef run_health_check(chat_id):", relogin_func + "def run_health_check(chat_id):", 1)
else:
    print("run_relogin function already exists, skipping")

with open(BOT_PATH, "w") as f:
    f.write(content)

print("Bot patched successfully with /relogin command")
