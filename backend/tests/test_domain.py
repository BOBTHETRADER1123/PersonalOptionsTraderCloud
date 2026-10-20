from app.domain import leg_pnl, option_payoff, payoff_summary


def test_long_option_pnl():
    assert leg_pnl(1, 100, 125, 2, 50) == 2500


def test_short_option_pnl():
    assert leg_pnl(-1, 100, 75, 2, 50) == 2500


def test_bull_call_spread_payoff():
    legs = [
        {"side": "BUY", "option_type": "CE", "strike": 100, "entry_price": 20, "lots": 1, "lot_size": 10},
        {"side": "SELL", "option_type": "CE", "strike": 130, "entry_price": 5, "lots": 1, "lot_size": 10},
    ]
    assert option_payoff(legs, 100) == -150
    assert option_payoff(legs, 130) == 150
    assert option_payoff(legs, 160) == 150
    report = payoff_summary(legs)
    assert report["net_premium"] == -150
    assert report["max_profit"] == 150
    assert report["max_loss"] == -150
    assert report["breakevens"] == [115.0]


def test_naked_short_call_reports_unbounded_loss():
    report = payoff_summary([{"side": "SELL", "option_type": "CE", "strike": 100, "entry_price": 5, "lots": 1, "lot_size": 10}])
    assert report["max_loss"] is None
    assert report["max_profit"] == 50
