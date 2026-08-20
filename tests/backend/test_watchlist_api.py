import pytest
from engine.utils.db import add_to_watchlist, get_watchlist, remove_from_watchlist, _ensure_investment_tables

def test_watchlist_crud():
    username = "test_user"
    symbol = "TEST.NS"
    _ensure_investment_tables()
    add_to_watchlist(username, symbol, "REIT", name="Test REIT")
    
    items = get_watchlist(username)
    assert any(i["symbol"] == symbol for i in items)
    
    res = remove_from_watchlist(username, symbol)
    assert res is True
    
    items2 = get_watchlist(username)
    assert not any(i["symbol"] == symbol for i in items2)
