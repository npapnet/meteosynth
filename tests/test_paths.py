"""
Where a run reads and writes: the workspace rule, one test per sentence of it.

The regression these exist for is specific and was live until `FEAT-21`: a script fetched
into ``./data`` under **the terminal's** folder rather than its own, so running the same
script from two directories built two stores and downloaded twice. Test 2 is that one.
"""

from __future__ import annotations

import pathlib

import pytest

from meteosynth import Workspace, default_data_dir, workspace
from meteosynth.paths import DATA_DIR_NAME, OUTPUT_DIR_NAME


# --------------------------------------------------------------------------------------
# Choosing a root
# --------------------------------------------------------------------------------------


def test_no_anchor_is_the_working_directory(tmp_path, monkeypatch):
    """This is the command case, and the notebook fallback."""
    monkeypatch.chdir(tmp_path)
    assert workspace().root == tmp_path.resolve()


def test_no_anchor_follows_a_change_of_directory(tmp_path, monkeypatch):
    """Nothing is cached at import: the answer is read each time it is asked for."""
    monkeypatch.chdir(tmp_path)
    first = workspace().root

    second_dir = tmp_path / "elsewhere"
    second_dir.mkdir()
    monkeypatch.chdir(second_dir)

    assert workspace().root == second_dir.resolve()
    assert first != workspace().root


def test_a_file_anchor_is_the_folder_containing_it(tmp_path):
    """``workspace(__file__)`` means "beside this script", so the file's parent."""
    script = tmp_path / "run_me.py"
    script.write_text("", encoding="utf-8")

    assert workspace(script).root == tmp_path.resolve()


def test_a_file_anchor_does_not_follow_a_change_of_directory(tmp_path, monkeypatch):
    """**The regression this module exists for.**

    A script anchored to itself keeps its own folder however it was launched. Before
    `FEAT-21` the default store was the working directory, so this was false and the same
    script run from two places built two stores.
    """
    script_dir = tmp_path / "use_case"
    script_dir.mkdir()
    script = script_dir / "run_me.py"
    script.write_text("", encoding="utf-8")

    launched_from = tmp_path / "somewhere_else"
    launched_from.mkdir()
    monkeypatch.chdir(launched_from)

    assert workspace(script).root == script_dir.resolve()
    assert workspace(script).data_dir == script_dir.resolve() / DATA_DIR_NAME


def test_none_is_the_same_as_no_argument(tmp_path, monkeypatch):
    """``globals().get("__file__")`` yields None in a notebook cell; it must not raise."""
    monkeypatch.chdir(tmp_path)
    assert workspace(None) == workspace()


def test_a_directory_anchor_is_used_as_the_root(tmp_path):
    """A folder that is not a file is the root itself, not its parent."""
    study = tmp_path / "study"
    study.mkdir()
    assert workspace(study).root == study.resolve()


def test_a_relative_anchor_is_read_from_the_working_directory(tmp_path, monkeypatch):
    """The rule for every path a user types, here and in ``data_dir=``."""
    monkeypatch.chdir(tmp_path)
    assert workspace("inputs").root == (tmp_path / "inputs").resolve()


def test_a_root_that_does_not_exist_yet_is_allowed(tmp_path, monkeypatch):
    """The folder a first run is about to create is a legitimate root."""
    monkeypatch.chdir(tmp_path)
    assert workspace("not_here_yet").root == (tmp_path / "not_here_yet").resolve()


def test_the_root_is_always_absolute(tmp_path, monkeypatch):
    """So nothing downstream has to know what the working directory was."""
    monkeypatch.chdir(tmp_path)
    assert workspace("inputs").root.is_absolute()
    assert workspace().root.is_absolute()


# --------------------------------------------------------------------------------------
# The layout hanging off it
# --------------------------------------------------------------------------------------


def test_the_layout_is_data_and_output_under_the_root(tmp_path):
    ws = workspace(tmp_path)
    assert ws.data_dir == tmp_path.resolve() / "data"
    assert ws.output_dir == tmp_path.resolve() / "output"
    assert (DATA_DIR_NAME, OUTPUT_DIR_NAME) == ("data", "output")


def test_naming_a_workspace_creates_nothing(tmp_path):
    """Importing and constructing must not touch the disk. Only writing does."""
    ws = workspace(tmp_path / "study")
    _ = ws.data_dir, ws.output_dir

    assert not (tmp_path / "study").exists()


def test_asking_for_a_path_creates_the_folder(tmp_path):
    """By the time a caller asks for a path inside, they have committed to writing."""
    ws = workspace(tmp_path)

    record = ws.data("pvgis_hourly_leros_2005_2023.parquet")
    figure = ws.output("year.png")

    assert record.parent.is_dir() and record.parent == ws.data_dir
    assert figure.parent.is_dir() and figure.parent == ws.output_dir
    # The path is returned, not the file: nothing has been written yet.
    assert not record.exists() and not figure.exists()


def test_a_workspace_is_frozen(tmp_path):
    """The root is decided once, at the top of a run, and cannot drift mid-run."""
    ws = workspace(tmp_path)
    with pytest.raises(Exception):
        ws.root = tmp_path / "elsewhere"       # type: ignore[misc]


def test_describe_names_the_root(tmp_path):
    assert str(tmp_path.resolve()) in workspace(tmp_path).describe()


# --------------------------------------------------------------------------------------
# The seam with the store
# --------------------------------------------------------------------------------------


def test_default_data_dir_is_the_working_directory_workspace(tmp_path, monkeypatch):
    """One definition, two names -- so the CLI case and the store cannot disagree."""
    monkeypatch.chdir(tmp_path)
    assert default_data_dir() == workspace().data_dir


def test_a_workspace_can_be_built_directly_from_a_path(tmp_path):
    """The dataclass is public; ``workspace()`` is only the rule for choosing a root."""
    assert Workspace(pathlib.Path(tmp_path)).data_dir == tmp_path / "data"
