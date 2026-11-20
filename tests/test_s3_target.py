import os

import pytest

import s3_target

BEDAG = {
    "PGR_ATLAS_S3_BEDAG_ENDPOINT_URL": "https://x7ba-s3-kakbfe.infra.be.ch:10443",
    "PGR_ATLAS_S3_BEDAG_REGION": "ch-bern-1",
    "PGR_ATLAS_S3_BEDAG_BUCKET": "aw3-pgr-atlas-test",
    "PGR_ATLAS_S3_BEDAG_ACCESS_KEY_ID": "bedag-key",
    "PGR_ATLAS_S3_BEDAG_SECRET_ACCESS_KEY": "bedag-secret",
}
HOSTTECH = {
    "PGR_ATLAS_S3_HOSTTECH_ENDPOINT_URL": "https://f712.gos3.io",
    "PGR_ATLAS_S3_HOSTTECH_BUCKET": "adelboden-test",
    "PGR_ATLAS_S3_HOSTTECH_ACCESS_KEY_ID": "hosttech-key",
    "PGR_ATLAS_S3_HOSTTECH_SECRET_ACCESS_KEY": "hosttech-secret",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in list(os.environ):
        if var.startswith(("PGR_ATLAS_S3_", "PROBE_S3_")):
            monkeypatch.delenv(var)


def _set(monkeypatch, env):
    for var, value in env.items():
        monkeypatch.setenv(var, value)


def test_no_target_leaves_probe_s3_alone(monkeypatch):
    """Local development: PROBE_S3_* as set."""
    monkeypatch.setenv("PROBE_S3_BUCKET", "maxi")
    assert s3_target.apply() is None
    assert os.environ["PROBE_S3_BUCKET"] == "maxi"
    assert s3_target.available() == []


def test_apply_copies_the_target(monkeypatch):
    _set(monkeypatch, BEDAG | HOSTTECH | {"PGR_ATLAS_S3_TARGET": "bedag"})
    assert s3_target.available() == ["bedag", "hosttech"]
    assert s3_target.apply() == "bedag"
    assert os.environ["PROBE_S3_ENDPOINT_URL"] == BEDAG["PGR_ATLAS_S3_BEDAG_ENDPOINT_URL"]
    assert os.environ["PROBE_S3_REGION"] == "ch-bern-1"
    assert os.environ["PROBE_S3_BUCKET"] == "aw3-pgr-atlas-test"
    assert os.environ["PROBE_S3_ACCESS_KEY_ID"] == "bedag-key"
    assert os.environ["PROBE_S3_SECRET_ACCESS_KEY"] == "bedag-secret"


def test_a_field_the_target_leaves_out_is_removed(monkeypatch):
    """Hosttech has no region: Bedag's must not stay behind after a switch."""
    _set(monkeypatch, BEDAG | HOSTTECH | {"PGR_ATLAS_S3_TARGET": "bedag"})
    s3_target.apply()
    monkeypatch.setenv("PGR_ATLAS_S3_TARGET", "hosttech")
    assert s3_target.apply() == "hosttech"
    assert "PROBE_S3_REGION" not in os.environ
    assert os.environ["PROBE_S3_BUCKET"] == "adelboden-test"
    assert os.environ["PROBE_S3_ACCESS_KEY_ID"] == "hosttech-key"


def test_unknown_target_ends_the_process(monkeypatch):
    _set(monkeypatch, HOSTTECH | {"PGR_ATLAS_S3_TARGET": "bedag"})
    with pytest.raises(SystemExit, match="PGR_ATLAS_S3_BEDAG_ENDPOINT_URL"):
        s3_target.apply()


def test_source_label(monkeypatch):
    assert s3_target.source_label("https://f712.gos3.io") == "Hosttech"
    assert s3_target.source_label("https://x7ba-s3-kakbfe.infra.be.ch:10443") == "Bedag"
    assert s3_target.source_label("https://s3.example.org") == "s3.example.org"
    # The endpoint decides, not the target's name.
    _set(monkeypatch, BEDAG | {"PGR_ATLAS_S3_TARGET": "bedag"})
    assert s3_target.source_label("https://f712.gos3.io") == "Hosttech"


@pytest.fixture()
def probe_core_keys(monkeypatch):
    """What probe-core resolves from the environment, set by the test."""
    from probe_core import s3

    keys = {"access_key": None, "secret_key": None}
    monkeypatch.setattr(s3, "S3_CONFIG", keys)
    return keys


def test_credentials_need_key_and_secret(probe_core_keys):
    assert not s3_target.has_credentials()
    probe_core_keys["access_key"] = "key"
    assert not s3_target.has_credentials()
    probe_core_keys["secret_key"] = "secret"
    assert s3_target.has_credentials()


def test_startup_names_the_missing_variables(probe_core_keys, capsys):
    s3_target.warn_if_no_credentials()
    err = capsys.readouterr().err
    assert "PROBE_S3_ACCESS_KEY_ID" in err and "PROBE_S3_SECRET_ACCESS_KEY" in err

    probe_core_keys.update(access_key="key", secret_key="secret")
    s3_target.warn_if_no_credentials()
    assert capsys.readouterr().err == ""
