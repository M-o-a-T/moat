"""
Configuration file for the Sphinx documentation builder.

For the full list of built-in configuration values, see the documentation:
https://www.sphinx-doc.org/en/master/usage/configuration.html

-- Project information -----------------------------------------------------
https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
"""
# pylint: disable=invalid-name

import importlib.metadata
import os
import sys

sys.path.insert(0, os.path.abspath(".."))

project = "pysignalclijsonrpc"
copyright = "2022, Stefan Heitmüller"  # pylint: disable=redefined-builtin
author = "Stefan Heitmüller <stefan.heitmueller@gmx.com>"
release = importlib.metadata.version(__package__)

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx_copybutton",
    "sphinx_inline_tabs",
]

templates_path = ["_templates"]
exclude_patterns = []

language = "en"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "furo"
html_static_path = ["_static"]
