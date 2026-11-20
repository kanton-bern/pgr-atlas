"""Download names of the Raster-Karten (ad hoc) results. Kept out of app.py so
they can be tested without Streamlit or S3 (tests/test_raster_export.py).

probe-core names the files it writes (ifk_and_raster.raster_from_curves):
    depth_at_0.7m_2594477_1157052_2594767_1157152.tif    (mode A, threshold)
    velocity_rp10000_2606262_1144652_2606412_1144707.tif (mode B, return period)
The app offers them in the style of every download (ui_text, "Download file
names"), with the metric the file holds and the area's bounding box in LV95 m:
    adhoc_wiederkehrperiode_fliesstiefe_0_7m_2594477_1157052_2594767_1157152.tif
    adhoc_intensitaet_fliessgeschwindigkeit_10000_jahre_2606262_1144652_2606412_1144707.tif
"""

import os
import re

import ui_text

_VAR = r"(?P<var>depth|velocity|pressure)"
_SLUG = r"(?P<slug>\d+_\d+_\d+_\d+)"
_MODE_A = re.compile(
    rf"^{_VAR}_at_(?P<threshold>[0-9.]+(?:[eE][+-]?\d+)?)(?P<unit>m|ms|kNm2)_{_SLUG}\.tif$"
)
_MODE_B = re.compile(rf"^{_VAR}_rp(?P<rp>[0-9.]+)_{_SLUG}\.tif$")


def download_name(path: str) -> str:
    """The name a result file is offered under; a name that matches neither
    pattern is kept as it is."""
    name = os.path.basename(path)
    if m := _MODE_A.match(name):
        threshold = ui_text.file_number(m["threshold"]) + m["unit"].lower()
        return (
            f"adhoc_{ui_text.FILE_METRICS['return_period']}_{ui_text.FILE_VARIABLES[m['var']]}"
            f"_{threshold}_{m['slug']}.tif"
        )
    if m := _MODE_B.match(name):
        return (
            f"adhoc_{ui_text.FILE_METRICS['intensity']}_{ui_text.FILE_VARIABLES[m['var']]}"
            f"_{ui_text.file_number(m['rp'])}_jahre_{m['slug']}.tif"
        )
    return name
