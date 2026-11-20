import configparser
from importlib.resources import files

# ── Data lake top-level folder names (disk paths and S3 prefixes) ──────────────
DATA_LAKE_DIR_RAW_SIMS = "Raw-Sim-Dirs"
DATA_LAKE_DIR_BRONZE = "Data-Lake-Bronze"
DATA_LAKE_DIR_SILVER = "Data-Lake-Silver"
DATA_LAKE_DIR_GOLD = "Data-Lake-Gold"
DATA_LAKE_DIR_RUN_LOGS_RESULTS = "Run-Logs-Results"
DATA_LAKE_DIR_LOCKS = "locks"  # batch claims, kept on success; lock without silver = running

# One marker per 1000-batch range whose batches all have silver; listings skip marked ranges.
DATA_LAKE_DIR_RANGE_DONE = "Data-Lake-Range-Done"
BATCH_RANGE_SIZE = 1000  # batch dirs are 7-digit, so a 4-digit prefix covers one range

# QA sweep claim locks and results (<job_name>/kachel_<id>...); status and retry count are in
# the result filename, so one listing tells which kacheln are left.
DATA_LAKE_DIR_QA_LOCKS = "Data-Lake-QA-Locks"
DATA_LAKE_DIR_QA_RESULTS = "Data-Lake-QA-Results"

# ── Derivates: products computed from the lake ─────────────────────────────────
DATA_LAKE_DIR_DERIVATE = "Data-Lake-Derivate"
# Metric folder names, one top-level folder per metric under the derivate root:
DERIVATE_METRIC_RETURN_PERIOD = "return_period"
DERIVATE_METRIC_INTENSITY = "intensity"
DERIVATE_METRIC_HIT_RATE = "hit_rate"  # Trefferhäufigkeit: annual rate at a fixed threshold (= 1/return_period, but persisted directly rather than inverted)
DERIVATE_METRIC_COMBINED_HIT_RATE = "combined_hit_rate"  # Trefferhäufigkeit for an AND across variables (e.g. depth>0.1m AND pressure>=3kPa): annual rate + 80y Poisson probability
DERIVATE_METRIC_SIM_COUNT = (
    "sim_count"  # unweighted count of simulation rows reaching a pixel, no probability/threshold
)
DERIVATE_METRIC_START_RATE = "start_rate"  # Häufigkeit of anriss starts per pixel: rate (#/year) of starts with h >= a threshold whose release circle covers the pixel
DERIVATE_METRIC_AFFECTED_MASK = "affected_mask"
DERIVATE_METRIC_ANRISS_UMHUELLENDE = "anriss_umhuellende"
DATA_LAKE_DIR_DERIVATE_HULLS = f"{DATA_LAKE_DIR_DERIVATE}/{DERIVATE_METRIC_ANRISS_UMHUELLENDE}"
# Each derivate metric has its own folder, Hive-partitioned by its params, then its unit:
#   Data-Lake-Derivate/<metric>/<param>=<value>/.../id_kachel=<id>/data.tif
# Underscore-prefixed siblings of the Hive partition dirs, so a hive_partitioning
# glob over <metric>/ never trips over them:
#   <metric>/_mosaic/<param>=<value>/canton.tif (+ canton_bands.json)
DATA_LAKE_SUBDIR_MOSAIC = "_mosaic"
# Work-claim locks of the derivate runner: <derivate root>/_locks/<producer>/<unit_kind>=<id>.lock
DATA_LAKE_SUBDIR_LOCKS = "_locks"

# Run logs compacted per 1000-batch range: results/batch_XXXX_results.parquet (every
# batch's results.csv) and logs/batch_XXXX.log.gz (the .log files, concatenated).
DATA_LAKE_DIR_RUN_LOGS_RESULTS_COMPACTED = "Run-Logs-Results-Compacted"
DATA_LAKE_DIR_RUN_LOGS_RESULTS_COMPACTED_PARQUET = (
    f"{DATA_LAKE_DIR_RUN_LOGS_RESULTS_COMPACTED}/results"
)
DATA_LAKE_DIR_RUN_LOGS_RESULTS_COMPACTED_LOGS_GZ = (
    f"{DATA_LAKE_DIR_RUN_LOGS_RESULTS_COMPACTED}/logs"
)

