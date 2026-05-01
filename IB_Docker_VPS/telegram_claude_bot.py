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
    /history             — Show conversation context
    /clear               — Clear conversation context
    /sethistory N        — Set max history turns
    /newsession          — Reset Claude session (next message starts fresh)
    /stop                — Interrupt currently-running task
    /remember <fact>     — Save a fact to long-term memory
    /remember_session [N] — LLM auto-extracts durable facts from last N turns (default 10)
    /forget <number>     — Remove a memory by index
    /memory              — Show all stored memories
    /pfin [subcommand]   — Personal Finance Agent (brief, pf_deep, watchlist_review,
                           track_email, approve, cancel). No args → usage guide
    (any text)           — Natural language (treated as freeform question)

Architecture (2026-04-21, Tier A+B refactor):
    - Conversation continuity uses Claude Code's native --resume (session_id
      captured from first stream-json init event, per chat_id).
    - Memory (/remember, /forget) is still user-curated and prefix-injected —
      the two layers are complementary, not redundant.
    - /newsession clears the session_id (forces a fresh Claude thread).
    - /stop terminates the subprocess mid-turn.
    - Model: claude-opus-4-7[1m] with --effort max; --max-turns 40.
    - Partial-message streaming + TodoWrite-plan rendering in progress msg.
    - tool_result payloads persisted to logs/tool_results/{chat_id}-{date}/.
"""

import os
import sys
import json
import re
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

# ── Context & Memory Config ────────────────────────────────────────
MAX_HISTORY_PER_CHAT = 20   # max conversation turns per chat (/history UX only)
HISTORY_DIR = LOG_DIR / "history"
HISTORY_DIR.mkdir(exist_ok=True)
MEMORY_DIR = LOG_DIR / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

# Tier A+B additions
SESSIONS_DIR = LOG_DIR / "sessions"          # per-chat Claude session_ids
SESSIONS_DIR.mkdir(exist_ok=True)
TOOL_RESULTS_DIR = LOG_DIR / "tool_results"  # per-chat/per-day tool_result audit log
TOOL_RESULTS_DIR.mkdir(exist_ok=True)

# Turn budget per claude -p call. 25 was the original (v1); bumped to 40 to match
# the Agent_Orchestration pipeline agents and prevent /full_report clipping.
MAX_TURNS_PER_CALL = 40

# Partial-message streaming: when True, pass --include-partial-messages to Claude
# and render the trailing assistant text in the progress message so the user can
# watch Claude "think" in real time. Costs nothing extra — same wire protocol.
INCLUDE_PARTIAL_MESSAGES = True
PARTIAL_TEXT_TAIL_CHARS = 220   # how many trailing chars to show in progress msg

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
ALLOWED_CHAT_IDS = {cid.strip() for cid in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if cid.strip()}

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


def format_tables_for_telegram(text):
    """Convert Markdown pipe tables to aligned monospace code blocks.

    Telegram's Markdown parser does not render pipe tables — they show up
    as raw text with misaligned columns. We detect `| col | col |` tables
    (optionally with a `|---|---|` separator line), compute per-column
    widths, pad cells, and wrap the whole thing in triple backticks so
    Telegram renders it as a monospace block with columns that line up.
    """
    lines = text.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        # Detect start of a pipe table: a line beginning and ending with |
        # and containing at least one interior |
        if (stripped.startswith("|") and stripped.endswith("|")
                and stripped.count("|") >= 2):
            # Collect the whole table (contiguous pipe lines)
            table_lines = []
            while i < n:
                s = lines[i].strip()
                if s.startswith("|") and s.endswith("|") and s.count("|") >= 2:
                    table_lines.append(s)
                    i += 1
                else:
                    break
            # Need at least one data row
            if len(table_lines) >= 1:
                # Parse rows
                rows = []
                for tl in table_lines:
                    # Strip leading/trailing pipe, then split
                    inner = tl[1:-1]
                    cells = [c.strip() for c in inner.split("|")]
                    # Skip separator rows like |---|---|
                    if all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells):
                        continue
                    rows.append(cells)
                if rows:
                    # Normalize column count
                    ncols = max(len(r) for r in rows)
                    rows = [r + [""] * (ncols - len(r)) for r in rows]
                    widths = [max(len(r[c]) for r in rows) for c in range(ncols)]
                    rendered = []
                    for idx, r in enumerate(rows):
                        padded = "  ".join(r[c].ljust(widths[c]) for c in range(ncols))
                        rendered.append(padded.rstrip())
                        # Add underline after header row for readability
                        if idx == 0 and len(rows) > 1:
                            sep = "  ".join("-" * widths[c] for c in range(ncols))
                            rendered.append(sep)
                    out.append("```")
                    out.extend(rendered)
                    out.append("```")
                    continue
            # Fallback: emit original lines
            out.extend(table_lines)
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def send_message(chat_id, text, parse_mode="Markdown"):
    """Send a message, splitting if too long. Falls back to plain text on parse error."""
    text = format_tables_for_telegram(text)
    chunks = split_message(text)
    resp = None
    for chunk in chunks:
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        resp = tg_request("sendMessage", payload)
        # Fallback: if Markdown parsing fails, retry without parse_mode
        if not resp.get("ok") and parse_mode and "can\'t parse entities" in str(resp.get("error", "")):
            log.warning("Markdown parse failed, retrying as plain text")
            payload.pop("parse_mode", None)
            resp = tg_request("sendMessage", payload)
        if len(chunks) > 1:
            time.sleep(0.3)
    return resp


def send_message_get_id(chat_id, text, parse_mode="Markdown"):
    """Send a message and return the message_id (for later editing)."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    resp = tg_request("sendMessage", payload)
    if resp.get("ok"):
        return resp["result"]["message_id"]
    if parse_mode and "can\'t parse entities" in str(resp.get("error", "")):
        payload.pop("parse_mode", None)
        resp = tg_request("sendMessage", payload)
        if resp.get("ok"):
            return resp["result"]["message_id"]
    return None


