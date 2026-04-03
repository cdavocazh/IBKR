"""GICS sector/industry classification for S&P 500 tickers.

Provides a mapping of ~504 S&P 500 constituent tickers to their
Global Industry Classification Standard (GICS) sector and industry group.

11 GICS Sectors:
    Information Technology, Health Care, Financials, Consumer Discretionary,
    Communication Services, Industrials, Consumer Staples, Energy, Utilities,
    Real Estate, Materials

~25 GICS Industry Groups:
    Software & Services, Technology Hardware & Equipment,
    Semiconductors & Semiconductor Equipment,
    Pharmaceuticals Biotechnology & Life Sciences,
    Health Care Equipment & Services,
    Banks, Financial Services, Insurance, Capital Markets,
    Consumer Discretionary Distribution & Retail,
    Automobiles & Components, Consumer Durables & Apparel, Consumer Services,
    Media & Entertainment, Telecommunication Services,
    Capital Goods, Commercial & Professional Services, Transportation,
    Food Staples Retailing, Food Beverage & Tobacco,
    Household & Personal Products,
    Energy,
    Utilities,
    Equity Real Estate Investment Trusts,
    Real Estate Management & Development,
    Materials

Usage:
    from tools.sector_mapping import get_sector, get_sector_peers

    sector = get_sector("AAPL")          # "Information Technology"
    peers  = get_sector_peers("AAPL")    # tickers in same industry group
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Canonical GICS sector list
# ---------------------------------------------------------------------------
GICS_SECTORS: list[str] = [
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Financials",
    "Health Care",
    "Industrials",
    "Information Technology",
    "Materials",
    "Real Estate",
    "Utilities",
]

# ---------------------------------------------------------------------------
# Canonical GICS industry group list
# ---------------------------------------------------------------------------
GICS_INDUSTRY_GROUPS: list[str] = [
    # Information Technology
    "Software & Services",
    "Technology Hardware & Equipment",
    "Semiconductors & Semiconductor Equipment",
    # Health Care
    "Pharmaceuticals Biotechnology & Life Sciences",
    "Health Care Equipment & Services",
    # Financials
    "Banks",
    "Financial Services",
    "Insurance",
    "Capital Markets",
    # Consumer Discretionary
    "Consumer Discretionary Distribution & Retail",
    "Automobiles & Components",
    "Consumer Durables & Apparel",
    "Consumer Services",
    # Communication Services
    "Media & Entertainment",
    "Telecommunication Services",
    # Industrials
    "Capital Goods",
    "Commercial & Professional Services",
    "Transportation",
    # Consumer Staples
    "Food Staples Retailing",
    "Food Beverage & Tobacco",
    "Household & Personal Products",
    # Energy
    "Energy",
    # Utilities
    "Utilities",
    # Real Estate
    "Equity Real Estate Investment Trusts",
    "Real Estate Management & Development",
    # Materials
    "Materials",
]


# ---------------------------------------------------------------------------
# GICS_SECTOR_MAP — ticker -> {sector, industry_group}
# Organised by sector with comment headers for readability.
# ---------------------------------------------------------------------------
GICS_SECTOR_MAP: dict[str, dict[str, str]] = {

    # ── Information Technology ─────────────────────────────────

    # Software & Services
    "AAPL":  {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "ACN":   {"sector": "Information Technology", "industry_group": "Software & Services"},
    "ADBE":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "ADSK":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "AKAM":  {"sector": "Information Technology", "industry_group": "Software & Services"},

    "APP":   {"sector": "Information Technology", "industry_group": "Software & Services"},
    "BR":    {"sector": "Information Technology", "industry_group": "Software & Services"},
    "CDNS":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "CRM":   {"sector": "Information Technology", "industry_group": "Software & Services"},
    "CRWD":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "CSGP":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "CTSH":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "DDOG":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "EPAM":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "FDS":   {"sector": "Information Technology", "industry_group": "Software & Services"},
    "FICO":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "FIS":   {"sector": "Information Technology", "industry_group": "Software & Services"},
    "FISV":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "FTNT":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "GDDY":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "GEN":   {"sector": "Information Technology", "industry_group": "Software & Services"},
    "GPN":   {"sector": "Information Technology", "industry_group": "Software & Services"},
    "INTU":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "IT":    {"sector": "Information Technology", "industry_group": "Software & Services"},
    "JKHY":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "MSFT":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "NOW":   {"sector": "Information Technology", "industry_group": "Software & Services"},
    "ORCL":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "PANW":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "PAYC":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "PAYX":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "PLTR":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "PTC":   {"sector": "Information Technology", "industry_group": "Software & Services"},
    "SNPS":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "TYL":   {"sector": "Information Technology", "industry_group": "Software & Services"},
    "VRSN":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "WDAY":  {"sector": "Information Technology", "industry_group": "Software & Services"},

    # Technology Hardware & Equipment
    "APH":   {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "CDW":   {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "CSCO":  {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "DELL":  {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "FFIV":  {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "GLW":   {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "GRMN":  {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "HPE":   {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "HPQ":   {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "IBM":   {"sector": "Information Technology", "industry_group": "Software & Services"},
    "KEYS":  {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "MSI":   {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "NTAP":  {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "STX":   {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "SMCI":  {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "SNDK":  {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "TEL":   {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "TRMB":  {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "WDC":   {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
    "ZBRA":  {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},

    # Semiconductors & Semiconductor Equipment
    "ADI":   {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "AMAT":  {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "AMD":   {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "AVGO":  {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "FSLR":  {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "INTC":  {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "KLAC":  {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "LRCX":  {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "MCHP":  {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "MPWR":  {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "MU":    {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "NVDA":  {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "NXPI":  {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "ON":    {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "QCOM":  {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "SWKS":  {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "TER":   {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "TXN":   {"sector": "Information Technology", "industry_group": "Semiconductors & Semiconductor Equipment"},
    "ANET":  {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},

    # IT — Financial Technology (classified IT per GICS)
    "CPAY":  {"sector": "Information Technology", "industry_group": "Software & Services"},
    "PYPL":  {"sector": "Financial Services", "industry_group": "Financial Services"},  # will fix below

    # ── Health Care ────────────────────────────────────────────

    # Pharmaceuticals, Biotechnology & Life Sciences
    "ABBV":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "AMGN":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "BIIB":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "BMY":   {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "CRL":   {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "CTVA":  {"sector": "Materials", "industry_group": "Materials"},  # Corteva is Materials
    "GILD":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "IDXX":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "INCY":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "IQV":   {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "JNJ":   {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "LLY":   {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "MRK":   {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "MRNA":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "PFE":   {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "REGN":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "RVTY":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "TECH":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "VRTX":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "VTRS":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "WAT":   {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "ZTS":   {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "KVUE":  {"sector": "Consumer Staples", "industry_group": "Household & Personal Products"},  # Kenvue is Consumer Staples
    "SOLV":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "A":     {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},

    # Health Care Equipment & Services
    "ABT":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "ALGN":  {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "BAX":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "BDX":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "BSX":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "CAH":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "CI":    {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "CNC":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "COO":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "COR":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "CVS":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "DGX":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "DHR":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "DVA":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "DXCM":  {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "ELV":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "EW":    {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "GEHC":  {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "HCA":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "HOLX":  {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "HSIC":  {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "HUM":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "ISRG":  {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "LH":    {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "MCK":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "MDT":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "MOH":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "MTD":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "PODD":  {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "RMD":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "STE":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "SYK":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "TMO":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "UHS":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "UNH":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "VLTO":  {"sector": "Health Care", "industry_group": "Pharmaceuticals Biotechnology & Life Sciences"},
    "WST":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},
    "ZBH":   {"sector": "Health Care", "industry_group": "Health Care Equipment & Services"},

    # ── Financials ─────────────────────────────────────────────

    # Banks
    "BAC":   {"sector": "Financials", "industry_group": "Banks"},
    "C":     {"sector": "Financials", "industry_group": "Banks"},
    "CFG":   {"sector": "Financials", "industry_group": "Banks"},
    "FITB":  {"sector": "Financials", "industry_group": "Banks"},
    "HBAN":  {"sector": "Financials", "industry_group": "Banks"},
    "JPM":   {"sector": "Financials", "industry_group": "Banks"},
    "KEY":   {"sector": "Financials", "industry_group": "Banks"},
    "MTB":   {"sector": "Financials", "industry_group": "Banks"},
    "PNC":   {"sector": "Financials", "industry_group": "Banks"},
    "RF":    {"sector": "Financials", "industry_group": "Banks"},
    "TFC":   {"sector": "Financials", "industry_group": "Banks"},
    "USB":   {"sector": "Financials", "industry_group": "Banks"},
    "WFC":   {"sector": "Financials", "industry_group": "Banks"},

    # Financial Services (incl. payment processors)
    "AXP":   {"sector": "Financials", "industry_group": "Financial Services"},
    "BRK-B": {"sector": "Financials", "industry_group": "Financial Services"},
    "COF":   {"sector": "Financials", "industry_group": "Financial Services"},
    "COIN":  {"sector": "Financials", "industry_group": "Financial Services"},

    "MA":    {"sector": "Financials", "industry_group": "Financial Services"},
    "PYPL":  {"sector": "Financials", "industry_group": "Financial Services"},
    "SYF":   {"sector": "Financials", "industry_group": "Financial Services"},
    "V":     {"sector": "Financials", "industry_group": "Financial Services"},

    # Insurance
    "ACGL":  {"sector": "Financials", "industry_group": "Insurance"},
    "AFL":   {"sector": "Financials", "industry_group": "Insurance"},
    "AIG":   {"sector": "Financials", "industry_group": "Insurance"},
    "AIZ":   {"sector": "Financials", "industry_group": "Insurance"},
    "AJG":   {"sector": "Financials", "industry_group": "Insurance"},
    "ALL":   {"sector": "Financials", "industry_group": "Insurance"},
    "AON":   {"sector": "Financials", "industry_group": "Insurance"},
    "BRO":   {"sector": "Financials", "industry_group": "Insurance"},
    "CB":    {"sector": "Financials", "industry_group": "Insurance"},
    "CINF":  {"sector": "Financials", "industry_group": "Insurance"},
    "ERIE":  {"sector": "Financials", "industry_group": "Insurance"},
    "GL":    {"sector": "Financials", "industry_group": "Insurance"},
    "HIG":   {"sector": "Financials", "industry_group": "Insurance"},
    "L":     {"sector": "Financials", "industry_group": "Insurance"},
    "MET":   {"sector": "Financials", "industry_group": "Insurance"},
    "MMM":   {"sector": "Industrials", "industry_group": "Capital Goods"},  # 3M is Industrials
    "PFG":   {"sector": "Financials", "industry_group": "Insurance"},
    "PGR":   {"sector": "Financials", "industry_group": "Insurance"},
    "PRU":   {"sector": "Financials", "industry_group": "Insurance"},
    "TRV":   {"sector": "Financials", "industry_group": "Insurance"},
    "WRB":   {"sector": "Financials", "industry_group": "Insurance"},
    "WTW":   {"sector": "Financials", "industry_group": "Insurance"},
    "MRSH":  {"sector": "Financials", "industry_group": "Insurance"},

    # Capital Markets
    "AMP":   {"sector": "Financials", "industry_group": "Capital Markets"},
    "APO":   {"sector": "Financials", "industry_group": "Capital Markets"},
    "ARES":  {"sector": "Financials", "industry_group": "Capital Markets"},
    "BEN":   {"sector": "Financials", "industry_group": "Capital Markets"},
    "BK":    {"sector": "Financials", "industry_group": "Capital Markets"},
    "BLK":   {"sector": "Financials", "industry_group": "Capital Markets"},
    "BX":    {"sector": "Financials", "industry_group": "Capital Markets"},
    "CBOE":  {"sector": "Financials", "industry_group": "Capital Markets"},
    "CME":   {"sector": "Financials", "industry_group": "Capital Markets"},
    "EG":    {"sector": "Financials", "industry_group": "Capital Markets"},
    "GS":    {"sector": "Financials", "industry_group": "Capital Markets"},
    "HOOD":  {"sector": "Financials", "industry_group": "Capital Markets"},
    "IBKR":  {"sector": "Financials", "industry_group": "Capital Markets"},
    "ICE":   {"sector": "Financials", "industry_group": "Capital Markets"},
    "IVZ":   {"sector": "Financials", "industry_group": "Capital Markets"},
    "KKR":   {"sector": "Financials", "industry_group": "Capital Markets"},
    "MCO":   {"sector": "Financials", "industry_group": "Capital Markets"},
    "MS":    {"sector": "Financials", "industry_group": "Capital Markets"},
    "MSCI":  {"sector": "Financials", "industry_group": "Capital Markets"},
    "NDAQ":  {"sector": "Financials", "industry_group": "Capital Markets"},
    "NTRS":  {"sector": "Financials", "industry_group": "Capital Markets"},
    "RJF":   {"sector": "Financials", "industry_group": "Capital Markets"},
    "SCHW":  {"sector": "Financials", "industry_group": "Capital Markets"},
    "SPGI":  {"sector": "Financials", "industry_group": "Capital Markets"},
    "STT":   {"sector": "Financials", "industry_group": "Capital Markets"},
    "TROW":  {"sector": "Financials", "industry_group": "Capital Markets"},
    "VRSK":  {"sector": "Financials", "industry_group": "Capital Markets"},

    # ── Consumer Discretionary ─────────────────────────────────

    # Consumer Discretionary Distribution & Retail
    "AMZN":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "AZO":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "BBY":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "BKNG":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "CPRT":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},  # Copart — specialty retail
    "CVNA":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "DG":    {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "DLTR":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "EBAY":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "EXPE":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "GPC":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "HD":    {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},

    "LOW":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "ORLY":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "POOL":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "ROST":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "TGT":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "TJX":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "TSCO":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "ULTA":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},
    "WSM":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Discretionary Distribution & Retail"},

    # Automobiles & Components
    "APTV":  {"sector": "Consumer Discretionary", "industry_group": "Automobiles & Components"},
    "F":     {"sector": "Consumer Discretionary", "industry_group": "Automobiles & Components"},
    "GM":    {"sector": "Consumer Discretionary", "industry_group": "Automobiles & Components"},
    "TSLA":  {"sector": "Consumer Discretionary", "industry_group": "Automobiles & Components"},

    # Consumer Durables & Apparel
    "HAS":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Durables & Apparel"},
    "LEN":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Durables & Apparel"},
    "LULU":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Durables & Apparel"},
    "NKE":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Durables & Apparel"},
    "NVR":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Durables & Apparel"},
    "DHI":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Durables & Apparel"},
    "PHM":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Durables & Apparel"},
    "RL":    {"sector": "Consumer Discretionary", "industry_group": "Consumer Durables & Apparel"},
    "TPR":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Durables & Apparel"},
    "DECK":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Durables & Apparel"},
    "BLDR":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Durables & Apparel"},

    # Consumer Services
    "ABNB":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "CCL":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "CMG":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "DAL":   {"sector": "Industrials", "industry_group": "Transportation"},  # Airlines are Industrials
    "DPZ":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "DRI":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "HLT":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "LVS":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "LYV":   {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "MAR":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "MCD":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "MGM":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "NCLH":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "RCL":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "SBUX":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "WYNN":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "YUM":   {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},
    "DASH":  {"sector": "Consumer Discretionary", "industry_group": "Consumer Services"},

    # ── Communication Services ─────────────────────────────────

    # Media & Entertainment
    "CHTR":  {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "CMCSA": {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "DIS":   {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "EA":    {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "FOX":   {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "FOXA":  {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "GOOG":  {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "GOOGL": {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "META":  {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "MTCH":  {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "NFLX":  {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "NWS":   {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "NWSA":  {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "OMC":   {"sector": "Communication Services", "industry_group": "Media & Entertainment"},

    "TTD":   {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "TTWO":  {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "WBD":   {"sector": "Communication Services", "industry_group": "Media & Entertainment"},
    "TKO":   {"sector": "Communication Services", "industry_group": "Media & Entertainment"},

    # Telecommunication Services
    "T":     {"sector": "Communication Services", "industry_group": "Telecommunication Services"},
    "TMUS":  {"sector": "Communication Services", "industry_group": "Telecommunication Services"},
    "VZ":    {"sector": "Communication Services", "industry_group": "Telecommunication Services"},

    # ── Industrials ────────────────────────────────────────────

    # Capital Goods
    "AOS":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "AXON":  {"sector": "Industrials", "industry_group": "Capital Goods"},
    "BA":    {"sector": "Industrials", "industry_group": "Capital Goods"},
    "CARR":  {"sector": "Industrials", "industry_group": "Capital Goods"},
    "CAT":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "CMI":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "DE":    {"sector": "Industrials", "industry_group": "Capital Goods"},
    "DOV":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "EMR":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "ETN":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "FAST":  {"sector": "Industrials", "industry_group": "Capital Goods"},
    "FTV":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "GD":    {"sector": "Industrials", "industry_group": "Capital Goods"},
    "GE":    {"sector": "Industrials", "industry_group": "Capital Goods"},
    "GEV":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "GNRC":  {"sector": "Industrials", "industry_group": "Capital Goods"},
    "GWW":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "HII":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "HON":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "HUBB":  {"sector": "Industrials", "industry_group": "Capital Goods"},
    "HWM":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "IEX":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "IR":    {"sector": "Industrials", "industry_group": "Capital Goods"},
    "ITW":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "JCI":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "LHX":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "LII":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "LMT":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "MAS":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "NDSN":  {"sector": "Industrials", "industry_group": "Capital Goods"},
    "NOC":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "OTIS":  {"sector": "Industrials", "industry_group": "Capital Goods"},
    "PCAR":  {"sector": "Industrials", "industry_group": "Capital Goods"},
    "PH":    {"sector": "Industrials", "industry_group": "Capital Goods"},
    "PNR":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "PWR":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "ROK":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "ROP":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "RTX":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "SNA":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "SWK":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "TDG":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "TDY":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "TT":    {"sector": "Industrials", "industry_group": "Capital Goods"},
    "TXT":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "WAB":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "XYL":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "AME":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "ALLE":  {"sector": "Industrials", "industry_group": "Capital Goods"},
    "EME":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "FIX":   {"sector": "Industrials", "industry_group": "Capital Goods"},
    "SW":    {"sector": "Industrials", "industry_group": "Capital Goods"},

    # Commercial & Professional Services
    "ADP":   {"sector": "Industrials", "industry_group": "Commercial & Professional Services"},

    "CIEN":  {"sector": "Communication Services", "industry_group": "Telecommunication Services"},  # Ciena is networking
    "CTAS":  {"sector": "Industrials", "industry_group": "Commercial & Professional Services"},
    "EFX":   {"sector": "Industrials", "industry_group": "Commercial & Professional Services"},
    "GPN":   {"sector": "Industrials", "industry_group": "Commercial & Professional Services"},  # already in IT; will be overridden
    "J":     {"sector": "Industrials", "industry_group": "Commercial & Professional Services"},
    "LDOS":  {"sector": "Industrials", "industry_group": "Commercial & Professional Services"},
    "ROL":   {"sector": "Industrials", "industry_group": "Commercial & Professional Services"},
    "RSG":   {"sector": "Industrials", "industry_group": "Commercial & Professional Services"},
    "VRSK":  {"sector": "Industrials", "industry_group": "Commercial & Professional Services"},  # already in Financials
    "WM":    {"sector": "Industrials", "industry_group": "Commercial & Professional Services"},

    # Transportation
    "CHRW":  {"sector": "Industrials", "industry_group": "Transportation"},
    "CSX":   {"sector": "Industrials", "industry_group": "Transportation"},
    "EXPD":  {"sector": "Industrials", "industry_group": "Transportation"},
    "FDX":   {"sector": "Industrials", "industry_group": "Transportation"},
    "JBHT":  {"sector": "Industrials", "industry_group": "Transportation"},
    "LUV":   {"sector": "Industrials", "industry_group": "Transportation"},
    "NSC":   {"sector": "Industrials", "industry_group": "Transportation"},
    "ODFL":  {"sector": "Industrials", "industry_group": "Transportation"},
    "UAL":   {"sector": "Industrials", "industry_group": "Transportation"},
    "UNP":   {"sector": "Industrials", "industry_group": "Transportation"},
    "UPS":   {"sector": "Industrials", "industry_group": "Transportation"},
    "URI":   {"sector": "Industrials", "industry_group": "Transportation"},
    "UBER":  {"sector": "Industrials", "industry_group": "Transportation"},

    # ── Consumer Staples ───────────────────────────────────────

    # Food Staples Retailing
    "COST":  {"sector": "Consumer Staples", "industry_group": "Food Staples Retailing"},
    "KR":    {"sector": "Consumer Staples", "industry_group": "Food Staples Retailing"},
    "SYY":   {"sector": "Consumer Staples", "industry_group": "Food Staples Retailing"},
    "WMT":   {"sector": "Consumer Staples", "industry_group": "Food Staples Retailing"},

    # Food, Beverage & Tobacco
    "ADM":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "BF-B":  {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "BG":    {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "CAG":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "CPB":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "GIS":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "HRL":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "HSY":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},

    "KDP":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "KHC":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "KO":    {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "LW":    {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "MDLZ":  {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "MKC":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "MNST":  {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "MO":    {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "PEP":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "PM":    {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "SJM":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "STZ":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "TAP":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},
    "TSN":   {"sector": "Consumer Staples", "industry_group": "Food Beverage & Tobacco"},

    # Household & Personal Products
    "CHD":   {"sector": "Consumer Staples", "industry_group": "Household & Personal Products"},
    "CL":    {"sector": "Consumer Staples", "industry_group": "Household & Personal Products"},
    "CLX":   {"sector": "Consumer Staples", "industry_group": "Household & Personal Products"},
    "EL":    {"sector": "Consumer Staples", "industry_group": "Household & Personal Products"},
    "KMB":   {"sector": "Consumer Staples", "industry_group": "Household & Personal Products"},
    "PG":    {"sector": "Consumer Staples", "industry_group": "Household & Personal Products"},

    # ── Energy ─────────────────────────────────────────────────

    "APA":   {"sector": "Energy", "industry_group": "Energy"},
    "BKR":   {"sector": "Energy", "industry_group": "Energy"},
    "COP":   {"sector": "Energy", "industry_group": "Energy"},
    "CTRA":  {"sector": "Energy", "industry_group": "Energy"},
    "CVX":   {"sector": "Energy", "industry_group": "Energy"},
    "DVN":   {"sector": "Energy", "industry_group": "Energy"},
    "EOG":   {"sector": "Energy", "industry_group": "Energy"},
    "EQT":   {"sector": "Energy", "industry_group": "Energy"},
    "FANG":  {"sector": "Energy", "industry_group": "Energy"},
    "HAL":   {"sector": "Energy", "industry_group": "Energy"},
    "KMI":   {"sector": "Energy", "industry_group": "Energy"},
    "MPC":   {"sector": "Energy", "industry_group": "Energy"},
    "OKE":   {"sector": "Energy", "industry_group": "Energy"},
    "OXY":   {"sector": "Energy", "industry_group": "Energy"},
    "PSX":   {"sector": "Energy", "industry_group": "Energy"},
    "SLB":   {"sector": "Energy", "industry_group": "Energy"},
    "TPL":   {"sector": "Energy", "industry_group": "Energy"},
    "TRGP":  {"sector": "Energy", "industry_group": "Energy"},
    "VLO":   {"sector": "Energy", "industry_group": "Energy"},
    "WMB":   {"sector": "Energy", "industry_group": "Energy"},
    "XOM":   {"sector": "Energy", "industry_group": "Energy"},

    # ── Utilities ──────────────────────────────────────────────

    "AEE":   {"sector": "Utilities", "industry_group": "Utilities"},
    "AEP":   {"sector": "Utilities", "industry_group": "Utilities"},
    "AES":   {"sector": "Utilities", "industry_group": "Utilities"},
    "ATO":   {"sector": "Utilities", "industry_group": "Utilities"},
    "AWK":   {"sector": "Utilities", "industry_group": "Utilities"},
    "CEG":   {"sector": "Utilities", "industry_group": "Utilities"},
    "CMS":   {"sector": "Utilities", "industry_group": "Utilities"},
    "CNP":   {"sector": "Utilities", "industry_group": "Utilities"},
    "D":     {"sector": "Utilities", "industry_group": "Utilities"},
    "DTE":   {"sector": "Utilities", "industry_group": "Utilities"},
    "DUK":   {"sector": "Utilities", "industry_group": "Utilities"},
    "ED":    {"sector": "Utilities", "industry_group": "Utilities"},
    "EIX":   {"sector": "Utilities", "industry_group": "Utilities"},
    "ES":    {"sector": "Utilities", "industry_group": "Utilities"},
    "ETR":   {"sector": "Utilities", "industry_group": "Utilities"},
    "EVRG":  {"sector": "Utilities", "industry_group": "Utilities"},
    "EXC":   {"sector": "Utilities", "industry_group": "Utilities"},
    "FE":    {"sector": "Utilities", "industry_group": "Utilities"},
    "LNT":   {"sector": "Utilities", "industry_group": "Utilities"},
    "NEE":   {"sector": "Utilities", "industry_group": "Utilities"},
    "NI":    {"sector": "Utilities", "industry_group": "Utilities"},
    "NRG":   {"sector": "Utilities", "industry_group": "Utilities"},
    "PCG":   {"sector": "Utilities", "industry_group": "Utilities"},
    "PEG":   {"sector": "Utilities", "industry_group": "Utilities"},
    "PNW":   {"sector": "Utilities", "industry_group": "Utilities"},
    "PPL":   {"sector": "Utilities", "industry_group": "Utilities"},
    "SO":    {"sector": "Utilities", "industry_group": "Utilities"},
    "SRE":   {"sector": "Utilities", "industry_group": "Utilities"},
    "VST":   {"sector": "Utilities", "industry_group": "Utilities"},
    "WEC":   {"sector": "Utilities", "industry_group": "Utilities"},
    "XEL":   {"sector": "Utilities", "industry_group": "Utilities"},

    # ── Real Estate ────────────────────────────────────────────

    # Equity Real Estate Investment Trusts (REITs)
    "AMT":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "ARE":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "AVB":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "BXP":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "CCI":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "CPT":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "DLR":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "DOC":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "EQIX":  {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "EQR":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "ESS":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "EXR":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "FRT":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "HST":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "INVH":  {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "IRM":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "KIM":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "MAA":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "O":     {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "PLD":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "PSA":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "REG":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "SBAC":  {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "SPG":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "UDR":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "VICI":  {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "VTR":   {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},
    "WELL":  {"sector": "Real Estate", "industry_group": "Equity Real Estate Investment Trusts"},

    # Real Estate Management & Development
    "CBRE":  {"sector": "Real Estate", "industry_group": "Real Estate Management & Development"},

    # ── Materials ──────────────────────────────────────────────

    "ALB":   {"sector": "Materials", "industry_group": "Materials"},
    "AMCR":  {"sector": "Materials", "industry_group": "Materials"},
    "APD":   {"sector": "Materials", "industry_group": "Materials"},
    "AVY":   {"sector": "Materials", "industry_group": "Materials"},
    "BALL":  {"sector": "Materials", "industry_group": "Materials"},
    "CF":    {"sector": "Materials", "industry_group": "Materials"},
    "CRH":   {"sector": "Materials", "industry_group": "Materials"},
    "DD":    {"sector": "Materials", "industry_group": "Materials"},
    "DOW":   {"sector": "Materials", "industry_group": "Materials"},
    "ECL":   {"sector": "Materials", "industry_group": "Materials"},
    "FCX":   {"sector": "Materials", "industry_group": "Materials"},
    "IFF":   {"sector": "Materials", "industry_group": "Materials"},
    "IP":    {"sector": "Materials", "industry_group": "Materials"},
    "LIN":   {"sector": "Materials", "industry_group": "Materials"},
    "LYB":   {"sector": "Materials", "industry_group": "Materials"},
    "MLM":   {"sector": "Materials", "industry_group": "Materials"},
    "MOS":   {"sector": "Materials", "industry_group": "Materials"},
    "NEM":   {"sector": "Materials", "industry_group": "Materials"},
    "NUE":   {"sector": "Materials", "industry_group": "Materials"},
    "PKG":   {"sector": "Materials", "industry_group": "Materials"},
    "PPG":   {"sector": "Materials", "industry_group": "Materials"},
    "SHW":   {"sector": "Materials", "industry_group": "Materials"},
    "STLD":  {"sector": "Materials", "industry_group": "Materials"},
    "VMC":   {"sector": "Materials", "industry_group": "Materials"},
    "WY":    {"sector": "Materials", "industry_group": "Materials"},

    # ── Additional / corrections for specific tickers ──────────

    # Tickers that might have been in an earlier section with wrong
    # classification are corrected here (last-write wins in the dict).

    # CTVA — Corteva Agriscience is Materials (specialty chemicals)
    "CTVA":  {"sector": "Materials", "industry_group": "Materials"},

    # KVUE — Kenvue is Consumer Staples
    "KVUE":  {"sector": "Consumer Staples", "industry_group": "Household & Personal Products"},

    # MMM — 3M is Industrials / Capital Goods
    "MMM":   {"sector": "Industrials", "industry_group": "Capital Goods"},

    # LYV — Live Nation is Communication Services
    "LYV":   {"sector": "Communication Services", "industry_group": "Media & Entertainment"},

    # DAL — Delta Air Lines is Industrials / Transportation
    "DAL":   {"sector": "Industrials", "industry_group": "Transportation"},

    # PYPL — PayPal is Financials / Financial Services
    "PYPL":  {"sector": "Financials", "industry_group": "Financial Services"},

    # VRSK — Verisk is Financials / Capital Markets (data analytics for insurance)
    "VRSK":  {"sector": "Financials", "industry_group": "Capital Markets"},

    # GPN — Global Payments is Financials / Financial Services
    "GPN":   {"sector": "Financials", "industry_group": "Financial Services"},

    # CIEN — Ciena is Information Technology / Technology Hardware & Equipment
    "CIEN":  {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},

    # IBM — IT Services / Software & Services
    "IBM":   {"sector": "Information Technology", "industry_group": "Software & Services"},

    # UBER — Industrials / Transportation
    "UBER":  {"sector": "Industrials", "industry_group": "Transportation"},

    # EXE — Expand Energy is Energy
    "EXE":   {"sector": "Energy", "industry_group": "Energy"},

    # PSKY — not a standard S&P 500 ticker, classify as Industrials placeholder
    "PSKY":  {"sector": "Industrials", "industry_group": "Capital Goods"},

    # Q — Quintessential (placeholder ticker)
    "Q":     {"sector": "Information Technology", "industry_group": "Software & Services"},

    # XYZ — placeholder ticker
    "XYZ":   {"sector": "Information Technology", "industry_group": "Software & Services"},

    # JBL — Jabil is Information Technology / Technology Hardware
    "JBL":   {"sector": "Information Technology", "industry_group": "Technology Hardware & Equipment"},
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_sector(ticker: str) -> str | None:
    """Return the GICS sector for *ticker*, or ``None`` if not found."""
    entry = GICS_SECTOR_MAP.get(ticker.upper())
    return entry["sector"] if entry else None


def get_industry_group(ticker: str) -> str | None:
    """Return the GICS industry group for *ticker*, or ``None`` if not found."""
    entry = GICS_SECTOR_MAP.get(ticker.upper())
    return entry["industry_group"] if entry else None


def get_sector_peers(
    ticker: str,
    same_industry_group: bool = True,
) -> list[str]:
    """Return a sorted list of tickers in the same sector (or industry group).

    Parameters
    ----------
    ticker:
        The reference ticker (case-insensitive).
    same_industry_group:
        If ``True`` (default), return only tickers in the **same industry
        group**.  If ``False``, return all tickers in the same **sector**.

    Returns
    -------
    list[str]
        Sorted peer tickers, **excluding** the input ticker itself.
        Returns an empty list if the ticker is not found.
    """
    entry = GICS_SECTOR_MAP.get(ticker.upper())
    if entry is None:
        return []

    key = "industry_group" if same_industry_group else "sector"
    target_value = entry[key]

    return sorted(
        t
        for t, info in GICS_SECTOR_MAP.items()
        if info[key] == target_value and t != ticker.upper()
    )


def get_tickers_by_sector(sector: str) -> list[str]:
    """Return a sorted list of all tickers belonging to *sector*.

    The match is case-insensitive.

    Parameters
    ----------
    sector:
        One of the 11 GICS sector names (e.g. ``"Information Technology"``).

    Returns
    -------
    list[str]
        Sorted tickers, or an empty list if no tickers match.
    """
    sector_lower = sector.lower()
    return sorted(
        t
        for t, info in GICS_SECTOR_MAP.items()
        if info["sector"].lower() == sector_lower
    )


def get_tickers_by_industry_group(industry_group: str) -> list[str]:
    """Return a sorted list of all tickers belonging to *industry_group*.

    The match is case-insensitive.

    Parameters
    ----------
    industry_group:
        One of the ~25 GICS industry group names
        (e.g. ``"Software & Services"``).

    Returns
    -------
    list[str]
        Sorted tickers, or an empty list if no tickers match.
    """
    ig_lower = industry_group.lower()
    return sorted(
        t
        for t, info in GICS_SECTOR_MAP.items()
        if info["industry_group"].lower() == ig_lower
    )


def get_all_sectors() -> list[str]:
    """Return the canonical list of 11 GICS sectors."""
    return list(GICS_SECTORS)


def get_sector_summary() -> dict[str, int]:
    """Return a dict mapping each sector to its ticker count."""
    counts: dict[str, int] = {}
    for info in GICS_SECTOR_MAP.values():
        s = info["sector"]
        counts[s] = counts.get(s, 0) + 1
    return dict(sorted(counts.items()))