# ── Probabilities/rates: inputs joined with gold at query time ─────────────────
# probability_lookup.parquet: lambda_Hangmuren, p_raeumlich and p_A per id_anriss.
# ablaufwahrscheinlichkeiten.csv: p_Ablauf per (mu, xsi, tau0) combination, sums to 1;
# S3 holds the only copy. p_h needs no file: see GOLD_P_H_MEAN/GOLD_P_H_MAX.
DATA_LAKE_DIR_PROBABILITIES_RATES = "Data-Lake-Probabilities-Rates"
DATA_LAKE_PROBABILITIES_RATES_LOOKUP = (
    f"{DATA_LAKE_DIR_PROBABILITIES_RATES}/probability_lookup.parquet"
)
DATA_LAKE_PROBABILITIES_RATES_ABLAUF = (
    f"{DATA_LAKE_DIR_PROBABILITIES_RATES}/ablaufwahrscheinlichkeiten.csv"
)


# ── Gebäudeschatten ─────────────────────────────────────────────────────────
# Second campaign: release areas are building footprints, not anriss circles. Same
# bronze/silver/gold shape as MAXI, in its own lake root.
DATA_LAKE_DIR_GEBAEUDESCHATTEN_RAW_SIMS = "Gebaeudeschatten-Raw-Sim-Dirs"
DATA_LAKE_DIR_GEBAEUDESCHATTEN_BRONZE = "Gebaeudeschatten-Data-Lake-Bronze"
DATA_LAKE_DIR_GEBAEUDESCHATTEN_SILVER = "Gebaeudeschatten-Data-Lake-Silver"
DATA_LAKE_DIR_GEBAEUDESCHATTEN_GOLD = "Gebaeudeschatten-Data-Lake-Gold"
DATA_LAKE_DIR_GEBAEUDESCHATTEN_GOLD_STAGING = "Gebaeudeschatten-Data-Lake-Gold-Staging"
DATA_LAKE_DIR_GEBAEUDESCHATTEN_GOLD_LEDGER = "Gebaeudeschatten-Data-Lake-Gold-Ledger"
DATA_LAKE_DIR_GEBAEUDESCHATTEN_RUN_LOGS_RESULTS = "Gebaeudeschatten-Run-Logs-Results"
DATA_LAKE_DIR_GEBAEUDESCHATTEN_LOCKS = "gebaeudeschatten-locks"  # separate prefix from DATA_LAKE_DIR_LOCKS -- MAXI's batch_XXXXXXX.lock names could otherwise collide with this campaign's own batch numbering
DATA_LAKE_DIR_GEBAEUDESCHATTEN_DERIVATE = "Gebaeudeschatten-Data-Lake-Derivate"
DATA_LAKE_DIR_GEBAEUDESCHATTEN_DERIVATE_AFFECTED_MASK = (
    f"{DATA_LAKE_DIR_GEBAEUDESCHATTEN_DERIVATE}/affected_mask"
)
# "Affected" definitions, one prefix each under affected_mask/, evaluated per row:
#   raw                            -- any row in SIM_SPATIAL
#   shadowing_building             -- SIM_SPATIAL_ZEROED, own_building_mask != 1
#   shadowing_building_surrounding -- SIM_SPATIAL_ZEROED, own_building_mask = 0
GEBAEUDESCHATTEN_AFFECTED_MASK_VARIANTS = (
    "raw",
    "shadowing_building",
    "shadowing_building_surrounding",
)

# Minimum Fliesstiefe [cm] for a row to count as affected: 1 cm filters numerical noise,
# 10 cm is where low intensity for Hangmuren starts. One raster set (_min<N>cm) per value.
GEBAEUDESCHATTEN_AFFECTED_MASK_MIN_DEPTHS_CM = (1, 10)

# Gold reach caps [m] from the release area; 800 is the simulation domain itself (no filter).
GEBAEUDESCHATTEN_GOLD_REACH_VARIANTS_M = (800, 100, 50, 25)


