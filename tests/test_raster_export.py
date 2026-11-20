import pytest

from raster_export import download_name


@pytest.mark.parametrize(
    "probe_core_name, offered",
    [
        (
            "depth_at_0.7m_2594477_1157052_2594767_1157152.tif",
            "adhoc_wiederkehrperiode_fliesstiefe_0_7m_2594477_1157052_2594767_1157152.tif",
        ),
        (
            "velocity_at_1.0ms_1_2_3_4.tif",
            "adhoc_wiederkehrperiode_fliessgeschwindigkeit_1ms_1_2_3_4.tif",
        ),
        ("pressure_at_30.0kNm2_1_2_3_4.tif", "adhoc_wiederkehrperiode_druck_30knm2_1_2_3_4.tif"),
        (
            "velocity_rp10000_2606262_1144652_2606412_1144707.tif",
            "adhoc_intensitaet_fliessgeschwindigkeit_10000_jahre_2606262_1144652_2606412_1144707.tif",
        ),
        ("depth_rp300_1_2_3_4.tif", "adhoc_intensitaet_fliesstiefe_300_jahre_1_2_3_4.tif"),
    ],
)
def test_result_files_get_german_names(probe_core_name, offered):
    assert download_name(f"/some/job/dir/{probe_core_name}") == offered


def test_unknown_names_are_kept():
    assert download_name("/x/something_else.tif") == "something_else.tif"
