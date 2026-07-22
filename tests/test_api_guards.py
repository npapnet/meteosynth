"""Guards against the removed API creeping back.

These are the breaking changes of the 0.2.0 redesign. Each was removed for a reason
recorded in ``docs/design/variable-specs-and-initialisation.md``; a guard here means a
reintroduction fails loudly rather than quietly restoring a defect.
"""

import io
import pathlib
import tokenize

import pytest

SRC = pathlib.Path(__file__).parent.parent / "src" / "meteosynth"

# ``markov_implementations/`` holds two alternative simulators (continuous and discrete)
# that predate this design and are not on the KDE-2D path it redesigns. They still use
# global seeding and are deliberately out of scope here; excluding them keeps these
# guards honest about what they actually cover rather than silently passing because the
# pattern was spelled differently.
LEGACY = "markov_implementations"

PY_FILES = sorted(p for p in SRC.rglob("*.py") if LEGACY not in p.parts)


def _code_only(source: str) -> str:
    """Strip comments and string literals, leaving executable code.

    Without this the guards would fire on their own explanations: a docstring saying
    "``start_value`` was removed because..." is exactly the prose we want to keep, and
    is not a reintroduction of the parameter.
    """
    out = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except tokenize.TokenError:  # pragma: no cover - only on malformed source
        return source
    return " ".join(out)


def _sources():
    for path in PY_FILES:
        yield path, _code_only(path.read_text(encoding="utf-8"))


def test_there_are_source_files_to_scan():
    """Guard the guards: a bad glob would make every test below pass vacuously."""
    assert len(PY_FILES) > 5


def test_the_stripper_keeps_code_and_drops_prose():
    """And guard the stripper, for the same reason."""
    source = '"""A docstring mentioning start_value."""\n# comment: start_value\nx = 1\n'
    stripped = _code_only(source)

    assert "start_value" not in stripped
    assert "x" in stripped

    assert "start_value" in _code_only("start_value = 1\n")


def test_no_start_value_anywhere():
    """start_value was inert for irradiance and out-of-domain for wind and temp.

    Its default of 0.0 sat outside the observed hour-0 range of both non-degenerate
    variables, and far enough out it crashed rather than merely biased.
    """
    offenders = [str(p) for p, text in _sources() if "start_value" in text]
    assert not offenders, f"start_value reintroduced in {offenders}"


def test_no_global_numpy_seeding():
    """np.random.seed mutates process-wide state as a side effect.

    An ensemble built from n independent one-day calls cannot be seeded through it, and
    reseeding per step made every step draw the same value.
    """
    offenders = [str(p) for p, text in _sources() if "np.random.seed(" in text]
    assert not offenders, f"global seeding reintroduced in {offenders}"


def test_no_singularity_type():
    """Replaced by the Kind enum; NC and CC collapsed since both returned the constant."""
    offenders = [str(p) for p, text in _sources() if "singularity_type" in text]
    assert not offenders, f"singularity_type reintroduced in {offenders}"


def test_generate_series_is_not_on_env_series_generator():
    """The demarcation, which is otherwise enforced only by absence.

    A month subset has one pooled pi(x0) and one set of transitions shared by every
    generated day, so there is no honest answer to "what does day 32 look like".
    Trajectories therefore live only on the rolling-window path.
    """
    from meteosynth.generators import DayWindowGenerator, EnvSeriesGenerator

    assert not hasattr(EnvSeriesGenerator, "generate_series")
    assert hasattr(DayWindowGenerator, "generate_series")


def test_removed_generator_methods_are_gone():
    from meteosynth.generators import DayWindowGenerator, EnvSeriesGenerator

    assert not hasattr(EnvSeriesGenerator, "gen_day_sequence")
    assert not hasattr(EnvSeriesGenerator, "generate_ensemble")
    assert not hasattr(DayWindowGenerator, "gen_day_sequence")


def test_met_data_cols_whitelist_is_gone():
    """MODELLED_ATTRS gated attr_str, which is how a PVGIS quality flag became
    modellable. The registry gates now."""
    import meteosynth.constants as constants
    import meteosynth.generators as generators

    assert not hasattr(generators, "MET_DATA_COLS")
    assert not hasattr(constants, "MODELLED_ATTRS")
    assert not hasattr(constants, "REQUIRED_COLS")


def test_public_api_exports_the_new_surface():
    import meteosynth

    for name in [
        "VariableSpec", "register", "registered", "get_spec", "Kind",
        "adapters", "DayWindowGenerator", "EnvSeriesGenerator",
        "build_cross_midnight_pairs", "build_initial_values",
    ]:
        assert name in meteosynth.__all__, f"{name} missing from __all__"
        assert hasattr(meteosynth, name), f"{name} not importable"