def gebaeudeschatten_gold_reach_dir(reach_m: int) -> str:
    """S3 prefix segment for one gold reach variant, e.g. 100 -> 'REACH_100M'."""
    assert reach_m in GEBAEUDESCHATTEN_GOLD_REACH_VARIANTS_M, (
        f"reach_m={reach_m} not in GEBAEUDESCHATTEN_GOLD_REACH_VARIANTS_M={GEBAEUDESCHATTEN_GOLD_REACH_VARIANTS_M}"
    )
    return f"REACH_{reach_m}M"


def gebaeudeschatten_gold_sim_spatial_dir(reach_m: int) -> str:
    return f"{DATA_LAKE_DIR_GEBAEUDESCHATTEN_GOLD}/{gebaeudeschatten_gold_reach_dir(reach_m)}/SIM_SPATIAL"


def gebaeudeschatten_gold_sim_spatial_zeroed_dir(reach_m: int) -> str:
    """SIM_SPATIAL with Fliesstiefe/Fliessgeschwindigkeit/Druck zeroed where the pixel is in
    or touches the row's own release building (own_building_mask 1 or 2). A separate
    dataset, so SIM_SPATIAL stays the unmodified simulation output."""
    return f"{DATA_LAKE_DIR_GEBAEUDESCHATTEN_GOLD}/{gebaeudeschatten_gold_reach_dir(reach_m)}/SIM_SPATIAL_ZEROED"


def gebaeudeschatten_gold_sim_anriss_dir(reach_m: int) -> str:
    return f"{DATA_LAKE_DIR_GEBAEUDESCHATTEN_GOLD}/{gebaeudeschatten_gold_reach_dir(reach_m)}/SIM_ANRISS"


# Building-polygon manifest, one row per release polygon; id_start is the layer's fid.
GEBAEUDESCHATTEN_MANIFEST_SCHEMA_DUCKDB = {
    "id_start": "BIGINT",
    "layer": "VARCHAR",  # source gdb layer, e.g. "TLM_Gebaeude_minus2m_sp"
    "fid": "INTEGER",  # OGR/FileGDB row id within that layer, unique per polygon
    "area": "DOUBLE",  # m^2, from the polygon geometry itself (SHAPE_Area)
    "x_start": "DOUBLE",  # polygon centroid
    "y_start": "DOUBLE",
    "xmin": "DOUBLE",  # polygon bbox, LV95
    "xmax": "DOUBLE",
    "ymin": "DOUBLE",
    "ymax": "DOUBLE",
    "geometry_wkb": "BLOB",
}
GEBAEUDESCHATTEN_MIN_AREA_M2 = 5.0  # below this, the delivered (already -2m-buffered) polygon is a sliver -- skipped, not simulated

# GOLD_SCHEMA_SIM_DUCKDB's pixel columns without id_prozessquelle/d (no probabilities here).
GEBAEUDESCHATTEN_SCHEMA_SIM_DUCKDB = {
    "id_start": "BIGINT",
    "x_start": "DOUBLE",  # silver release-polygon centroid
    "y_start": "DOUBLE",
    "A": "INTEGER",  # release polygon area [m^2]
    "h": "INTEGER",  # Anrissmaechtigkeit [cm] (relTh)
    "mu": "DECIMAL(7,3)",
    "xsi": "INTEGER",
    "tau0": "INTEGER",
    "x": "FLOAT",
    "y": "FLOAT",
    "Fliesstiefe": "INTEGER",  # max. Fliesstiefe [cm] = ROUND(depth*100)
    "Fliessgeschwindigkeit": "INTEGER",  # max. Fliessgeschwindigkeit [cm/s] = ROUND(velocity*100)
    "Druck": "INTEGER",  # Scheidegger [kPa], same PRESSURE_RHO/GRAVITY as MAXI
}

# own_building_mask, against the row's own building only: 0 = outside, 1 = pixel centre in
# the footprint, 2 = one of its 8 neighbours is.
GEBAEUDESCHATTEN_SCHEMA_SIM_ZEROED_DUCKDB = {
    **GEBAEUDESCHATTEN_SCHEMA_SIM_DUCKDB,
    "own_building_mask": "TINYINT",
}

