import json
from strategies.trader_agent.scorer import score_vote, summarize


def test_buy_positive_return_scores_positive():
    x = score_vote({'action':'BUY','conviction':0.8}, 1.0)
    assert x['correct'] is True and x['outcome'] == 0.8


def test_sell_positive_return_scores_negative():
    x = score_vote({'action':'SELL','conviction':0.8}, 1.0)
    assert x['correct'] is False and x['outcome'] == -0.8


def test_hold_small_move_is_correct():
    assert score_vote({'action':'HOLD','conviction':0.4}, 0.01)['correct'] is True


def test_summary_counts_actions():
    xs=[score_vote({'action':'BUY','conviction':1},1),
        score_vote({'action':'SELL','conviction':1},-1),
        score_vote({'action':'HOLD','conviction':1},0)]
    s=summarize(xs)
    assert s == {'n':3,'mean_outcome':1.0,'accuracy':1.0,'buy':1,'sell':1,'hold':1}
