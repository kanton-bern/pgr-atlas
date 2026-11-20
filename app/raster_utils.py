"""Shared raster colorization helpers for the Raster-Derivate view.

Pure numpy, no GDAL/rasterio dependency -- display-only, so it lives in the
app, not in probe-core.

The colour domain and ramp are passed in explicitly by the caller
(views/raster_derivate.py's _style, forwarded to derivate_bbox_server.py as
query args), since the view shows several metrics with different scales.
"""

import numpy as np

# viridis sampled at 7 stops (0, 1/6, ..., 1): purple -> yellow. 'viridis_r'
# (yellow first) is used where a SMALL value is the dangerous end
# (Wiederkehrperiode: short return period = frequent = high hazard), so
# "yellow = more hazard" reads the same across all metrics.
# frontend/src/raster_bbox_map/value-format.ts's RAMPS mirrors these for the legend.
_VIRIDIS = [
    (68, 1, 84),
    (68, 57, 131),
    (49, 104, 142),
    (33, 145, 140),
    (53, 183, 121),
    (144, 215, 67),
    (253, 231, 37),
]
RAMPS = {
    "viridis": _VIRIDIS,
    "viridis_r": _VIRIDIS[::-1],
}
# 'mask' scale: 0/1 rasters (affected_mask) -- 1 gets this colour, 0 stays transparent.
MASK_COLOR = (230, 85, 13)
# Named mask colours a request may pick; orange is the default (MAXI affected
# mask), purple is the Gebäudeschatten view's "im Schatten".
MASK_COLORS = {"orange": MASK_COLOR, "purple": (155, 111, 201)}
SCALES = ("log", "linear", "mask")

# Fixed colour domain of Wiederkehrperiode across ALL thresholds:
# a per-band real vmin/vmax made the same colour mean a different return
# period for every threshold. RETURN_PERIOD_SAFE_YEARS doubles as the sanity
# cap on real vmax, which can be a statistically-extrapolated artifact up to
# 1e16 years. Trefferhäufigkeit (events/year) uses the reciprocal domain, so a
# rate and the matching return period get the same colour.
RETURN_PERIOD_LOW_YEARS = 100
RETURN_PERIOD_SAFE_YEARS = 100_000

# The smallest colour span, so a band of one value doesn't divide by zero.
_MIN_SPAN = 1e-12


def colorize_mask(values, color=MASK_COLOR):
    """0/1 band -> RGBA uint8 array (H, W, 4): 1 gets `color`, everything else transparent."""
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    is_set = values == 1
    rgba[is_set, :3] = color
    rgba[is_set, 3] = 255
    return rgba


def _colorize_band(values, vmin, vmax, scale, ramp="viridis"):
    """band values -> RGBA uint8 array (H, W, 4). NaN = transparent.
    'log': values <= 0 are transparent too (log10-normalized over [vmin, vmax]);
    'linear': normalized over [vmin, vmax]; 'mask': 1 -> MASK_COLOR, else
    transparent. Values outside [vmin, vmax] saturate at the ramp ends."""
    if scale == "mask":
        return colorize_mask(values)
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)

    valid = np.isfinite(values)
    # Each pixel's position along the ramp, 0 (vmin) to 1 (vmax).
    ramp_position = np.zeros(values.shape, dtype=np.float64)
    if scale == "log":
        valid &= values > 0
        log_min, log_max = np.log10(vmin), np.log10(vmax)
        with np.errstate(divide="ignore", invalid="ignore"):
            log_values = np.log10(np.clip(values[valid], vmin, vmax))
        span = max(log_max - log_min, _MIN_SPAN)
        ramp_position[valid] = np.clip((log_values - log_min) / span, 0, 1)
    else:
        span = max(vmax - vmin, _MIN_SPAN)
        ramp_position[valid] = np.clip((values[valid] - vmin) / span, 0, 1)

    stops_rgb = RAMPS[ramp]
    stops = np.linspace(0.0, 1.0, len(stops_rgb))
    for channel in range(3):
        channel_stops = [stop[channel] for stop in stops_rgb]
        rgba[..., channel] = np.interp(ramp_position, stops, channel_stops).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
    return rgba
