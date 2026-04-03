"""
Telegram Bot → Claude Code Bridge for Financial Agent

Receives commands via Telegram, spawns headless Claude Code sessions
in /root/Finl_Agent_CC, and streams results back to Telegram.

Usage:
    python3 telegram_claude_bot.py

Environment:
    TELEGRAM_BOT_TOKEN  — Telegram Bot API token (from @BotFather)
    TELEGRAM_CHAT_ID    — Your Telegram chat ID (restricts access)

Supported commands:
    /scan [full]         — Macro indicator scan
    /macro               — Macro regime analysis
    /stress              — Financial stress score
    /btc                 — BTC futures analysis
    /synthesize          — Full macro synthesis
    /ta <ASSET>          — Technical analysis
    /analyze <TICKER>    — Equity analysis
    /commodity <ASSET>   — Commodity outlook
    /full_report         — 8-step full briefing
    /ask <question>      — Freeform question to the agent
    /health              — Check IB Gateway + services status
    /status              — Bot and system status
"""

import os
import sys
import json
import subprocess
import threading
import time
import signal
import logging
from pathlib import Path
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────
DOTENV_PATH = Path(__file__).parent / ".env"
AGENT_DIR = "/root/Finl_Agent_CC"
MAX_MESSAGE_LEN = 4096  # Telegram message limit
CLAUDE_TIMEOUT = 300    # 5 min max per command
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ── Logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "telegram_bot.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("tg-claude")

# ── Load .env ───────────────────────────────────────────────────────
def load_env():
    """Load .env file manually (no python-dotenv dependency)."""
    if DOTENV_PATH.exists():
        for line in DOTENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

load_env()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

if not TOKEN:
    log.error("TELEGRAM_BOT_TOKEN not set. Create .env with your bot token.")
    sys.exit(1)

# ── Telegram API (raw requests, no library needed) ──────────────────
import urllib.request
import urllib.parse
import urllib.error

API_BASE = f"https://api.telegram.org/bot{TOKEN}"


def tg_request(method, data=None):
    """Make a Telegram Bot API request."""
    url = f"{API_BASE}/{method}"
    if data:
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log.error(f"Telegram API error {e.code}: {body}")
        return {"ok": False, "error": body}
    except Exception as e:
        log.error(f"Telegram request failed: {e}")
        return {"ok": False, "error": str(e)}


def send_message(chat_id, text, parse_mode="Markdown"):
    """Send a message, splitting if too long."""
    chunks = split_message(text)
    for chunk in chunks:
        tg_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
        )
        if len(chunks) > 1:
            time.sleep(0.3)


def split_message(text):
    """Split long messages at Telegram's 4096 char limit."""
    if len(text) <= MAX_MESSAGE_LEN:
        return [text]
    chunks = []
    while text:
        if len(text) <= MAX_MESSAGE_LEN:
            chunks.append(text)
            break
        # Find a good split point
        split_at = text.rfind("\n", 0, MAX_MESSAGE_LEN)
        if split_at == -1:
            split_at = MAX_MESSAGE_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


# ── Claude Code Execution ──────────────────────────────────────────
# Track running tasks to prevent double-runs
_running_tasks = {}
_task_lock = threading.Lock()


def run_claude_command(prompt, chat_id, command_name="command"):
    """Run Claude Code headlessly and return the output."""
    task_key = f"{chat_id}:{command_name}"

    with _task_lock:
        if task_key in _running_tasks:
            send_message(chat_id, f"⏳ `{command_name}` is already running. Please wait.")
            return
        _running_tasks[task_key] = True

    try:
        send_message(chat_id, f"🔄 Running `{command_name}`...")

        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "text",
            "--max-turns", "25",
            "--dangerously-skip-permissions",
        ]

        log.info(f"Executing: {command_name} for chat {chat_id}")
        start = time.time()

        result = subprocess.run(
            cmd,
            cwd=AGENT_DIR,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
            env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"},
        )

        elapsed = time.time() - start
        output = result.stdout.strip() or result.stderr.strip() or "(no output)"

        # Log the run
        log.info(f"Completed {command_name} in {elapsed:.1f}s (exit={result.returncode})")
        log_run(command_name, elapsed, result.returncode, len(output))

        # Format response
        header = f"✅ `{command_name}` ({elapsed:.0f}s)\n\n"
        send_message(chat_id, header + output)

    except subprocess.TimeoutExpired:
        send_message(chat_id, f"⏰ `{command_name}` timed out after {CLAUDE_TIMEOUT}s.")
        log.warning(f"Timeout: {command_name}")

    except Exception as e:
        send_message(chat_id, f"❌ Error running `{command_name}`: {e}")
        log.error(f"Error: {command_name}: {e}")

    finally:
        with _task_lock:
            _running_tasks.pop(task_key, None)


