import os
import stat
import time

import work_dirs


def test_new_dirs_are_private_and_unique():
    first, second = (
        work_dirs.new_dir(work_dirs.RASTER_JOBS),
        work_dirs.new_dir(work_dirs.RASTER_JOBS),
    )
    assert first != second and first.parent == second.parent == work_dirs.root() / "raster_jobs"
    assert stat.S_IMODE(first.stat().st_mode) == 0o700
    work_dirs.remove(first)
    assert not first.exists() and second.exists()
    work_dirs.remove(None)  # nothing to remove: fine


def test_sweep_deletes_only_what_is_older_than_seven_days():
    old_job, new_job = (
        work_dirs.new_dir(work_dirs.RASTER_JOBS),
        work_dirs.new_dir(work_dirs.RASTER_JOBS),
    )
    (old_job / "depth.tif").write_bytes(b"x")
    upload = work_dirs.new_dir(work_dirs.UPLOADS)
    old_curves = work_dirs.kind_dir(work_dirs.RASTER_CURVES) / "abc.parquet"
    new_curves = old_curves.with_name("def.parquet")
    old_curves.write_bytes(b"x")
    new_curves.write_bytes(b"x")
    # Anything else in the work root is not the app's to delete.
    foreign = work_dirs.root() / "maxi_rasters" / "depth_rp300_1_2_3_4.tif"
    foreign.parent.mkdir()
    foreign.write_bytes(b"x")
    eight_days_ago = time.time() - 8 * 24 * 3600
    for path in (old_job, upload, old_curves, foreign, foreign.parent):
        os.utime(path, (eight_days_ago, eight_days_ago))

    assert work_dirs.sweep() == 3
    assert not old_job.exists() and not upload.exists() and not old_curves.exists()
    assert new_job.exists() and new_curves.exists() and foreign.exists()


def test_sweep_without_work_folders_does_nothing():
    assert work_dirs.sweep() == 0
