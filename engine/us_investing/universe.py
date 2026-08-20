"""
us_investing/universe.py
========================
Curated default universe of US stocks and ETFs.
"""

from typing import Any

US_ETF_UNIVERSE: dict[str, dict[str, Any]] = {
    "SPY":  {"name": "SPDR S&P 500 ETF Trust",        "sector": "Broad Market",   "type": "etf"},
    "QQQ":  {"name": "Invesco QQQ Trust (Nasdaq 100)", "sector": "Technology",     "type": "etf"},
    "VTI":  {"name": "Vanguard Total Stock Market ETF","sector": "Broad Market",   "type": "etf"},
    "IWM":  {"name": "iShares Russell 2000 ETF",       "sector": "Small Cap",      "type": "etf"},
    "GLD":  {"name": "SPDR Gold Shares",               "sector": "Commodities",    "type": "etf"},
    "TLT":  {"name": "iShares 20+ Year Treasury Bond", "sector": "Fixed Income",   "type": "etf"},
    "XLK":  {"name": "Technology Select Sector SPDR",  "sector": "Technology",     "type": "etf"},
    "XLF":  {"name": "Financial Select Sector SPDR",   "sector": "Financials",     "type": "etf"},
    "XLE":  {"name": "Energy Select Sector SPDR",      "sector": "Energy",         "type": "etf"},
    "ARKK": {"name": "ARK Innovation ETF",             "sector": "Innovation",     "type": "etf"},
    "VNQ":  {"name": "Vanguard Real Estate ETF",       "sector": "Real Estate",    "type": "etf"},
    "EEM":  {"name": "iShares MSCI Emerging Markets",  "sector": "Emerging Markets","type": "etf"},
}

US_STOCK_UNIVERSE: dict[str, dict[str, Any]] = {
    # Technology
    "AAPL":  {"name": "Apple Inc.",                    "sector": "Technology",     "type": "stock"},
    "MSFT":  {"name": "Microsoft Corporation",         "sector": "Technology",     "type": "stock"},
    "NVDA":  {"name": "NVIDIA Corporation",            "sector": "Technology",     "type": "stock"},
    "GOOGL": {"name": "Alphabet Inc. (Class A)",       "sector": "Technology",     "type": "stock"},
    "META":  {"name": "Meta Platforms Inc.",           "sector": "Technology",     "type": "stock"},
    "AMZN":  {"name": "Amazon.com Inc.",               "sector": "Consumer Disc.", "type": "stock"},
    "TSLA":  {"name": "Tesla Inc.",                    "sector": "Consumer Disc.", "type": "stock"},
    # Financials
    "JPM":   {"name": "JPMorgan Chase & Co.",          "sector": "Financials",     "type": "stock"},
    "BRK-B": {"name": "Berkshire Hathaway (B)",        "sector": "Financials",     "type": "stock"},
    "V":     {"name": "Visa Inc.",                     "sector": "Financials",     "type": "stock"},
    # Healthcare
    "JNJ":   {"name": "Johnson & Johnson",             "sector": "Healthcare",     "type": "stock"},
    "UNH":   {"name": "UnitedHealth Group",            "sector": "Healthcare",     "type": "stock"},
    # Consumer
    "PG":    {"name": "Procter & Gamble Co.",          "sector": "Consumer Staples","type": "stock"},
    "KO":    {"name": "The Coca-Cola Company",         "sector": "Consumer Staples","type": "stock"},
    # Energy
    "XOM":   {"name": "Exxon Mobil Corporation",       "sector": "Energy",         "type": "stock"},
    "CVX":   {"name": "Chevron Corporation",           "sector": "Energy",         "type": "stock"},
    # India-relevant US listings
    "INFY":  {"name": "Infosys Ltd. ADR",              "sector": "Technology",     "type": "stock"},
    "WIT":   {"name": "Wipro Ltd. ADR",                "sector": "Technology",     "type": "stock"},
    "HDB":   {"name": "HDFC Bank Ltd. ADR",            "sector": "Financials",     "type": "stock"},
}

FULL_UNIVERSE = {**US_ETF_UNIVERSE, **US_STOCK_UNIVERSE}

BENCHMARK_TICKER = "SPY"   # S&P 500 ETF as benchmark
USD_INR_TICKER = "USDINR=X"
