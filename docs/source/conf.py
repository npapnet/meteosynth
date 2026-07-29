import os
import sys

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore

# conf.py lives in docs/source/, so the package sources are two levels up.
sys.path.insert(0, os.path.abspath("../../src"))

# Read project metadata dynamically from pyproject.toml (single source of truth maintained by `uv version`)
pyproject_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../pyproject.toml"))

if tomllib is not None:
    with open(pyproject_path, "rb") as f:
        pyproject_data = tomllib.load(f).get("project", {})
    project = pyproject_data.get("name", "meteosynth")
    release = pyproject_data.get("version", "0.0.0")
else:
    import re
    with open(pyproject_path, "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(r'^\s*version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    release = match.group(1) if match else "0.0.0"
    match_name = re.search(r'^\s*name\s*=\s*"([^"]+)"', content, re.MULTILINE)
    project = match_name.group(1) if match_name else "meteosynth"

version = release
copyright = "2026, N.Papadakis"
author = "N.Papadakis"

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
