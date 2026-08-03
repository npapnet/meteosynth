"""
Which folder is the root of this run: the one question, answered once.

Every entry point that writes something has to answer it -- a script fetching a training
record, a subcommand writing an ensemble -- and there are exactly two right answers,
depending on how the code was entered:

* **A script's files belong beside the script.** ``uv run python
  examples/use_cases/year-leros/leros_year_ensemble.py`` should put its data in
  ``examples/use_cases/year-leros/``, whichever folder the terminal happened to be in.
* **A command's files belong where the command was run.** ``meteosynth generate`` in
  ``~/my-study`` should put them in ``~/my-study``, because that is the only place a
  command *can* mean.

Both give the same layout -- ``data/`` for what was collected, ``output/`` for what was
generated -- so learning one is learning the other::

    <root>/
        data/      collected records
        output/    generated series, figures, tables

Why a module rather than a line in each script
----------------------------------------------
The rule above is four lines of code. Writing those four lines into every script is the
obvious alternative, and it is how this repository arrived at **three** conventions that
disagree: the working directory in one folder, a hard-coded ``examples/data`` in four
more, an explicitly named file in a sixth. Nothing failed; the copies simply stopped
agreeing, and nothing anywhere said so.

So the rule lives here, and everything asks. That is the whole of this module's job.

An explicit path is read from the working directory
---------------------------------------------------
The root above applies **only when the caller says nothing**. A path someone typed is
read the way their shell would read it::

    fetch_pvgis(..., data_dir="inputs")     # <working directory>/inputs, never <root>/inputs

This is deliberate and it is the one place the two ideas meet. Anchoring a typed relative
path to the script would mean ``--data-dir inputs`` pointing somewhere the user cannot see
from their prompt, which is exactly the surprise this module exists to remove.

No ambient configuration
------------------------
There is **no environment variable and no global setting**, for the reason
:func:`meteosynth.store.default_data_dir` gives at length: ambient configuration would let
the same script read a different store depending on which shell launched it.
:func:`workspace` reads its argument and the working directory, and nothing else.

It also does not go looking for its caller. A library cannot reliably find the file that
called it -- walking the call stack breaks in a REPL, in a notebook and in anything
frozen -- so the anchor is **passed in**, never discovered.

A note on the name
------------------
The module is ``paths`` and the function is :func:`workspace`, deliberately not both
``workspace``. A ``workspace.py`` holding a ``workspace()`` that the package re-exports
would leave ``meteosynth.workspace`` bound to the *function*, making the module
unreachable by ``import meteosynth.workspace`` -- ``import a.b as m`` binds
``getattr(a, "b")`` when that attribute exists, so it would silently hand back the
callable. Two names, no shadow: ``meteosynth.paths`` is the module,
``meteosynth.workspace`` is the function, ``meteosynth.Workspace`` the class.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from typing import Optional, Union

__all__ = [
    "DATA_DIR_NAME",
    "OUTPUT_DIR_NAME",
    "Workspace",
    "workspace",
]

#: Folder collected records go in, under the workspace root.
DATA_DIR_NAME = "data"

#: Folder generated files go in, under the workspace root. A sibling of the data folder
#: rather than a child, because the two have opposite lifetimes: a record is collected once
#: and re-read, an output is rewritten every run.
OUTPUT_DIR_NAME = "output"


@dataclass(frozen=True)
class Workspace:
    """
    One folder a run treats as "here", and the two folders hanging off it.

    Parameters
    ----------
    root : pathlib.Path
        The workspace root. Always absolute -- :func:`workspace` resolves it, so nothing
        downstream has to care what the working directory was at the time.

    Notes
    -----
    Construct via :func:`workspace` rather than directly; that is where the rule for
    choosing a root lives.

    **Nothing here creates a folder until something is written.** The properties are
    plain paths, so importing this module and holding a ``Workspace`` leaves the disk
    untouched; :meth:`data` and :meth:`output` create on demand, because by then a caller
    has committed to writing.

    Examples
    --------
    >>> ws = workspace("/tmp/study")                          # doctest: +SKIP
    >>> ws.data_dir                                           # doctest: +SKIP
    PosixPath('/tmp/study/data')
    >>> ws.output("year_2023.csv")                            # doctest: +SKIP
    PosixPath('/tmp/study/output/year_2023.csv')
    """

    root: pathlib.Path

    @property
    def data_dir(self) -> pathlib.Path:
        """``<root>/data`` -- the project's store of collected records."""
        return self.root / DATA_DIR_NAME

    @property
    def output_dir(self) -> pathlib.Path:
        """``<root>/output`` -- everything generated, and nothing collected."""
        return self.root / OUTPUT_DIR_NAME

    def data(self, name: str) -> pathlib.Path:
        """
        Path to ``name`` inside the data folder, creating the folder.

        Parameters
        ----------
        name : str
            A filename, not a path. Nested names work but say nothing the store can read:
            :func:`meteosynth.store.scan` looks one level deep, because provenance inside
            a record is what organises it, not where it sits.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / name

    def output(self, name: str) -> pathlib.Path:
        """Path to ``name`` inside the output folder, creating the folder."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir / name

    def describe(self) -> str:
        """
        One line naming where this run reads and writes, for a script to print.

        Scripts announce their workspace before doing anything slow, so a wrong folder is
        caught in the first second rather than after a download. Having the sentence here
        keeps them all saying it the same way.
        """
        return f"workspace: {self.root}  ({DATA_DIR_NAME}/, {OUTPUT_DIR_NAME}/)"

    def __str__(self) -> str:  # pragma: no cover -- convenience for a print()
        return str(self.root)


def workspace(anchor: Union[None, str, os.PathLike] = None) -> Workspace:
    """
    The workspace root for this run.

    Parameters
    ----------
    anchor : str, os.PathLike or None, optional
        What to anchor to:

        * ``None`` -- the **working directory**. This is the command case, and the
          fallback in a notebook or REPL where there is no script file.
        * ``__file__`` -- a *file*, so the root is **the folder containing it**. This is
          the script case: it does not move when the script is launched from elsewhere.
        * a *directory* -- used as the root itself. A relative one is read from the
          working directory, like any path a user types.

        A path that does not exist is treated as a directory, since the folder a run is
        about to create is a legitimate root.

    Returns
    -------
    Workspace
        With an absolute :attr:`~Workspace.root`.

    Notes
    -----
    **The file-or-directory test is what makes ``__file__`` work without a second
    function.** ``workspace(__file__)`` and ``workspace(some_dir)`` both mean "root here",
    and a script should not have to say which kind of thing it is holding.

    A script written as ``#%%`` cells runs both as a file and inside an editor's
    interactive window, where ``__file__`` is undefined. The idiom that covers both::

        WS = workspace(globals().get("__file__"))

    In the editor that yields ``None`` and the root falls back to the working directory --
    the same answer the CLI gets, which is the honest one when there is no script to be
    beside.

    Examples
    --------
    >>> workspace().root == pathlib.Path.cwd()
    True
    >>> workspace(__file__).root.name
    'meteosynth'
    """
    if anchor is None:
        return Workspace(pathlib.Path.cwd())

    path = pathlib.Path(anchor)
    # Relative to the working directory, per the module docstring. `resolve` does this and
    # normalises `..` in one step; it does not require the path to exist.
    path = path.resolve()
    return Workspace(path.parent if path.is_file() else path)