# Per-kachel raster: is this 5 m cell in or next to ANY building (same 0/1/2 encoding);
# a map backdrop, unrelated to the zeroing above.
DATA_LAKE_DIR_GEBAEUDESCHATTEN_DERIVATE_BUILDING_MASK = (
    f"{DATA_LAKE_DIR_GEBAEUDESCHATTEN_DERIVATE}/building_mask"
)

# Sim key in silver column names, and the same key read from gold's renamed columns.
GEBAEUDESCHATTEN_GOLD_SIM_KEY = ["id_start", "area", "relTh", "mu", "xsi", "tau0"]
GEBAEUDESCHATTEN_GOLD_SIM_KEY_FROM_GOLD = "id_start, A AS area, h AS relTh, mu, xsi, tau0"

# Silver schema: LAKE_SCHEMA_DUCKDB with id_start/x_start/y_start for the anriss columns.
GEBAEUDESCHATTEN_LAKE_SCHEMA_DUCKDB = {
    "id_kachel": "INTEGER",
    "id_start": "BIGINT",
    "x_start": "DOUBLE",
    "y_start": "DOUBLE",
    "area": "INTEGER",
    "relTh": "INTEGER",
    "mu": "DECIMAL(7,3)",
    "xsi": "INTEGER",
    "tau0": "INTEGER",
    "x": "FLOAT",
    "y": "FLOAT",
    "depth": "FLOAT",
    "velocity": "FLOAT",
    "spatial_checksum": "BIGINT",
}


def batch_range_id(batch_id: int) -> int:
    """Which 1000-wide range a batch ID falls into (0-based)."""
    return batch_id // BATCH_RANGE_SIZE


def batch_range_prefix(range_id: int) -> str:
    """S3 key prefix covering one range's batch IDs (4-digit zero-padded —
    batch dir names are 7-digit, so this leaves exactly 3 digits = 1000 IDs)."""
    return f"batch_{range_id:04d}"


# ── Per-batch staging names (under Simulations/batch_XXXX/) ───────────────────
BATCH_BRONZE_DIRNAME = "batch_data_lake_bronze"
BATCH_SILVER_DIRNAME = "batch_data_lake_silver"
BATCH_SILVER_FILENAME = "batch_merged_silver.parquet"

# ── Shipped-file naming conventions ───────────────────────────────────────────
BATCH_SILVER_S3_SUFFIX = "silver.parquet"  # each batch ships as {batch_name}_silver.parquet

# ── Per-batch log and results files (local name inside batch dir, renamed on ship) ──
BATCH_LOG_FILENAME = "batch.log"  # shipped as {batch_name}.log
BATCH_RESULTS_FILENAME = "batch_results.csv"  # shipped as {batch_name}_results.csv

# ── Gold: the same rows (GOLD_SCHEMA_SIM_DUCKDB) in two layouts, both immutable ──
# SIM_SPATIAL/id_kachel=NNNNNNNN/data.parquet: per km², for area and pixel queries.
# SIM_ANRISS/batch_XXXX_sim_anriss.parquet: per 1000-batch range, sorted by id_anriss,
# for opening one event.
DATA_LAKE_DIR_GOLD_STAGING = "Data-Lake-Gold-Staging"  # scatter fragments
DATA_LAKE_DIR_GOLD_LEDGER = "Data-Lake-Gold-Ledger"  # resume + audit state
DATA_LAKE_DIR_GOLD_SIM_SPATIAL = f"{DATA_LAKE_DIR_GOLD}/SIM_SPATIAL"
DATA_LAKE_DIR_GOLD_SIM_ANRISS = f"{DATA_LAKE_DIR_GOLD}/SIM_ANRISS"
GOLD_HIVE_KEY = "id_kachel"
GOLD_KACHEL_FILENAME = "data.parquet"
GOLD_ROW_GROUP_SIZE = 500_000  # benchmarked: smaller groups are several times slower
GOLD_ZSTD_LEVEL = 9  # final kachel files are write-once/read-many