def edit_message(chat_id, message_id, text, parse_mode="Markdown"):
    """Edit an existing message in-place."""
    if not message_id:
        return
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text[:MAX_MESSAGE_LEN],
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    resp = tg_request("editMessageText", payload)
    if not resp.get("ok") and parse_mode and "can\'t parse entities" in str(resp.get("error", "")):
        payload.pop("parse_mode", None)
        tg_request("editMessageText", payload)


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


# ── Conversation Context (per chat_id) ─────────────────────────────
_chat_history = {}          # chat_id -> [{"role": ..., "content": ...}, ...]
_history_lock = threading.Lock()
_max_history = {}           # chat_id -> int (per-chat override)


def _history_path(chat_id):
    return HISTORY_DIR / f"{chat_id}.json"


def _get_history(chat_id):
    """Return conversation history for a chat, loading from disk if needed."""
    with _history_lock:
        if chat_id not in _chat_history:
            path = _history_path(chat_id)
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    _chat_history[chat_id] = data.get("messages", [])
                    if "max_history" in data:
                        _max_history[chat_id] = data["max_history"]
                except (json.JSONDecodeError, KeyError):
                    _chat_history[chat_id] = []
            else:
                _chat_history[chat_id] = []
        return list(_chat_history[chat_id])


def _append_history(chat_id, role, content):
    """Append a message to history, trim, and persist."""
    with _history_lock:
        if chat_id not in _chat_history:
            _chat_history[chat_id] = []
        _chat_history[chat_id].append({"role": role, "content": content})
        max_turns = _max_history.get(chat_id, MAX_HISTORY_PER_CHAT)
        # Each turn = 2 messages (user + assistant), keep max_turns * 2 messages
        max_msgs = max_turns * 2
        if len(_chat_history[chat_id]) > max_msgs:
            _chat_history[chat_id] = _chat_history[chat_id][-max_msgs:]
        _save_history_unlocked(chat_id)


def _save_history_unlocked(chat_id):
    """Write history to disk (caller must hold _history_lock)."""
    data = {
        "messages": _chat_history.get(chat_id, []),
        "max_history": _max_history.get(chat_id, MAX_HISTORY_PER_CHAT),
        "updated": datetime.now().isoformat(),
    }
    _history_path(chat_id).write_text(json.dumps(data, indent=2))


def _clear_history(chat_id):
    """Clear conversation context for a chat."""
    with _history_lock:
        _chat_history[chat_id] = []
        _save_history_unlocked(chat_id)


def _format_history_prompt(chat_id):
    """Format conversation history as a prompt prefix."""
    history = _get_history(chat_id)
    if not history:
        return ""
    lines = ["Previous conversation:"]
    for msg in history:
        role = "User" if msg["role"] == "user" else "Assistant"
        # Truncate long messages in context
        content = msg["content"]
        if len(content) > 500:
            content = content[:500] + "... [truncated]"
        lines.append(f"{role}: {content}")
    return "\n".join(lines) + "\n\n"


# ── Long-Term Memory (per chat_id) ─────────────────────────────────
_memory_cache = {}          # chat_id -> [{"content": ..., "created": ...}, ...]
_memory_lock = threading.Lock()


def _memory_path(chat_id):
    return MEMORY_DIR / f"{chat_id}.json"


def _load_memory(chat_id):
    """Load memory facts from disk."""
    with _memory_lock:
        if chat_id not in _memory_cache:
            path = _memory_path(chat_id)
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    _memory_cache[chat_id] = data.get("facts", [])
                except (json.JSONDecodeError, KeyError):
                    _memory_cache[chat_id] = []
            else:
                _memory_cache[chat_id] = []
        return list(_memory_cache[chat_id])


def _save_memory(chat_id):
    """Persist memory to disk (caller must hold _memory_lock)."""
    data = {
        "facts": _memory_cache.get(chat_id, []),
        "updated": datetime.now().isoformat(),
    }
    _memory_path(chat_id).write_text(json.dumps(data, indent=2))


def _add_memory(chat_id, fact):
    """Add a fact to long-term memory."""
    with _memory_lock:
        if chat_id not in _memory_cache:
            _memory_cache[chat_id] = []
        _memory_cache[chat_id].append({
            "content": fact,
            "created": datetime.now().isoformat(),
        })
        _save_memory(chat_id)


def _remove_memory(chat_id, index):
    """Remove a memory fact by 1-based index. Returns the removed fact or None."""
    with _memory_lock:
        facts = _memory_cache.get(chat_id, [])
        if 1 <= index <= len(facts):
            removed = facts.pop(index - 1)
            _save_memory(chat_id)
            return removed
        return None


