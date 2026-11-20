"""Fixed places in the `adelboden-test` bucket that the e2e and AppTest suites use.

All of them lie in finished gold kacheln, so their results don't change when
kacheln are added elsewhere.
"""

TEST_BUCKET = "adelboden-test"

# LV95 pixel centre with non-empty IFK curves (124 contributing Anrisse).
IFK_PIXEL = (2598502.5, 1137502.5)
# Centre of a finished kachel where no simulated process arrives: empty curves.
IFK_PIXEL_NO_PROCESS = (2598502.5, 1135502.5)
# Outside every finished kachel (and outside the canton).
IFK_PIXEL_OUTSIDE = (2683002.5, 1248002.5)

# An Anriss that contributes to IFK_PIXEL, with SIM_ANRISS data and a hull.
ANRISS_ID = 999049
ANRISS_LV95 = (2598505.41, 1137500.27)
# Above every ID in the event manifest (61 M Anrisse).
UNKNOWN_ANRISS_ID = 999_999_999


def lv95_bbox(center, half_size_m):
    """A closed LV95 bbox ring around `center`, as the map components send it."""
    e, n = center
    return [
        [e - half_size_m, n - half_size_m],
        [e + half_size_m, n - half_size_m],
        [e + half_size_m, n + half_size_m],
        [e - half_size_m, n + half_size_m],
        [e - half_size_m, n - half_size_m],
    ]


# 100 m x 100 m around IFK_PIXEL, one kachel: Mode A (depth >= 0.1 m) gives 441
# pixels in about 6 s.
RASTER_SELECTION = {"type": "bbox", "ring": lv95_bbox(IFK_PIXEL, 50)}

# Gebäudeschatten (full-canton copy in the test bucket).
# A building with 2 simulations: at 800 m, 4 own pixels, 13 ring pixels, 571 pixels in all.
GEBAEUDESCHATTEN_BUILDING = 17801
# A pixel in its runout that 5 buildings reach at 800 m, all counting there.
GEBAEUDESCHATTEN_PIXEL = (2636392.5, 1162622.5)

# Derivate lake (with canton mosaics): hit_rate for depth, velocity and pressure,
# the combined hit rate for this combination, and intensity with a 300-year band.
DERIVATE_COMBO = "depth01_pressure3"
