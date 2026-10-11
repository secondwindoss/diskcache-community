"""Test the package-level import checks."""

import warnings

import pytest

import diskcache as dc


def test_warns_when_upstream_distribution_is_installed(tmp_path):
    (tmp_path / 'diskcache-5.6.3.dist-info').mkdir()

    with pytest.warns(RuntimeWarning, match='pip uninstall diskcache'):
        assert dc._warn_if_upstream_installed(str(tmp_path))


def test_warns_for_legacy_egg_info(tmp_path):
    (tmp_path / 'diskcache-5.6.3-py3.12.egg-info').mkdir()

    with pytest.warns(RuntimeWarning):
        assert dc._warn_if_upstream_installed(str(tmp_path))


def test_silent_when_only_the_fork_is_installed(tmp_path):
    (tmp_path / 'diskcache_community-5.6.3.dist-info').mkdir()
    (tmp_path / 'diskcache').mkdir()

    with warnings.catch_warnings():
        warnings.simplefilter('error')
        assert not dc._warn_if_upstream_installed(str(tmp_path))


def test_silent_when_the_directory_is_missing(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        assert not dc._warn_if_upstream_installed(str(tmp_path / 'none'))


def test_silent_in_this_environment():
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        assert not dc._warn_if_upstream_installed()
