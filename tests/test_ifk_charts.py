import pandas as pd

import ifk_charts

CURVE = pd.DataFrame({"return_period": [10.0, 100.0], "intensity": [0.5, 1.2]})


def _mark(series):
    return ifk_charts._curve_line(CURVE, "depth", series).to_dict()["mark"]


def test_only_the_original_curve_is_dashed():
    assert _mark("original")["strokeDash"] == [5, 4]
    assert _mark("expert")["strokeDash"] == []
    assert _mark(None)["strokeDash"] == []


def test_each_series_is_named_in_the_legend():
    spec = ifk_charts._curve_line(CURVE, "depth", "original").to_dict()
    assert spec["transform"] == [{"calculate": '"Original"', "as": "series"}]