# Scheidegger total pressure in kN/m²: RHO*G*(depth + v²/(2G))/1000, with the constants
# the simulations ran with (the com1DFA config template shipped in probe_core/data/).

_com1dfa_cfg = configparser.ConfigParser(interpolation=None)
# read_string, not read(): read() ignores a missing file silently.
_com1dfa_cfg.read_string(
    files("probe_core").joinpath("data", "cfgCom1DFA_template.ini").read_text(encoding="utf-8")
)
PRESSURE_RHO = _com1dfa_cfg.getfloat("GENERAL", "rho")  # kg/m³ (1800: debris flow)
GRAVITY = _com1dfa_cfg.getfloat("GENERAL", "gravAcc")  # m/s²

# Gold columns; id_kachel lives only in the Hive directory name. Gold renames silver's
# area/relTh/depth/velocity to A/h/Fliesstiefe/Fliessgeschwindigkeit, as integer cm and
# cm/s; Druck is computed from those rounded values. Probabilities are joined at query time.
# x_anriss/y_anriss are DOUBLE because they are exact-equality join keys; FLOAT x/y suffice
# for the 5 m pixel grid.

# Unused: the materialized ENRICHED layout, replaced by the query-time join.
GOLD_SCHEMA_ENRICHED_DUCKDB = {
    "id_prozessquelle": "SMALLINT",  # manifest join on id_anriss
    "lambda_Hangmuren": "FLOAT",  # Xurce delivery, per anriss
    "id_anriss": "BIGINT",
    "x_anriss": "DOUBLE",  # silver X_rel_center (release centroid)
    "y_anriss": "DOUBLE",  # silver Y_rel_center
    "p_raeumlich": "FLOAT",  # Xurce delivery, per anriss
    "A": "INTEGER",  # Anrissfläche [m²] (silver area)
    "p_A": "FLOAT",  # Xurce delivery p_a, per anriss
    "d": "SMALLINT",  # Bodengründigkeit [cm] (manifest bodengruendigkeit)
    "h": "INTEGER",  # Anrissmächtigkeit [cm] (silver relTh = manifest h_cm)
    "p_h": "FLOAT",  # GOLD_P_H weight: h == d → mean, else max
    "mu": "DECIMAL(7,3)",
    "xsi": "INTEGER",
    "tau0": "INTEGER",
    "p_Ablauf": "FLOAT",
    "lambda_Ereignis": "FLOAT",
    "x": "FLOAT",
    "y": "FLOAT",
    "Fliesstiefe": "INTEGER",  # max. Fliesstiefe [cm] = ROUND(depth*100)
    "Fliessgeschwindigkeit": "INTEGER",  # max. Fliessgeschwindigkeit [cm/s] = ROUND(velocity*100)
    "Druck": "INTEGER",  # Scheidegger [kPa] from the rounded cm values, itself rounded
}

GOLD_SCHEMA_SIM_DUCKDB = {
    "id_prozessquelle": "SMALLINT",  # manifest join on id_anriss
    "id_anriss": "BIGINT",
    "x_anriss": "DOUBLE",  # silver X_rel_center (release centroid)
    "y_anriss": "DOUBLE",  # silver Y_rel_center
    "A": "INTEGER",  # Anrissfläche [m²] (silver area)
    "d": "SMALLINT",  # Bodengründigkeit [cm] (manifest bodengruendigkeit)
    "h": "INTEGER",  # Anrissmächtigkeit [cm] (silver relTh = manifest h_cm)
    "mu": "DECIMAL(7,3)",
    "xsi": "INTEGER",
    "tau0": "INTEGER",
    "x": "FLOAT",
    "y": "FLOAT",
    "Fliesstiefe": "INTEGER",  # max. Fliesstiefe [cm] = ROUND(depth*100)
    "Fliessgeschwindigkeit": "INTEGER",  # max. Fliessgeschwindigkeit [cm/s] = ROUND(velocity*100)
    "Druck": "INTEGER",  # Scheidegger [kPa] from the rounded cm values, itself rounded
}

# p_h weights for MAXI's two h_types: h == d is 'mean', otherwise 'max'.
GOLD_P_H_MEAN = 0.8
GOLD_P_H_MAX = 0.2

