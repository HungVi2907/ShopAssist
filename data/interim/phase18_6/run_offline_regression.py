"""Extend the unchanged Phase18.5 guarded selection with Phase18.6 tests."""
import runpy
import pytest

original_main=pytest.main
def main(args):
    return original_main(['tests/test_phase18_6.py',*args])
pytest.main=main
runpy.run_path('data/interim/phase18_5/run_offline_regression.py',run_name='__main__')