def log_run(command, elapsed, exit_code, output_len):
    """Append run record to daily log file."""
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"runs-{today}.log"
    entry = {
        "time": datetime.now().isoformat(),
        "command": command,
        "elapsed_s": round(elapsed, 1),
        "exit_code": exit_code,
        "output_chars": output_len,
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Command Routing ────────────────────────────────────────────────
# Maps /command → Claude Code prompt
COMMAND_MAP = {
    "scan": "run /fin scan",
    "scanfull": "run /fin scan full",
    "macro": "run /fin macro",
    "bonds": "run /fin bonds",
    "stress": "run /fin stress",
    "latecycle": "run /fin latecycle",
    "consumer": "run /fin consumer",
    "housing": "run /fin housing",
    "labor": "run /fin labor",
    "synthesize": "run /fin synthesize",
    "btc": "run /fin btc",
    "oil": "run /fin oil",
    "bbb": "run /fin bbb",
    "fsmi": "run /fin fsmi",
    "vigilantes": "run /fin vigilantes",
    "valuation": "run /fin valuation",
    "riskpremium": "run /fin riskpremium",
    "crossasset": "run /fin crossasset",
    "pmregime": "run /fin pmregime",
    "usdregime": "run /fin usdregime",
    "full_report": "run /fin full_report",
}

# Commands that take an argument
ARG_COMMANDS = {
    "analyze": "run /fin analyze {arg}",
    "ta": "run /fin ta {arg}",
    "commodity": "run /fin commodity {arg}",
    "compare": "run /fin compare {arg}",
    "peers": "run /fin peers {arg}",
    "graham": "run /fin graham {arg}",
    "rsi": "run /fin rsi {arg}",
    "sr": "run /fin sr {arg}",
    "breakout": "run /fin breakout {arg}",
    "quickta": "run /fin quickta {arg}",
    "synthesis": "run /fin synthesis {arg}",
    "search": "run /fin search {arg}",
    "sl": "run /fin sl {arg}",
    "drivers": "run /fin drivers {arg}",
}


def handle_command(chat_id, text):
    """Parse and route a command."""
    text = text.strip()
    if not text.startswith("/"):
        return

    parts = text.split(None, 1)
    cmd = parts[0].lstrip("/").lower().replace("@", "").split("@")[0]
    arg = parts[1].strip() if len(parts) > 1 else ""

    # ── Built-in commands (no Claude Code needed) ──
    if cmd == "start":
        send_message(
            chat_id,
            "🤖 *Financial Agent Bot*\n\n"
            "I run Claude Code sessions against `/root/Finl_Agent_CC`.\n\n"
            "*Quick commands:*\n"
            "/scan — Macro indicator scan\n"
            "/macro — Macro regime\n"
            "/stress — Stress score\n"
            "/btc — BTC analysis\n"
            "/synthesize — Full synthesis\n"
            "/ta ASSET — Technical analysis\n"
            "/analyze TICKER — Equity analysis\n"
            "/full\\_report — 8-step briefing\n"
            "/ask QUESTION — Freeform\n"
            "/health — System status\n"
            "/help — All commands",
        )
        return

    if cmd == "help":
        lines = ["🤖 *All Commands*\n", "*No-arg commands:*"]
        for k in sorted(COMMAND_MAP):
            lines.append(f"  /{k}")
        lines.append("\n*Commands with argument:*")
        for k in sorted(ARG_COMMANDS):
            lines.append(f"  /{k} <arg>")
        lines.append("\n*System:*")
        lines.append("  /health — IB Gateway + services")
        lines.append("  /status — Bot + RAM")
        lines.append("  /ask <question> — Freeform agent query")
        send_message(chat_id, "\n".join(lines))
        return

    if cmd == "health":
        threading.Thread(target=run_health_check, args=(chat_id,), daemon=True).start()
        return

    if cmd == "status":
        threading.Thread(target=run_status, args=(chat_id,), daemon=True).start()
        return

    # ── Claude Code commands ──
    if cmd in COMMAND_MAP:
        prompt = COMMAND_MAP[cmd]
        if cmd == "scan" and arg.lower() == "full":
            prompt = COMMAND_MAP["scanfull"]
        threading.Thread(
            target=run_claude_command, args=(prompt, chat_id, cmd), daemon=True
        ).start()
        return

    if cmd in ARG_COMMANDS:
        if not arg:
            send_message(chat_id, f"Usage: `/{cmd} <argument>`")
            return
        prompt = ARG_COMMANDS[cmd].format(arg=arg)
        threading.Thread(
            target=run_claude_command, args=(prompt, chat_id, f"{cmd} {arg}"), daemon=True
        ).start()
        return

    if cmd == "ask":
        if not arg:
            send_message(chat_id, "Usage: `/ask <your question>`")
            return
        threading.Thread(
            target=run_claude_command, args=(arg, chat_id, "ask"), daemon=True
        ).start()
        return

    send_message(chat_id, f"Unknown command: `/{cmd}`. Try /help")


# ── Health / Status (no Claude Code needed) ─────────────────────────
def run_health_check(chat_id):
    """Check IB Gateway + system services."""
    checks = []

    # IB Gateway
    try:
        r = subprocess.run(
            ["nc", "-z", "127.0.0.1", "4001"],
            capture_output=True, timeout=5
        )
        checks.append("✅ IB Gateway API (4001): UP" if r.returncode == 0 else "❌ IB Gateway API (4001): DOWN")
    except Exception:
        checks.append("❌ IB Gateway API (4001): CHECK FAILED")

    # Docker container
    try:
        r = subprocess.run(
            ["docker", "compose", "-f", "/root/ib-gateway/docker-compose.yml", "ps", "--format", "json"],
            capture_output=True, text=True, timeout=10
        )
        if "running" in r.stdout.lower():
            checks.append("✅ IB Gateway container: RUNNING")
        else:
            checks.append("⚠️ IB Gateway container: NOT RUNNING")
    except Exception:
        checks.append("⚠️ IB Gateway container: CHECK FAILED")

    # Systemd services
    for svc in ["macro-react", "btc-react", "fintwit-bot"]:
        try:
            r = subprocess.run(
                ["systemctl", "is-active", f"{svc}.service"],
                capture_output=True, text=True, timeout=5
            )
            status = r.stdout.strip()
            icon = "✅" if status == "active" else "❌"
            checks.append(f"{icon} {svc}: {status}")
        except Exception:
            checks.append(f"⚠️ {svc}: CHECK FAILED")

    # Memory
    try:
        r = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5)
        mem_line = [l for l in r.stdout.splitlines() if l.startswith("Mem:")][0]
        parts = mem_line.split()
        checks.append(f"\n💾 RAM: {parts[2]} used / {parts[1]} total ({parts[6]} available)")
    except Exception:
        pass

    send_message(chat_id, "🏥 *Health Check*\n\n" + "\n".join(checks))


