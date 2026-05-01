"""Telegram-friendly IBKR portfolio and watchlist helpers."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ib_insync import Contract, Stock

from ibkr.connection import IBKRConnection

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = PROJECT_ROOT / "data" / "telegram" / "ibkr_bot_state.json"
DEFAULT_BOT_CLIENT_ID = int(os.environ.get("IBKR_BOT_CLIENT_ID", "31"))

_STOPWORDS = {
    "A",
    "ACCOUNT",
    "ACCOUNTS",
    "ADD",
    "ALERT",
    "ALERTS",
    "ALL",
    "AND",
    "ANY",
    "ARE",
    "AT",
    "BIG",
    "BIGGEST",
    "BY",
    "CHECK",
    "CLEAR",
    "CURRENT",
    "DELETE",
    "DISPLAY",
    "FOR",
    "FROM",
    "HELP",
    "HIGH",
    "HOLDING",
    "HOLDINGS",
    "HOW",
    "I",
    "IF",
    "IN",
    "IS",
    "IT",
    "LARGEST",
    "LEVEL",
    "LEVELS",
    "LIST",
    "LOCAL",
    "MARKET",
    "ME",
    "MORE",
    "MOVE",
    "MOVEMENT",
    "MOVEMENTS",
    "MOVES",
    "MY",
    "OF",
    "ON",
    "OVER",
    "PLEASE",
    "PORTFOLIO",
    "PORTFOLIOS",
    "PRICE",
    "PRICES",
    "QUOTE",
    "QUOTES",
    "REGISTER",
    "REMOVE",
    "SAVE",
    "SEE",
    "SET",
    "SHOW",
    "SOME",
    "STORE",
    "TELL",
    "THAN",
    "THAT",
    "THE",
    "THESE",
    "TICKER",
    "TICKERS",
    "TO",
    "TOP",
    "VALUE",
    "VALUES",
    "VPS",
    "WATCHLIST",
    "WATCHLISTS",
    "WHAT",
    "WHATS",
    "WHEN",
    "WORTH",
}

_HELP_TEXT = (
    "IBKR command examples:\n"
    "/IBKR portfolio value\n"
    "/IBKR value of AAPL and NVDA\n"
    "/IBKR add AAPL,MSFT,NVDA to my watchlist\n"
    "/IBKR show my watchlist prices\n"
    "/IBKR top 5 tickers by market value\n"
    "/IBKR show prices for AAPL and TSLA\n"
    "/IBKR alert me if my watchlist moves more than 3%\n"
    "/IBKR check alerts\n"
    "/IBKR clear watchlist"
)


@dataclass
class ParsedPrompt:
    """Normalized representation of a /IBKR prompt."""

    intent: str
    raw_prompt: str
    symbols: list[str] = field(default_factory=list)
    account: Optional[str] = None
    top_n: int = 5
    threshold_pct: Optional[float] = None
    scope: str = "portfolio"


class BotStateStore:
    """Small JSON store for watchlists and alert settings."""

    def __init__(self, path: Path | str = DEFAULT_STATE_PATH):
        self.path = Path(path)

    def _default_state(self) -> dict:
        return {"watchlists": {}, "alerts": {}}

    def _load(self) -> dict:
        if not self.path.exists():
            return self._default_state()
        try:
            data = json.loads(self.path.read_text())
            if isinstance(data, dict):
                data.setdefault("watchlists", {})
                data.setdefault("alerts", {})
                return data
        except Exception:
            pass
        return self._default_state()

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True))

    def get_watchlist(self, chat_id: str) -> list[str]:
        data = self._load()
        items = data["watchlists"].get(str(chat_id), [])
        if not isinstance(items, list):
            return []
        return [str(item).upper() for item in items]

    def add_watchlist(self, chat_id: str, symbols: list[str]) -> list[str]:
        data = self._load()
        current = self.get_watchlist(chat_id)
        merged = _dedupe(current + [s.upper() for s in symbols])
        data["watchlists"][str(chat_id)] = merged
        self._save(data)
        return merged

    def remove_watchlist(self, chat_id: str, symbols: list[str]) -> list[str]:
        data = self._load()
        remove = {s.upper() for s in symbols}
        current = [s for s in self.get_watchlist(chat_id) if s not in remove]
        data["watchlists"][str(chat_id)] = current
        self._save(data)
        return current

    def clear_watchlist(self, chat_id: str) -> None:
        data = self._load()
        data["watchlists"][str(chat_id)] = []
        self._save(data)

    def get_alert(self, chat_id: str) -> dict:
        data = self._load()
        alert = data["alerts"].get(str(chat_id), {})
        return alert if isinstance(alert, dict) else {}

    def set_alert(self, chat_id: str, threshold_pct: float, scope: str) -> dict:
        data = self._load()
        payload = {
            "threshold_pct": float(threshold_pct),
            "scope": "watchlist" if scope == "watchlist" else "portfolio",
        }
        data["alerts"][str(chat_id)] = payload
        self._save(data)
        return payload


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _clean_prompt(prompt: str) -> str:
    return re.sub(r"^/ibkr(?:@\w+)?\b", "", prompt.strip(), flags=re.IGNORECASE).strip()


def _extract_symbols(prompt: str) -> list[str]:
    tokens = re.findall(r"\b[A-Za-z][A-Za-z.\-]{0,5}\b", prompt)
    symbols: list[str] = []
    for token in tokens:
        upper = token.upper().strip(".-")
        if not upper or upper in _STOPWORDS:
            continue
        if any(ch.isdigit() for ch in upper):
            continue
        symbols.append(upper)
    return _dedupe(symbols)


def _extract_account(prompt: str) -> Optional[str]:
    match = re.search(r"\baccount\s+([A-Za-z0-9]+)\b", prompt, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def _extract_threshold(prompt: str) -> Optional[float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", prompt)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _extract_top_n(prompt: str) -> int:
    match = re.search(r"\btop\s+(\d+)\b", prompt, flags=re.IGNORECASE)
    if not match:
        return 5
    try:
        return max(1, min(int(match.group(1)), 20))
    except ValueError:
        return 5


def parse_prompt(prompt: str) -> ParsedPrompt:
    """Parse a natural-language /IBKR prompt into a simple intent."""
    clean = _clean_prompt(prompt)
    if not clean:
        return ParsedPrompt(intent="help", raw_prompt=prompt)

    lower = clean.lower()
    symbols = _extract_symbols(clean)
    account = _extract_account(clean)
    threshold_pct = _extract_threshold(clean)
    top_n = _extract_top_n(clean)
    scope = "watchlist" if "watchlist" in lower else "portfolio"

    if any(word in lower for word in ("help", "what can you do", "examples")):
        return ParsedPrompt("help", prompt)

    if "watchlist" in lower and "clear" in lower:
        return ParsedPrompt("clear_watchlist", prompt)

    if "watchlist" in lower and any(word in lower for word in ("add", "store", "save", "put")):
        return ParsedPrompt("add_watchlist", prompt, symbols=symbols)

    if "watchlist" in lower and any(word in lower for word in ("remove", "delete", "drop")):
        return ParsedPrompt("remove_watchlist", prompt, symbols=symbols)

    if "alert" in lower and any(word in lower for word in ("set", "save", "store", "when", "if")):
        return ParsedPrompt(
            "set_alert",
            prompt,
            symbols=symbols,
            threshold_pct=threshold_pct,
            scope=scope,
            account=account,
        )

    if "watchlist" in lower and any(
        word in lower for word in ("show", "list", "price", "prices", "level", "levels", "quote", "quotes")
    ):
        return ParsedPrompt("watchlist_prices", prompt, scope=scope)

    if "top" in lower and any(word in lower for word in ("market value", "biggest", "largest")):
        return ParsedPrompt("top_holdings", prompt, account=account, top_n=top_n, scope=scope)

    if any(word in lower for word in ("alert", "alerts", "mover", "movers", "movement", "movements")):
        return ParsedPrompt(
            "check_alerts",
            prompt,
            symbols=symbols,
            threshold_pct=threshold_pct,
            scope=scope,
            account=account,
        )

    if any(phrase in lower for phrase in ("portfolio value", "whole portfolio", "entire portfolio", "net liquidation")):
        return ParsedPrompt("portfolio_value", prompt, account=account, scope=scope)

    if symbols and any(phrase in lower for phrase in ("value of", "worth of", "holding value", "holdings value")):
        return ParsedPrompt("holdings_value", prompt, symbols=symbols, account=account, scope=scope)

    if symbols and any(word in lower for word in ("price", "prices", "level", "levels", "quote", "quotes")):
        return ParsedPrompt("symbol_prices", prompt, symbols=symbols, account=account, scope=scope)

    if "portfolio" in lower and "value" in lower:
        return ParsedPrompt("portfolio_value", prompt, account=account, scope=scope)

    if symbols:
        return ParsedPrompt("holdings_value", prompt, symbols=symbols, account=account, scope=scope)

    return ParsedPrompt("help", prompt)


def _qualify_contract(ib, contract, cache: dict[int, Contract]):
    con_id = contract.conId
    if con_id in cache:
        return cache[con_id]

    try:
        if contract.secType == "STK" and contract.currency == "USD":
            qualified = Stock(contract.symbol, "SMART", "USD")
        else:
            qualified = Contract(conId=con_id)

        result = ib.qualifyContracts(qualified)
        if result:
            cache[con_id] = qualified
            return qualified
    except Exception:
        pass
    return None


def _extract_price_fields(ticker) -> dict:
    current_price = None
    price_source = None

    if ticker.last and ticker.last > 0:
        current_price = ticker.last
        price_source = "last"
    elif ticker.close and ticker.close > 0:
        current_price = ticker.close
        price_source = "close"
    elif ticker.bid and ticker.bid > 0 and ticker.ask and ticker.ask > 0:
        current_price = (ticker.bid + ticker.ask) / 2
        price_source = "mid"
    elif ticker.bid and ticker.bid > 0:
        current_price = ticker.bid
        price_source = "bid"

    prev_close = ticker.close if ticker.close and ticker.close > 0 else None
    change = None
    change_pct = None
    if current_price is not None and prev_close is not None and prev_close > 0:
        change = round(current_price - prev_close, 4)
        change_pct = round(change / prev_close * 100, 2)

    return {
        "current_price": round(current_price, 4) if current_price is not None else None,
        "prev_close": round(prev_close, 4) if prev_close is not None else None,
        "change": change,
        "change_pct": change_pct,
        "price_source": price_source,
    }


def _fetch_market_prices(ib, position_items, contract_cache: dict[int, Contract]) -> dict[int, dict]:
    prices: dict[int, dict] = {}
    tickers = []
    contracts_for_cancel = []
    seen_con_ids: set[int] = set()

    for item in position_items:
        con_id = item.contract.conId
        if con_id in seen_con_ids:
            continue
        seen_con_ids.add(con_id)

        qualified = _qualify_contract(ib, item.contract, contract_cache)
        if qualified is None:
            continue

        try:
            ticker = ib.reqMktData(qualified, "221,588", False, False)
            tickers.append((con_id, ticker))
            contracts_for_cancel.append(qualified)
        except Exception:
            pass

    if tickers:
        ib.sleep(3)

    for con_id, ticker in tickers:
        prices[con_id] = _extract_price_fields(ticker)

    for qualified in contracts_for_cancel:
        try:
            ib.cancelMktData(qualified)
        except Exception:
            pass

    return prices


def fetch_portfolio_snapshot(account: Optional[str] = None) -> dict:
    """Return a multi-account portfolio snapshot using live IBKR data."""
    conn = IBKRConnection(client_id=DEFAULT_BOT_CLIENT_ID)
    contract_cache: dict[int, Contract] = {}

    with conn.session() as ib:
        position_items = ib.positions()
        prices = _fetch_market_prices(ib, position_items, contract_cache)

        positions: list[dict] = []
        for item in position_items:
            if account and item.account.upper() != account.upper():
                continue

            contract = item.contract
            multiplier = float(contract.multiplier) if contract.multiplier else 1.0
            price_data = prices.get(contract.conId, {})
            current_price = price_data.get("current_price")
            prev_close = price_data.get("prev_close")

            market_value = None
            unrealized_pnl = None
            pnl_pct = None
            daily_pnl = None
            if current_price is not None:
                market_value = current_price * item.position * multiplier
                cost_basis = item.avgCost * item.position
                unrealized_pnl = market_value - cost_basis
                if cost_basis != 0:
                    pnl_pct = round(unrealized_pnl / abs(cost_basis) * 100, 2)
                if prev_close is not None and prev_close > 0:
                    daily_pnl = round((current_price - prev_close) * item.position * multiplier, 2)

            positions.append(
                {
                    "account": item.account,
                    "symbol": contract.symbol,
                    "local_symbol": contract.localSymbol or contract.symbol,
                    "sec_type": contract.secType,
                    "exchange": contract.exchange or contract.primaryExchange or "",
                    "currency": contract.currency,
                    "position_size": item.position,
                    "avg_cost": round(item.avgCost, 4),
                    "multiplier": multiplier,
                    "con_id": contract.conId,
                    "current_price": current_price,
                    "prev_close": prev_close,
                    "change": price_data.get("change"),
                    "change_pct": price_data.get("change_pct"),
                    "market_value": round(market_value, 2) if market_value is not None else None,
                    "unrealized_pnl": round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
                    "pnl_pct": pnl_pct,
                    "daily_pnl": daily_pnl,
                }
            )

        acct_net_liq: dict[str, float] = {}
        acct_avail_funds: dict[str, float] = {}
        acct_total_value: dict[str, float] = {}
        acct_maint_margin: dict[str, float] = {}
        acct_summary_unrealized: dict[str, float] = {}
        try:
            for av in ib.accountSummary():
                if av.account == "All":
                    continue
                if account and av.account.upper() != account.upper():
                    continue
                try:
                    value = float(av.value)
                except (TypeError, ValueError):
                    continue
                if av.tag == "NetLiquidation":
                    acct_net_liq[av.account] = value
                elif av.tag == "AvailableFunds":
                    acct_avail_funds[av.account] = value
                elif av.tag == "GrossPositionValue":
                    acct_total_value[av.account] = value
                elif av.tag == "MaintMarginReq":
                    acct_maint_margin[av.account] = value
                elif av.tag == "UnrealizedPnL":
                    acct_summary_unrealized[av.account] = value
        except Exception:
            pass

        acct_unrealized_pnl: dict[str, float] = {}
        acct_realized_pnl: dict[str, float] = {}
        try:
            for av in ib.accountValues():
                if av.currency != "BASE":
                    continue
                if account and av.account.upper() != account.upper():
                    continue
                try:
                    value = float(av.value)
                except (TypeError, ValueError):
                    continue
                if av.tag == "UnrealizedPnL":
                    acct_unrealized_pnl[av.account] = value
                elif av.tag == "RealizedPnL":
                    acct_realized_pnl[av.account] = value
        except Exception:
            pass

        all_accounts = sorted(
            set([p["account"] for p in positions]) | set(acct_net_liq.keys())
        )
        summaries: dict[str, dict] = {}
        for acct_id in all_accounts:
            acct_positions = [p for p in positions if p["account"] == acct_id]
            total_unrealized = acct_summary_unrealized.get(
                acct_id, acct_unrealized_pnl.get(acct_id, 0.0)
            )
            cost_basis_total = sum(abs(p["position_size"]) * p["avg_cost"] for p in acct_positions)
            summaries[acct_id] = {
                "position_count": len(acct_positions),
                "total_market_value": acct_total_value.get(acct_id),
                "total_unrealized_pnl": total_unrealized,
                "total_realized_pnl": acct_realized_pnl.get(acct_id, 0.0),
                "net_liquidation": acct_net_liq.get(acct_id),
                "available_funds": acct_avail_funds.get(acct_id),
                "maint_margin_req": acct_maint_margin.get(acct_id),
                "total_pnl_pct": round(total_unrealized / cost_basis_total * 100, 2)
                if cost_basis_total > 0 and total_unrealized is not None
                else None,
            }

        return {
            "accounts": all_accounts,
            "positions": positions,
            "summaries": summaries,
        }


def fetch_quotes(symbols: list[str], known_positions: Optional[list[dict]] = None) -> list[dict]:
    """Fetch quotes for symbols, reusing portfolio prices when available."""
    symbols = _dedupe([s.upper() for s in symbols if s])
    if not symbols:
        return []

    known_positions = known_positions or []
    existing: dict[str, dict] = {}
    for position in known_positions:
        for key in {position.get("symbol", ""), position.get("local_symbol", "")}:
            upper = str(key).upper()
            if upper and upper not in existing and position.get("current_price") is not None:
                existing[upper] = {
                    "symbol": upper,
                    "current_price": position.get("current_price"),
                    "prev_close": position.get("prev_close"),
                    "change": position.get("change"),
                    "change_pct": position.get("change_pct"),
                    "price_source": "portfolio",
                }

    remaining = [symbol for symbol in symbols if symbol not in existing]
    results = [existing[symbol] for symbol in symbols if symbol in existing]
    if not remaining:
        return results

    conn = IBKRConnection(client_id=DEFAULT_BOT_CLIENT_ID)
    with conn.session() as ib:
        tickers = []
        contracts = []
        for symbol in remaining:
            contract = Stock(symbol, "SMART", "USD")
            try:
                qualified = ib.qualifyContracts(contract)
                if not qualified:
                    continue
                contract = qualified[0]
                ticker = ib.reqMktData(contract, "221", False, False)
                tickers.append((symbol, ticker))
                contracts.append(contract)
            except Exception:
                continue

        if tickers:
            ib.sleep(2)

        fetched: dict[str, dict] = {}
        for symbol, ticker in tickers:
            payload = _extract_price_fields(ticker)
            payload["symbol"] = symbol
            payload["price_source"] = "ibkr"
            fetched[symbol] = payload

        for contract in contracts:
            try:
                ib.cancelMktData(contract)
            except Exception:
                pass

    missing = [symbol for symbol in remaining if symbol not in fetched or fetched[symbol].get("current_price") is None]
    if missing:
        fetched.update(_fetch_yfinance_quotes(missing))

    for symbol in remaining:
        if symbol in fetched:
            results.append(fetched[symbol])

    results_by_symbol = {item["symbol"]: item for item in results}
    return [results_by_symbol[symbol] for symbol in symbols if symbol in results_by_symbol]


def _fetch_yfinance_quotes(symbols: list[str]) -> dict[str, dict]:
    quotes: dict[str, dict] = {}
    try:
        import yfinance as yf

        tickers = yf.Tickers(" ".join(symbols))
        for symbol in symbols:
            try:
                info = tickers.tickers[symbol].fast_info
                current_price = getattr(info, "last_price", None)
                prev_close = getattr(info, "previous_close", None)
                change = None
                change_pct = None
                if current_price is not None and prev_close:
                    change = round(current_price - prev_close, 4)
                    change_pct = round(change / prev_close * 100, 2)
                quotes[symbol] = {
                    "symbol": symbol,
                    "current_price": round(current_price, 4) if current_price is not None else None,
                    "prev_close": round(prev_close, 4) if prev_close is not None else None,
                    "change": change,
                    "change_pct": change_pct,
                    "price_source": "yfinance",
                }
            except Exception:
                continue
    except Exception:
        pass
    return quotes


def _money(value: Optional[float]) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def _symbol_display(position: dict) -> str:
    return position.get("local_symbol") or position.get("symbol") or "?"


def _match_positions(positions: list[dict], symbols: list[str]) -> tuple[list[dict], list[str]]:
    requested = {symbol.upper() for symbol in symbols}
    matched = []
    seen_symbols: set[str] = set()
    for position in positions:
        keys = {
            str(position.get("symbol", "")).upper(),
            str(position.get("local_symbol", "")).upper(),
        }
        if keys & requested:
            matched.append(position)
            seen_symbols |= keys & requested
    missing = [symbol for symbol in symbols if symbol.upper() not in seen_symbols]
    return matched, missing


def _aggregate_positions(positions: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for position in positions:
        key = _symbol_display(position).upper()
        bucket = grouped.setdefault(
            key,
            {
                "symbol": key,
                "position_size": 0.0,
                "market_value": 0.0,
                "unrealized_pnl": 0.0,
                "daily_pnl": 0.0,
                "current_price": position.get("current_price"),
                "change_pct": position.get("change_pct"),
                "accounts": set(),
            },
        )
        bucket["position_size"] += float(position.get("position_size") or 0.0)
        bucket["market_value"] += float(position.get("market_value") or 0.0)
        bucket["unrealized_pnl"] += float(position.get("unrealized_pnl") or 0.0)
        bucket["daily_pnl"] += float(position.get("daily_pnl") or 0.0)
        bucket["accounts"].add(position.get("account"))
        if bucket.get("current_price") is None and position.get("current_price") is not None:
            bucket["current_price"] = position.get("current_price")
        if bucket.get("change_pct") is None and position.get("change_pct") is not None:
            bucket["change_pct"] = position.get("change_pct")
    out = []
    for bucket in grouped.values():
        bucket["accounts"] = sorted(a for a in bucket["accounts"] if a)
        out.append(bucket)
    return out


class IBKRTelegramService:
    """Service object used by Telegram bots or CLI wrappers."""

    def __init__(self, state_path: Path | str = DEFAULT_STATE_PATH):
        self.store = BotStateStore(state_path)

    def handle_prompt(self, prompt: str, chat_id: str = "default") -> str:
        parsed = parse_prompt(prompt)
        try:
            if parsed.intent == "help":
                return _HELP_TEXT
            if parsed.intent == "add_watchlist":
                return self._add_watchlist(parsed, chat_id)
            if parsed.intent == "remove_watchlist":
                return self._remove_watchlist(parsed, chat_id)
            if parsed.intent == "clear_watchlist":
                self.store.clear_watchlist(chat_id)
                return "Watchlist cleared."
            if parsed.intent == "watchlist_prices":
                return self._watchlist_prices(chat_id)
            if parsed.intent == "portfolio_value":
                return self._portfolio_value(parsed)
            if parsed.intent == "holdings_value":
                return self._holdings_value(parsed)
            if parsed.intent == "symbol_prices":
                return self._symbol_prices(parsed)
            if parsed.intent == "top_holdings":
                return self._top_holdings(parsed)
            if parsed.intent == "set_alert":
                return self._set_alert(parsed, chat_id)
            if parsed.intent == "check_alerts":
                return self._check_alerts(parsed, chat_id)
            return _HELP_TEXT
        except Exception as exc:
            return f"IBKR command failed: {exc}"

    def _add_watchlist(self, parsed: ParsedPrompt, chat_id: str) -> str:
        if not parsed.symbols:
            return "No tickers found. Example: /IBKR add AAPL,MSFT to my watchlist"
        watchlist = self.store.add_watchlist(chat_id, parsed.symbols)
        return "Watchlist saved: " + ", ".join(watchlist)

    def _remove_watchlist(self, parsed: ParsedPrompt, chat_id: str) -> str:
        if not parsed.symbols:
            return "No tickers found. Example: /IBKR remove AAPL from my watchlist"
        watchlist = self.store.remove_watchlist(chat_id, parsed.symbols)
        return "Watchlist now: " + (", ".join(watchlist) if watchlist else "(empty)")

    def _watchlist_prices(self, chat_id: str) -> str:
        watchlist = self.store.get_watchlist(chat_id)
        if not watchlist:
            return "Watchlist is empty. Example: /IBKR add AAPL,MSFT to my watchlist"

        snapshot = fetch_portfolio_snapshot()
        quotes = fetch_quotes(watchlist, snapshot["positions"])
        if not quotes:
            return "Watchlist is saved, but I could not fetch quotes right now."

        lines = ["Watchlist prices"]
        for quote in quotes:
            lines.append(
                f"{quote['symbol']}: {_money(quote.get('current_price'))} "
                f"({_pct(quote.get('change_pct'))})"
            )
        return "\n".join(lines)

    def _portfolio_value(self, parsed: ParsedPrompt) -> str:
        snapshot = fetch_portfolio_snapshot(account=parsed.account)
        if not snapshot["accounts"]:
            return "No portfolio positions or account summary data found."

        total_net_liq = sum(
            summary.get("net_liquidation") or 0.0 for summary in snapshot["summaries"].values()
        )
        total_market_value = sum(
            summary.get("total_market_value") or 0.0 for summary in snapshot["summaries"].values()
        )
        total_unrealized = sum(
            summary.get("total_unrealized_pnl") or 0.0 for summary in snapshot["summaries"].values()
        )

        lines = ["Portfolio value"]
        lines.append(f"Net liquidation: {_money(total_net_liq if total_net_liq else None)}")
        lines.append(f"Gross position value: {_money(total_market_value if total_market_value else None)}")
        lines.append(f"Unrealized P&L: {_money(total_unrealized if total_unrealized else None)}")

        if len(snapshot["accounts"]) > 1:
            lines.append("")
            lines.append("By account:")
            for acct_id in snapshot["accounts"]:
                summary = snapshot["summaries"][acct_id]
                lines.append(
                    f"{acct_id}: net liq {_money(summary.get('net_liquidation'))} | "
                    f"positions {summary.get('position_count', 0)}"
                )

        return "\n".join(lines)

    def _holdings_value(self, parsed: ParsedPrompt) -> str:
        if not parsed.symbols:
            return "No tickers found. Example: /IBKR value of AAPL and NVDA"

        snapshot = fetch_portfolio_snapshot(account=parsed.account)
        matched, missing = _match_positions(snapshot["positions"], parsed.symbols)
        if not matched:
            return "None of those tickers are in the current portfolio."

        aggregated = _aggregate_positions(matched)
        combined_value = sum(item.get("market_value", 0.0) or 0.0 for item in aggregated)
        lines = ["Selected holdings value"]
        for item in sorted(aggregated, key=lambda row: abs(row.get("market_value", 0.0)), reverse=True):
            lines.append(
                f"{item['symbol']}: {_money(item.get('market_value'))} | "
                f"price {_money(item.get('current_price'))} | "
                f"day {_pct(item.get('change_pct'))} | "
                f"uPnL {_money(item.get('unrealized_pnl'))}"
            )
        lines.append(f"Combined market value: {_money(combined_value)}")
        if missing:
            lines.append("Not currently held: " + ", ".join(missing))
        return "\n".join(lines)

    def _symbol_prices(self, parsed: ParsedPrompt) -> str:
        if not parsed.symbols:
            return "No tickers found. Example: /IBKR show prices for AAPL and TSLA"
        snapshot = fetch_portfolio_snapshot(account=parsed.account)
        quotes = fetch_quotes(parsed.symbols, snapshot["positions"])
        if not quotes:
            return "I could not fetch prices for those symbols right now."
        lines = ["Symbol prices"]
        for quote in quotes:
            lines.append(
                f"{quote['symbol']}: {_money(quote.get('current_price'))} "
                f"({_pct(quote.get('change_pct'))})"
            )
        return "\n".join(lines)

    def _top_holdings(self, parsed: ParsedPrompt) -> str:
        snapshot = fetch_portfolio_snapshot(account=parsed.account)
        aggregated = _aggregate_positions(snapshot["positions"])
        if not aggregated:
            return "No positions found."

        rows = sorted(aggregated, key=lambda row: abs(row.get("market_value", 0.0)), reverse=True)
        lines = [f"Top {min(parsed.top_n, len(rows))} holdings by market value"]
        for idx, item in enumerate(rows[: parsed.top_n], start=1):
            lines.append(
                f"{idx}. {item['symbol']} — {_money(item.get('market_value'))} "
                f"({_pct(item.get('change_pct'))})"
            )
        return "\n".join(lines)

    def _set_alert(self, parsed: ParsedPrompt, chat_id: str) -> str:
        threshold = parsed.threshold_pct or 3.0
        payload = self.store.set_alert(chat_id, threshold, parsed.scope)
        return (
            "Alert saved\n"
            f"Scope: {payload['scope']}\n"
            f"Threshold: {payload['threshold_pct']:.2f}%\n"
            "Use /IBKR check alerts to scan for breaches."
        )

    def _check_alerts(self, parsed: ParsedPrompt, chat_id: str) -> str:
        alert = self.store.get_alert(chat_id)
        threshold = parsed.threshold_pct or alert.get("threshold_pct") or 3.0
        if "watchlist" in parsed.raw_prompt.lower():
            scope = "watchlist"
        elif "portfolio" in parsed.raw_prompt.lower():
            scope = "portfolio"
        else:
            scope = alert.get("scope", parsed.scope)

        snapshot = fetch_portfolio_snapshot(account=parsed.account)
        candidates: list[dict] = []
        missing: list[str] = []

        if scope == "watchlist":
            watchlist = parsed.symbols or self.store.get_watchlist(chat_id)
            if not watchlist:
                return "Watchlist is empty. Add symbols first or say /IBKR alert me if my portfolio moves more than 3%"
            quotes = fetch_quotes(watchlist, snapshot["positions"])
            for quote in quotes:
                if quote.get("change_pct") is not None and abs(quote["change_pct"]) >= threshold:
                    matched_positions, _ = _match_positions(snapshot["positions"], [quote["symbol"]])
                    market_value = sum((p.get("market_value") or 0.0) for p in matched_positions) or None
                    candidates.append(
                        {
                            "symbol": quote["symbol"],
                            "current_price": quote.get("current_price"),
                            "change_pct": quote.get("change_pct"),
                            "market_value": market_value,
                        }
                    )
        else:
            rows = snapshot["positions"]
            if parsed.symbols:
                rows, missing = _match_positions(rows, parsed.symbols)
            for position in rows:
                change_pct = position.get("change_pct")
                if change_pct is not None and abs(change_pct) >= threshold:
                    candidates.append(
                        {
                            "symbol": _symbol_display(position).upper(),
                            "current_price": position.get("current_price"),
                            "change_pct": change_pct,
                            "market_value": position.get("market_value"),
                        }
                    )
            if parsed.symbols and missing:
                candidates.extend(
                    {
                        "symbol": symbol,
                        "current_price": None,
                        "change_pct": None,
                        "market_value": None,
                    }
                    for symbol in missing
                )

        triggered = [row for row in candidates if row.get("change_pct") is not None]
        if not triggered:
            return (
                "Alert check\n"
                f"Threshold: {threshold:.2f}% ({scope})\n"
                "No holdings are breaching that move threshold right now."
            )

        triggered.sort(key=lambda row: abs(row.get("change_pct", 0.0)), reverse=True)
        lines = ["Alert check", f"Threshold: {threshold:.2f}% ({scope})"]
        for row in triggered:
            extra = f" | value {_money(row.get('market_value'))}" if row.get("market_value") is not None else ""
            lines.append(
                f"{row['symbol']}: {_money(row.get('current_price'))} "
                f"({_pct(row.get('change_pct'))}){extra}"
            )
        if missing:
            lines.append("Not currently held: " + ", ".join(missing))
        return "\n".join(lines)