def _smart_remember_session(chat_id, n_turns=10):
    """
    Use Claude to extract durable facts from recent conversation history.

    Loads the last n_turns from this chat's history, calls `claude -p` with
    a focused extraction prompt, parses the response, and bulk-adds each
    fact to long-term memory via _add_memory().

    Returns (facts_added: list[str], error: str|None).
    """
    history = _get_history(chat_id)
    if not history:
        return [], "No conversation history to extract from."

    # Take the last n_turns * 2 messages (each turn = user + assistant)
    recent = history[-(n_turns * 2):]

    # Build compact transcript
    lines = []
    for msg in recent:
        role = "User" if msg["role"] == "user" else "Assistant"
        content = msg["content"]
        # Trim very long assistant outputs — facts live in first ~800 chars
        if role == "Assistant" and len(content) > 800:
            content = content[:800] + "... [truncated]"
        lines.append(f"{role}: {content}")
    transcript = "\n".join(lines)

    extraction_prompt = (
        "You are a memory extraction assistant. Read the conversation below and "
        "extract 3–8 durable facts worth storing in long-term memory.\n\n"
        "Rules:\n"
        "- Focus on: user preferences, active positions or trade ideas, key thresholds "
        "  they care about, ongoing analysis threads, explicit preferences or opinions.\n"
        "- Write one fact per line, plain text, no numbering, no bullet points.\n"
        "- Each fact must be a single sentence, self-contained (no pronouns like 'he/she/it').\n"
        "- Skip transient things (greetings, tool calls, raw numbers without context).\n"
        "- If there is nothing durable to extract, output exactly: NO_FACTS\n\n"
        f"Conversation:\n{transcript}\n\n"
        "Facts (one per line):"
    )

    try:
        result = subprocess.run(
            [
                "claude", "-p", extraction_prompt,
                "--model", "claude-haiku-4-5",
                "--output-format", "json",
                "--max-turns", "1",
            ],
            cwd=AGENT_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return [], f"Extraction subprocess failed (exit {result.returncode}): {result.stderr[:200]}"

        # Parse json output — result field contains the assistant text
        data = json.loads(result.stdout)
        text = data.get("result", "").strip()

        if not text or text == "NO_FACTS":
            return [], None

        facts = [line.strip() for line in text.splitlines() if line.strip() and line.strip() != "NO_FACTS"]
        for fact in facts:
            _add_memory(chat_id, fact)

        return facts, None

    except subprocess.TimeoutExpired:
        return [], "Extraction timed out (60s)."
    except (json.JSONDecodeError, KeyError) as e:
        return [], f"Failed to parse extraction output: {e}"
    except Exception as e:
        return [], f"Unexpected error: {e}"


def _format_memory_prompt(chat_id):
    """Format memory facts as a prompt prefix."""
    facts = _load_memory(chat_id)
    if not facts:
        return ""
    lines = ["Long-term memory for this user:"]
    for f in facts:
        lines.append(f"- {f['content']}")
    return "\n".join(lines) + "\n\n"


# ── Claude Session Persistence (per chat_id) — Tier A1 ─────────────
# Stores the Claude Code session UUID per chat so follow-up messages pass
# `--resume <session_id>`, giving full-fidelity conversation continuity
# (tool_use + tool_result replay) instead of the old lossy prefix injection.
_session_ids = {}
_session_lock = threading.Lock()


def _session_path(chat_id):
    return SESSIONS_DIR / f"{chat_id}.json"


def _get_session_id(chat_id):
    """Load the saved Claude session_id for this chat, or None if fresh."""
    with _session_lock:
        if chat_id not in _session_ids:
            path = _session_path(chat_id)
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    _session_ids[chat_id] = data.get("session_id")
                except (json.JSONDecodeError, KeyError):
                    _session_ids[chat_id] = None
            else:
                _session_ids[chat_id] = None
        return _session_ids[chat_id]


def _save_session_id(chat_id, session_id):
    """Persist the Claude session_id for this chat (pass None to clear)."""
    with _session_lock:
        _session_ids[chat_id] = session_id
        data = {
            "session_id": session_id,
            "updated": datetime.now().isoformat(),
        }
        _session_path(chat_id).write_text(json.dumps(data, indent=2))


# ── Tool Result Audit Persistence — Tier B2 ────────────────────────
# Every tool_result event from the stream-json channel is written to
# logs/tool_results/{chat_id}-YYYYMMDD/{turn:03d}.json so the user can
# verify what Claude actually saw (closes the "black box" gap vs Native).
def _save_tool_result(chat_id, turn, tool_name, tool_input, result_content):
    """Persist a tool_result payload to disk for audit."""
    try:
        today = datetime.now().strftime("%Y%m%d")
        date_dir = TOOL_RESULTS_DIR / f"{chat_id}-{today}"
        date_dir.mkdir(exist_ok=True)
        path = date_dir / f"{turn:03d}.json"
        payload = {
            "time": datetime.now().isoformat(),
            "turn": turn,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "result": result_content,
        }
        path.write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        log.warning(f"Failed to save tool_result: {e}")


# ── TodoWrite rendering — Tier A3 ──────────────────────────────────
def _format_todos(todos):
    """Render a TodoWrite `todos` list as a compact Telegram-friendly block."""
    if not todos:
        return ""
    lines = ["📋 Plan:"]
    for t in todos:
        status = (t.get("status") or "pending").lower()
        content = (t.get("content") or "").strip()
        if not content:
            continue
        if status == "completed":
            mark = "✅"
        elif status == "in_progress":
            mark = "🔄"
        else:
            mark = "☐"
        if len(content) > 80:
            content = content[:77] + "..."
        lines.append(f"  {mark} {content}")
    return "\n".join(lines)


# ── Claude Code Execution ──────────────────────────────────────────
# Track running tasks to prevent double-runs and support /stop.
# Value is the live subprocess.Popen handle (not just a sentinel) so /stop
# can call .terminate() mid-turn.  — Tier A4
_running_tasks = {}
_task_lock = threading.Lock()



def _describe_tool(name, tool_input):
    """Return a short human-readable description of a tool call."""
    if name == "Skill":
        skill = tool_input.get("skill", "")
        args = tool_input.get("args", "")
        return f"/{skill} {args}".strip() if skill else "skill"
    if name == "Bash":
        desc = tool_input.get("description", "")
        cmd = tool_input.get("command", "")
        if desc:
            return desc[:60]
        return (cmd[:60] + "...") if len(cmd) > 60 else cmd
    if name == "Read":
        fp = tool_input.get("file_path", "")
        return fp.split("/")[-1] if fp else "file"
    if name == "Grep":
        pattern = tool_input.get("pattern", "")
        return f"grep \"{pattern[:40]}\""
    if name == "Glob":
        return tool_input.get("pattern", "files")
    if name == "WebSearch":
        return tool_input.get("query", "web search")[:50]
    if name == "WebFetch":
        return tool_input.get("url", "url")[:50]
    return name

def _render_progress(command_name, elapsed_s, step_count, recent_steps,
                     current_todos, partial_tail, resumed, session_short):
    """Build the progress message content (used by the stream loop)."""
    head_bits = [f"🔄 `{command_name}` — {elapsed_s:.0f}s, step {step_count}"]
    if resumed:
        head_bits.append(f"(resumed {session_short})")
    elif session_short:
        head_bits.append(f"(new session {session_short})")
    parts = [" ".join(head_bits)]
    if current_todos:
        todos_block = _format_todos(current_todos)
        if todos_block:
            parts.append(todos_block)
    if recent_steps:
        parts.append("\n".join(recent_steps))
    if partial_tail:
        parts.append(f"💭 {partial_tail}")
    return "\n\n".join(parts)


def run_claude_command(prompt, chat_id, command_name="command"):
    """Run Claude Code with streaming progress updates via Telegram.

    Tier A+B behavior (2026-04-21):
      - A1 --resume:      passes prior session_id so Claude sees full tool
                          history, not a truncated text prefix.
      - A2 max-turns:     40 (was 25).
      - A3 TodoWrite:     renders current plan in the progress message.
      - A4 /stop:         stores Popen in _running_tasks for mid-turn kill.
      - B1 partial msgs:  --include-partial-messages; shows Claude's text tail.
      - B2 tool audit:    persists every tool_result to disk for review.
    """
    task_key = f"{chat_id}:{command_name}"

    with _task_lock:
        if task_key in _running_tasks:
            send_message(chat_id, f"\u23f3 `{command_name}` is already running. Use `/stop` to cancel.")
            return
        _running_tasks[task_key] = None  # placeholder; real Popen set below

    progress_msg_id = None
    proc = None
    try:
        progress_msg_id = send_message_get_id(
            chat_id, f"\U0001f504 `{command_name}` \u2014 starting..."
        )

        # Build prompt: memory prefix stays (user-curated facts) but history
        # prefix is dropped — session resume covers that now with higher fidelity.
        memory_prefix = _format_memory_prompt(chat_id)
        full_prompt = (
            memory_prefix
            + "Note: For email access, use tools/email_tools.py (search_emails, read_email, list_labels, send_email). Call via python3.\n\n"
            + "Formatting: When presenting tabular data, use Markdown pipe tables (| col | col |) with a |---|---| separator row. The Telegram bridge will render them as aligned monospace blocks.\n\n"
            + f"Current question: {prompt}"
        )

        prior_session_id = _get_session_id(chat_id)

        cmd = [
            "claude",
            "-p", full_prompt,
            "--model", "claude-opus-4-7[1m]",
            "--effort", "max",
            "--output-format", "stream-json",
            "--verbose",
            "--max-turns", str(MAX_TURNS_PER_CALL),
            "--allowedTools", "Bash(*)", "Read(*)", "Write(*)", "Edit(*)", "Glob(*)", "Grep(*)", "WebFetch(*)", "WebSearch(*)", "Skill(*)", "Agent(*)", "TodoWrite(*)",
            "mcp__9b9bb544-34fe-4786-a484-a59006d00c2d__gmail_search_messages",
            "mcp__9b9bb544-34fe-4786-a484-a59006d00c2d__gmail_read_message",
            "mcp__9b9bb544-34fe-4786-a484-a59006d00c2d__gmail_read_thread",
            "mcp__9b9bb544-34fe-4786-a484-a59006d00c2d__gmail_list_labels",
        ]
        if INCLUDE_PARTIAL_MESSAGES:
            cmd.append("--include-partial-messages")
        if prior_session_id:
            cmd.extend(["--resume", prior_session_id])

        log.info(
            f"Executing: {command_name} for chat {chat_id} "
            f"(resume={'yes' if prior_session_id else 'no'})"
        )
        start = time.time()

        proc = subprocess.Popen(
            cmd,
            cwd=AGENT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"},
        )
        # Register the live Popen handle so /stop can terminate it.
        with _task_lock:
            _running_tasks[task_key] = proc

        # Stream parser state
        final_result = ""
        steps = []
        last_update = 0.0
        turn_count = 0
        session_id_observed = prior_session_id
        resumed = bool(prior_session_id)
        current_todos = []
        partial_text_buf = []
        tool_use_map = {}    # tool_use_id -> (tool_name, tool_input)
        MIN_UPDATE_INTERVAL = 3  # seconds between Telegram edits (rate-limit)

        def _bump_progress(force=False):
            nonlocal last_update
            now = time.time()
            if not force and (now - last_update < MIN_UPDATE_INTERVAL):
                return
            if not progress_msg_id:
                return
            tail = ""
            if partial_text_buf:
                joined = "".join(partial_text_buf)
                tail = joined[-PARTIAL_TEXT_TAIL_CHARS:] if len(joined) > PARTIAL_TEXT_TAIL_CHARS else joined
                tail = tail.replace("`", "'")  # avoid accidental Markdown code fences
            short_sid = session_id_observed[:8] if session_id_observed else ""
            edit_message(
                chat_id, progress_msg_id,
                _render_progress(
                    command_name, now - start, turn_count, steps[-6:],
                    current_todos, tail, resumed, short_sid,
                ),
            )
            last_update = now

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type", "")

            # A1: capture session_id from init event (works for both fresh and resumed).
            if etype == "system" and event.get("subtype") == "init":
                sid = event.get("session_id")
                if sid:
                    session_id_observed = sid
                    _save_session_id(chat_id, sid)
                continue

            # B1: partial assistant-text deltas — buffer for "thinking" display.
            if etype == "stream_event":
                inner = event.get("event", {}) or {}
                if inner.get("type") == "content_block_delta":
                    delta = inner.get("delta", {}) or {}
                    if delta.get("type") == "text_delta":
                        chunk = delta.get("text", "")
                        if chunk:
                            partial_text_buf.append(chunk)
                            _bump_progress()
                continue

            # tool_use blocks arrive in `assistant` messages.
            if etype == "assistant":
                # A new full assistant message has arrived — clear partial buffer
                # (it's been superseded by the canonical message).
                partial_text_buf = []
                msg = event.get("message", {}) or {}
                content = msg.get("content", []) or []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        tool_name = block.get("name", "") or ""
                        tool_input = block.get("input", {}) or {}
                        tool_id = block.get("id", "")
                        tool_use_map[tool_id] = (tool_name, tool_input)
                        turn_count += 1

                        # A3: TodoWrite gets special treatment — render as Plan.
                        if tool_name == "TodoWrite":
                            current_todos = tool_input.get("todos", []) or []
                            step_text = f"📋 TodoWrite: {len([t for t in current_todos if (t.get('status') == 'in_progress')])} in progress / {len(current_todos)} total"
                        else:
                            desc = _describe_tool(tool_name, tool_input)
                            step_text = f"🔧 {tool_name}: {desc}"
                        steps.append(step_text)
                        _bump_progress()
                continue

            # tool_result blocks arrive in `user` messages (reverse channel).
            if etype == "user":
                msg = event.get("message", {}) or {}
                content = msg.get("content", []) or []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        tool_id = block.get("tool_use_id", "")
                        tname, tinput = tool_use_map.get(tool_id, ("unknown", {}))
                        result_content = block.get("content", "")
                        # B2: persist for audit
                        _save_tool_result(chat_id, turn_count, tname, tinput, result_content)
                continue

            # Final result event
            if etype == "result":
                final_result = event.get("result", "") or final_result
                continue

        proc.wait(timeout=CLAUDE_TIMEOUT)
        elapsed = time.time() - start

        output = final_result.strip() if final_result else "(no output)"

        # Keep the human-readable /history log in sync (display-only — session
        # resume does the real context carrying now).
        _append_history(chat_id, "user", prompt)
        _append_history(chat_id, "assistant", output)

        log.info(
            f"Completed {command_name} in {elapsed:.1f}s "
            f"(exit={proc.returncode}, turns={turn_count}, "
            f"session={session_id_observed[:8] if session_id_observed else 'none'})"
        )
        log_run(command_name, elapsed, proc.returncode, len(output))

        if progress_msg_id:
            tg_request("deleteMessage", {"chat_id": chat_id, "message_id": progress_msg_id})

        short_sid = session_id_observed[:8] if session_id_observed else ""
        resume_flag = "↻" if resumed else "✨"  # resumed vs fresh
        header = f"\u2705 `{command_name}` ({elapsed:.0f}s, {turn_count} steps, {resume_flag} {short_sid})\n\n"
        send_message(chat_id, header + output)

    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
        send_message(chat_id, f"\u23f0 `{command_name}` timed out after {CLAUDE_TIMEOUT}s.")
        log.warning(f"Timeout: {command_name}")

    except Exception as e:
        send_message(chat_id, f"\u274c Error running `{command_name}`: {e}")
        log.error(f"Error: {command_name}: {e}", exc_info=True)

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
    # Macro & Regime
    "scan": "run /fin scan",
    "scanfull": "run /fin scan full",
    "macro": "run /fin macro",
    "bonds": "run /fin bonds",
    "stress": "run /fin stress",
    "latecycle": "run /fin latecycle",
    "termpremium": "run /fin termpremium",
    "vixanalysis": "run /fin vixanalysis",
    "consumer": "run /fin consumer",
    "housing": "run /fin housing",
    "labor": "run /fin labor",
    "synthesize": "run /fin synthesize",
    # BTC
    "btc": "run /fin btc",
    "btctrend": "run /fin btc trend",
    "btcposition": "run /fin btc position",
    # Commodity
    "oil": "run /fin oil",
    # Yardeni
    "bbb": "run /fin bbb",
    "fsmi": "run /fin fsmi",
    "vigilantes": "run /fin vigilantes",
    "valuation": "run /fin valuation",
    "drawdown": "run /fin drawdown",
    # Pro Trader
    "riskpremium": "run /fin riskpremium",
    "crossasset": "run /fin crossasset",
    "pmregime": "run /fin pmregime",
    "usdregime": "run /fin usdregime",
    # Graham
    "grahamscreen": "run /fin grahamscreen",
    "netnet": "run /fin netnet",
    # Multi-step
    "full_report": "run /fin full_report",
    # Email
    # Email & Digest
    "email": "Check my recent emails using tools/email_tools.py. Call search_emails('newer_than:1d', 10) and show sender + subject for each.",
}

