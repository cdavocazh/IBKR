"""IBKR Connection Manager using ib_insync"""

import os
from contextlib import contextmanager
from typing import Optional

from dotenv import load_dotenv
from ib_insync import IB


class IBKRConnection:
    """Manages connection to IBKR TWS or IB Gateway."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: Optional[int] = None,
    ):
        load_dotenv()

        self.host = host or os.getenv("IBKR_HOST", "127.0.0.1")
        # IB Gateway: 4002 (paper), 4001 (live)
        # TWS: 7497 (paper), 7496 (live)
        self.port = port or int(os.getenv("IBKR_PORT", "4001"))
        self.client_id = client_id or int(os.getenv("IBKR_CLIENT_ID", "1"))
        self.ib = IB()

    def connect(self) -> IB:
        """Connect to IBKR TWS/Gateway."""
        if not self.ib.isConnected():
            self.ib.connect(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                readonly=True,
            )
            print(f"Connected to IBKR at {self.host}:{self.port}")
        return self.ib

    def disconnect(self) -> None:
        """Disconnect from IBKR."""
        if self.ib.isConnected():
            self.ib.disconnect()
            print("Disconnected from IBKR")

    def is_connected(self) -> bool:
        """Check if connected to IBKR."""
        return self.ib.isConnected()

    @contextmanager
    def session(self):
        """Context manager for IBKR connection session."""
        try:
            self.connect()
            yield self.ib
        finally:
            self.disconnect()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