# ── Silver ↔ Gold content checksum ─────────────────────────────────────────────
# Per simulation (GOLD_SIM_KEY), COUNT and SUM(hash(row)) must match between silver (at
# scatter) and gold (at compact): equal sums mean the same rows, in any order or split.
# Silver hashes the same rounding gold stores, and the sim-identity columns are hashed too.
# The casts are identical on both sides because hash() is type-sensitive. The sum is kept
# modulo a prime below 2^63 (parquet has no int128). A changed formula needs a rebuilt ledger.
GOLD_AUDIT_HASH_MODULUS = 9223372036854775783
_GOLD_AUDIT_HASH_SUM = "(SUM(hash({cols})::HUGEINT) %% %d)::BIGINT" % GOLD_AUDIT_HASH_MODULUS
GOLD_AUDIT_HASH_EXPR_SILVER = _GOLD_AUDIT_HASH_SUM.format(
    cols=(
        "X_rel_center::DOUBLE, Y_rel_center::DOUBLE, x::FLOAT, y::FLOAT, "
        "CAST(ROUND(depth * 100) AS INTEGER), CAST(ROUND(velocity * 100) AS INTEGER), "
        "id_anriss::BIGINT, area::INTEGER, relTh::INTEGER, mu::DECIMAL(7,3), xsi::INTEGER, tau0::INTEGER"
    )
)
GOLD_AUDIT_HASH_EXPR_GOLD = _GOLD_AUDIT_HASH_SUM.format(
    cols=(
        "x_anriss::DOUBLE, y_anriss::DOUBLE, x::FLOAT, y::FLOAT, "
        "Fliesstiefe::INTEGER, Fliessgeschwindigkeit::INTEGER, "
        "id_anriss::BIGINT, A::INTEGER, h::INTEGER, mu::DECIMAL(7,3), xsi::INTEGER, tau0::INTEGER"
    )
)

# Audit ledger parquets use the silver-side names as the canonical sim key;
# the gold-side aggregates alias their renamed columns back to these.
GOLD_SIM_KEY = ["id_anriss", "area", "relTh", "mu", "xsi", "tau0"]
GOLD_SIM_KEY_FROM_GOLD = "id_anriss, A AS area, h AS relTh, mu, xsi, tau0"

# In-file sort for SIM_SPATIAL: plain spatial-first order (x,y row-group
# pruning; a Hilbert curve was benchmarked and was slower).
GOLD_SORT_COLS = ["x", "y", "id_anriss", "A", "h", "mu", "xsi", "tau0"]

# In-file sort for SIM_ANRISS: the drill-down order anriss -> A -> h -> rheology.
GOLD_SORT_COLS_ANRISS = ["id_anriss", "A", "h", "mu", "xsi", "tau0", "x", "y"]

# Maximum distance [m] of any silver pixel from its anriss centre (observed up to ~1271 m);
# decides which kacheln an event can touch (a 5×5 neighbourhood). Gold compact fails beyond it.
GOLD_MAX_REACH_M = 1500

# Pixels farther than this [m] (a circle around the anriss centre) are dropped wherever silver
# becomes gold or a hull. Mirrors the simulation domain cap; keep the two in sync by hand.
GOLD_PIXEL_MAX_REACH_M = 800

LAKE_SCHEMA_DUCKDB = {
    "id_kachel": "INTEGER",
    "id_anriss": "BIGINT",
    "X_rel_center": "DOUBLE",
    "Y_rel_center": "DOUBLE",
    "area": "INTEGER",
    "relTh": "INTEGER",  # Anrissmächtigkeit in cm (manifest h_cm, e.g. 25); AvaFrame gets m (relTh/100) only inside the com1DFA config
    "mu": "DECIMAL(7,3)",  # Fixed precision (e.g., 0.050)
    "xsi": "INTEGER",
    "tau0": "INTEGER",
    "x": "FLOAT",
    "y": "FLOAT",
    "depth": "FLOAT",
    "velocity": "FLOAT",
    "spatial_checksum": "BIGINT",
}
