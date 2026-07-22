import os
import sys
# conf.py lives in docs/source/, so the package sources are two levels up.
sys.path.insert(0, os.path.abspath("../../src"))

project = "meteosynth"
copyright = "2026, N.Papadakis"
author = "N.Papadakis"
release = "0.2.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinxcontrib.mermaid",
    "myst_parser",
]

# Allow both reStructuredText and Markdown source files.
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# Enable MyST features used by the narrative docs (e.g. $..$ math, ::: fences).
myst_enable_extensions = [
    "dollarmath",
    "amsmath",
    "colon_fence",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# Enable the HTML theme
html_theme = "furo"
html_static_path = ["_static"]
