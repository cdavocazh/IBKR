# AGENTS.md

This file is a stub. The authoritative project instructions for Claude Code,
Codex CLI, OpenCode, and other coding agents live in [`CLAUDE.md`](CLAUDE.md).

**Why a stub instead of a copy?** Some agents auto-load `AGENTS.md`, others
auto-load `CLAUDE.md`. We maintain a single source (`CLAUDE.md`) so they
never drift out of sync.

If your agent doesn't follow this stub, point it at `CLAUDE.md` directly:
- Codex CLI: `codex --instructions ./CLAUDE.md`
- OpenCode: `opencode --rules ./CLAUDE.md`
- Cursor / Copilot: add `CLAUDE.md` to the rules / instructions section

For session status and what's currently deployed, see [`STATUS.md`](STATUS.md).
