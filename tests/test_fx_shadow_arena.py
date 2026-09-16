import json

import numpy as np
import pytest

from strategies.fx_shadow_arena import Candidate, run_arena, write_result


def panel():
    return {
        "features": np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32),
        "feature_names": np.array(["mom", "carry"]),
        "date": np.array([10, 11, 12]),
        "pair_idx": np.array([0, 0, 0]),
        "fwd1": np.array([0.02, -0.01, np.nan]),
    }


def buy(row):
    # The policy can see the causal feature values but not fwd1.
    assert "fwd1" not in row
    return {"action": "BUY", "conviction": row["features"]["mom"]}


def sell(row):
    return {"action": "SELL", "conviction": 1.0}


def test_same_panel_votes_and_next_period_outcomes_are_ranked():
    result = run_arena(panel(), [Candidate("buy", buy), Candidate("sell", sell)])
    assert result["paper_only"] is True
    assert result["n_rows"] == 3
    assert result["n_votes"] == 4  # NaN next-period label is excluded
    assert [x["candidate"] for x in result["ranking"]] == ["buy", "sell"]
    assert result["ranking"][0]["total_return"] == pytest.approx(0.01)
    assert all("next_return" in vote for vote in result["votes"])


def test_invalid_vote_and_live_destinations_are_rejected(tmp_path):
    def bad(_):
        return {"action": "BUY", "conviction": 2}

    with pytest.raises(ValueError, match="between 0 and 1"):
        run_arena(panel(), [Candidate("bad", bad)])
    with pytest.raises(ValueError, match="live output"):
        write_result({"paper_only": True}, tmp_path / "fx_ledger.jsonl")


def test_result_writer_is_paper_json_only(tmp_path):
    path = tmp_path / "arena-result.json"
    write_result({"paper_only": True, "ranking": []}, path)
    payload = json.loads(path.read_text())
    assert payload["paper_only"] is True
    assert not (tmp_path / "fx_ledger.jsonl").exists()