def run_status(chat_id):
    """Quick bot status."""
    uptime = subprocess.run(["uptime", "-p"], capture_output=True, text=True).stdout.strip()
    active_count = len(_running_tasks)
    send_message(
        chat_id,
        f"🤖 *Bot Status*\n\n"
        f"Uptime: `{uptime}`\n"
        f"Active tasks: `{active_count}`\n"
        f"Agent dir: `{AGENT_DIR}`\n"
        f"Claude: `{subprocess.run(['claude', '--version'], capture_output=True, text=True).stdout.strip()}`",
    )


# ── Polling Loop ───────────────────────────────────────────────────
def poll():
    """Long-poll Telegram for updates."""
    offset = 0
    log.info("Bot started. Polling for updates...")

    while True:
        try:
            resp = tg_request(
                "getUpdates",
                {"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
            )
            if not resp.get("ok"):
                log.warning(f"getUpdates failed: {resp}")
                time.sleep(5)
                continue

            for update in resp.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")

                if not text or not chat_id:
                    continue

                # Access control
                if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID:
                    log.warning(f"Unauthorized access from chat_id={chat_id}")
                    send_message(chat_id, "⛔ Unauthorized. This bot is private.")
                    continue

                log.info(f"Received: {text} (chat={chat_id})")
                handle_command(chat_id, text)

        except KeyboardInterrupt:
            log.info("Shutting down...")
            break
        except Exception as e:
            log.error(f"Poll error: {e}")
            time.sleep(5)


# ── Entry Point ────────────────────────────────────────────────────
if __name__ == "__main__":
    # Verify claude is available
    try:
        subprocess.run(["claude", "--version"], capture_output=True, check=True)
    except FileNotFoundError:
        log.error("Claude Code CLI not found. Install: npm install -g @anthropic-ai/claude-code")
        sys.exit(1)

    poll()