# Commands that take an argument
ARG_COMMANDS = {
    # Equity
    "analyze": "run /fin analyze {arg}",
    "compare": "run /fin compare {arg}",
    "peers": "run /fin peers {arg}",
    "allocation": "run /fin allocation {arg}",
    "balance": "run /fin balance {arg}",
    # Commodity
    "commodity": "run /fin commodity {arg}",
    # Technical Analysis
    "ta": "run /fin ta {arg}",
    "rsi": "run /fin rsi {arg}",
    "sr": "run /fin sr {arg}",
    "breakout": "run /fin breakout {arg}",
    "quickta": "run /fin quickta {arg}",
    "synthesis": "run /fin synthesis {arg}",
    # Graham
    "graham": "run /fin graham {arg}",
    # Pro Trader
    "sl": "run /fin sl {arg}",
    "drivers": "run /fin drivers {arg}",
    # Search & Digest
    "search": "run /fin search {arg}",
    "digest": "run /digest {arg}",
    # Email
    "emailsearch": "Search my emails using tools/email_tools.py: search_emails('{arg}', 10). Show sender, subject, snippet for each result.",
}


def handle_command(chat_id, text):
    """Parse and route a command or natural language message."""
    text = text.strip()
    if not text:
        return

    # ── Natural language (no / prefix) → implicit /ask ──
    if not text.startswith("/"):
        threading.Thread(
            target=run_claude_command, args=(text, chat_id, "ask"), daemon=True
        ).start()
        return

    parts = text.split(None, 1)
    cmd = parts[0].lstrip("/").lower().replace("@", "").split("@")[0]
    arg = parts[1].strip() if len(parts) > 1 else ""

    # ── Context & Memory commands (no Claude Code needed) ──
    if cmd == "history":
        history = _get_history(chat_id)
        if not history:
            send_message(chat_id, "No conversation history yet.")
            return
        max_h = _max_history.get(chat_id, MAX_HISTORY_PER_CHAT)
        lines = [f"💬 *Conversation Context* ({len(history)} messages, max {max_h} turns)\n"]
        for i, msg in enumerate(history[-20:], 1):  # show last 20 messages
            role = "👤" if msg["role"] == "user" else "🤖"
            content = msg["content"]
            if len(content) > 200:
                content = content[:200] + "..."
            lines.append(f"{role} {content}\n")
        send_message(chat_id, "\n".join(lines))
        return

    if cmd == "clear":
        _clear_history(chat_id)
        send_message(chat_id, "🗑 Conversation context cleared. (Use `/newsession` to also reset the underlying Claude session thread.)")
        return

    if cmd == "newsession":
        prior = _get_session_id(chat_id)
        _save_session_id(chat_id, None)
        if prior:
            send_message(
                chat_id,
                f"🆕 Claude session reset (was `{prior[:8]}`).\n\n"
                f"Next message starts a fresh thread — CLAUDE.md + skills reload, prior tool outputs won't carry over. "
                f"Long-term memory (`/memory`) is unaffected."
            )
        else:
            send_message(chat_id, "🆕 No active Claude session to reset. Next message will start fresh.")
        return

    if cmd == "stop":
        # Tier A4: terminate every running subprocess for this chat_id.
        stopped = []
        with _task_lock:
            for k, v in list(_running_tasks.items()):
                if not k.startswith(f"{chat_id}:"):
                    continue
                if v is None:
                    continue
                try:
                    if v.poll() is None:  # still running
                        v.terminate()
                        stopped.append(k.split(":", 1)[1])
                except Exception as e:
                    log.warning(f"Failed to terminate {k}: {e}")
        if stopped:
            send_message(chat_id, f"🛑 Terminated: `{', '.join(stopped)}`")
        else:
            send_message(chat_id, "No running tasks to stop.")
        return

    if cmd == "sethistory":
        if not arg or not arg.isdigit():
            send_message(chat_id, "Usage: `/sethistory <number>` (e.g. `/sethistory 30`)")
            return
        n = int(arg)
        with _history_lock:
            _max_history[chat_id] = n
            _save_history_unlocked(chat_id)
        send_message(chat_id, f"Max history set to {n} turns.")
        return

    if cmd == "remember":
        if not arg:
            send_message(chat_id, "Usage: `/remember <fact to save>`")
            return
        _add_memory(chat_id, arg)
        count = len(_load_memory(chat_id))
        send_message(chat_id, f"💾 Saved to memory ({count} facts total):\n_{arg}_")
        return

    if cmd == "remember_session":
        # LLM-powered: extract durable facts from recent conversation history.
        # Optional arg: number of turns to scan (default 30).
        n_turns = int(arg) if arg and arg.isdigit() else 30
        history = _get_history(chat_id)[-n_turns:]
        if len(history) < 2:
            send_message(chat_id, "Not enough conversation history to extract from.")
            return
        send_message(chat_id, f"\U0001f9e0 Scanning last {len(history)} turns for durable facts...")

        # Build transcript — truncate long assistant outputs to keep prompt size sane
        transcript_lines = []
        for msg in history:
            role = "User" if msg["role"] == "user" else "Assistant"
            content = msg["content"]
            if role == "Assistant" and len(content) > 600:
                content = content[:600] + "... [truncated]"
            transcript_lines.append(f"{role}: {content}")
        transcript = "\n".join(transcript_lines)

        extraction_prompt = (
            "You are a memory extraction assistant. Read the conversation transcript below "
            "and extract 3–10 durable facts worth remembering across future sessions. "
            "Focus on: user preferences, trading/investing beliefs, recurring topics, "
            "portfolio positions or watchlist items mentioned, and any explicit 'remember X' "
            "instructions. Exclude ephemeral data (exact prices, today's news). "
            "IMPORTANT: Output ONLY a raw JSON array of strings — no explanation, no markdown "
            "fences, no preamble. If nothing durable, output: []\n\n"
            "Example output: [\"User trades ES futures\", \"Interested in Geo Chen newsletters\"]\n\n"
            f"Transcript:\n{transcript}"
        )

        try:
            result = subprocess.run(
                [
                    "claude", "-p", extraction_prompt,
                    "--model", "claude-haiku-4-5-20251001",
                    "--output-format", "text",  # plain text — no outer JSON wrapper
                    "--max-turns", "3",          # allow tool-use + follow-up if needed
                ],
                cwd=AGENT_DIR,
                capture_output=True,
                text=True,
                timeout=90,
            )
            raw = result.stdout.strip()
            if not raw:
                raise ValueError(f"Empty output (exit={result.returncode}, stderr={result.stderr[:100]})")
            # Strip markdown code fences if present
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
            facts = json.loads(raw)
            if not isinstance(facts, list):
                raise ValueError(f"Expected JSON array, got: {type(facts).__name__}")
            facts = [str(f).strip() for f in facts if str(f).strip()]
        except Exception as e:
            send_message(chat_id, f"❌ Extraction failed: {e}\nRaw output: {result.stdout[:300]}")
            return

        if not facts:
            send_message(chat_id, "No durable facts found in recent conversation.")
            return

        for fact in facts:
            _add_memory(chat_id, fact)

        total = len(_load_memory(chat_id))
        lines = [f"💾 *Extracted {len(facts)} facts* (total: {total})\n"]
        for i, f in enumerate(facts, 1):
            lines.append(f"`{i}.` {f}")
        send_message(chat_id, "\n".join(lines))
        return

    if cmd == "forget":
        if not arg or not arg.isdigit():
            send_message(chat_id, "Usage: `/forget <number>` (1-based index from /memory)")
            return
        removed = _remove_memory(chat_id, int(arg))
        if removed:
            send_message(chat_id, f"🗑 Removed memory: _{removed['content']}_")
        else:
            send_message(chat_id, f"Invalid index. Use /memory to see available entries.")
        return

    if cmd == "memory":
        facts = _load_memory(chat_id)
        if not facts:
            send_message(chat_id, "No memories saved. Use `/remember <fact>` to add one.")
            return
        lines = ["🧠 *Long-Term Memory*\n"]
        for i, f in enumerate(facts, 1):
            created = f.get("created", "?")[:10]
            lines.append(f"`{i}.` {f['content']} _({created})_")
        send_message(chat_id, "\n".join(lines))
        return

    # ── Built-in commands (no Claude Code needed) ──
    if cmd == "start":
        send_message(
            chat_id,
            "🤖 *Financial Agent Bot*\n\n"
            "Claude Code financial analysis on Hostinger VPS.\n"
            "Just type naturally — no `/` prefix needed!\n\n"
            "*Macro & Regime:*\n"
            "/scan — Indicator scan (/scan full for all)\n"
            "/macro — Macro regime\n"
            "/stress — Financial stress score\n"
            "/bonds — Bond market analysis\n"
            "/synthesize — Full cross-asset synthesis\n"
            "/full\\_report — 8-step briefing\n\n"
            "*BTC & Commodities:*\n"
            "/btc — BTC futures analysis\n"
            "/oil — Crude oil analysis\n"
            "/commodity ASSET — Commodity outlook\n\n"
            "*Equity & TA:*\n"
            "/analyze TICKER — Equity deep-dive\n"
            "/ta ASSET — Technical analysis\n"
            "/graham TICKER — Value analysis\n\n"
            "*Context & Memory:*\n"
            "/history — View conversation log\n"
            "/clear — Clear /history log\n"
            "/newsession — Reset Claude session thread\n"
            "/stop — Interrupt running task\n"
            "/remember FACT — Save to long-term memory\n"
            "/remember\\_session — Auto-extract facts from recent chat (LLM)\n"
            "/memory — View saved memories\n"
            "/forget N — Remove a memory\n\n"
            "*Personal Finance:*\n"
            "/pfin — Show PFin usage guide\n"
            "/pfin brief — Daily portfolio briefing\n"
            "/pfin pf\\_deep [TICKER] — Deep position review\n"
            "/pfin watchlist\\_review — Watchlist state check\n"
            "/pfin track\\_email QUERY — Extract tickers from email\n\n"
            "*Other:*\n"
            "/digest — Newsletter digest\n"
            "/health — System status\n"
            "/help — All commands",
        )
        return

    if cmd == "help":
        lines = [
            "🤖 *All Commands*\n",
            "💡 *Tip:* Just type naturally without `/` for freeform questions!\n",
            "*No-arg commands:*",
        ]
        for k in sorted(COMMAND_MAP):
            lines.append("  /" + k.replace("_", r"\_"))
        lines.append("\n*Commands with argument:*")
        for k in sorted(ARG_COMMANDS):
            lines.append("  /" + k.replace("_", r"\_") + " <arg>")
        lines.append("\n*Context & Memory:*")
        lines.append("  /history — View conversation context (display only)")
        lines.append("  /clear — Clear /history log")
        lines.append("  /sethistory N — Set max history turns")
        lines.append("  /newsession — Reset underlying Claude session (fresh thread)")
        lines.append("  /stop — Interrupt the currently-running task")
        lines.append("  /remember FACT — Save to long-term memory")
        lines.append(r"  /remember\_session [N] — LLM auto-extract facts from last N turns")
        lines.append("  /memory — View saved memories")
        lines.append("  /forget N — Remove a memory by index")
        lines.append("\n*Personal Finance:*")
        lines.append("  /pfin — Usage guide")
        lines.append("  /pfin brief — Daily portfolio briefing")
        lines.append(r"  /pfin pf\_deep [TICKER] — Deep review (full portfolio or single name)")
        lines.append(r"  /pfin watchlist\_review — Watchlist state check")
        lines.append(r"  /pfin track\_email QUERY — Extract tickers from email")
        lines.append("  /pfin approve IDs — Promote DRAFT → ACTIVE")
        lines.append("  /pfin cancel ID — Mark watchlist entry CANCELLED")
        lines.append("\n*Skills (invoke via /ask):*")
        lines.append("  /ask run /trade_idea_review — Generate + review trade ideas, ES stance")
        lines.append("  /ask run /trade_idea_review cancel N — Cancel trade #N")
        lines.append("  /ask run /RnR_agent — Newsletter framework discovery + critique")
        lines.append("  /ask run /RnR_agent 7 — RnR with 7-day lookback")
        lines.append("  /ask run /digest_ES — ES newsletter digest (9 sources)")
        lines.append("  /ask run /digest — General macro newsletter digest")
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

    if cmd == "relogin_ibkr":
        if chat_id != "1130846055":
            return
        threading.Thread(target=run_relogin_ibkr, args=(chat_id,), daemon=True).start()
        return

    # ── PFin dispatcher (works with or without subcommand) ──
    if cmd == "pfin":
        # Forward everything after /pfin verbatim to the /pfin skill.
        # Empty arg → skill prints usage guide. Otherwise skill dispatches
        # on the first token of arg (brief, pf_deep, track_email, etc.)
        prompt = f"run /pfin {arg}".rstrip()
        task_name = f"pfin {arg}".strip() if arg else "pfin"
        threading.Thread(
            target=run_claude_command, args=(prompt, chat_id, task_name), daemon=True
        ).start()
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

    # Unknown /command → treat as freeform question
    send_message(chat_id, f"Unknown command: `/{cmd}`. Try /help")


# ── Health / Status (no Claude Code needed) ─────────────────────────
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
    history_count = len(_get_history(chat_id))
    memory_count = len(_load_memory(chat_id))
    sid = _get_session_id(chat_id)
    sid_display = f"`{sid[:8]}…`" if sid else "_none (fresh on next msg)_"
    send_message(
        chat_id,
        f"🤖 *Bot Status*\n\n"
        f"Uptime: `{uptime}`\n"
        f"Active tasks: `{active_count}`\n"
        f"Claude session: {sid_display}\n"
        f"Context log: `{history_count}` msgs\n"
        f"Memory facts: `{memory_count}`\n"
        f"Model: `claude-opus-4-7[1m]` (effort=max, max-turns={MAX_TURNS_PER_CALL})\n"
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
                {"offset": offset, "timeout": 25, "allowed_updates": ["message"]},
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
                if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
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
