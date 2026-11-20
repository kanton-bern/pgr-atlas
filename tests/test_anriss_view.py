"""Anriss: the Anriss a link opens (?id=)."""

import numpy as np
import pytest

from ui_common import anriss_query_params
from views.anriss import id_from_query


def test_a_link_with_an_id_gives_it():
    assert id_from_query({"id": "977441"}) == 977441


@pytest.mark.parametrize("params", [{}, {"other": "1"}, {"x": "2598502.5"}])
def test_a_link_without_an_id_gives_none(params):
    assert id_from_query(params) is None


@pytest.mark.parametrize("value", ["", "abc", "977441.5", "1e6", "0", "-3"])
def test_a_bad_id_raises(value):
    with pytest.raises(ValueError):
        id_from_query({"id": value})


@pytest.mark.parametrize("id_anriss", [977441, np.int64(977441)])
def test_an_id_written_to_a_link_reads_back(id_anriss):
    params = anriss_query_params(id_anriss)
    assert params == {"id": "977441"}
    assert id_from_query(params) == 977441
