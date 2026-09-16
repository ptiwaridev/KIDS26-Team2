"""Sanity check that the dev environment is wired up correctly."""


def test_imports():
    import azure.search.documents  # noqa: F401
    import pyodbc  # noqa: F401
    import streamlit  # noqa: F401
