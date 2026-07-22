import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde
import pytest
from meteosynth.markov_chain_simulator_kde2d import MarkovChainSimulator2dKDE

@pytest.fixture
def simulator_fixture():
    # Create sample data for testing
    np.random.seed(42)
    previous = np.random.normal(0, 1, 1000)
    current = previous + np.random.normal(0, 0.5, 1000)
    data = pd.DataFrame({'previous': previous, 'current': current})
    return MarkovChainSimulator2dKDE(data)

def test_initialization(simulator_fixture):
    # Test if the simulator initializes correctly
    assert len(simulator_fixture.data) == 1000
    assert hasattr(simulator_fixture, 'joint_kde')
    assert isinstance(simulator_fixture.joint_kde, gaussian_kde)

def test_get_x_domain(simulator_fixture):
    # Test the domain generation
    x_domain = simulator_fixture._get_x_domain()
    dom_min, dom_max, dom_range = simulator_fixture._calc_domain()
    assert len(x_domain) == 1000
    assert np.all(x_domain >= dom_min - 0.1 * dom_range)
    assert np.all(x_domain <= dom_max + 0.1 * dom_range)

def test_get_conditional_density_p1000(simulator_fixture):
    # Test conditional density calculation at POSITIVE value
    prev_value = 0.5
    # x_a is domain
    # x_b is density
    res_dict = simulator_fixture.get_conditional_density(prev_value, resolution=1000)
    x_a, x_b, cdf = res_dict['domain'], res_dict['pdf'], res_dict['cdf']

    assert len(x_a) == len(x_b)
    assert x_a.shape == (1000,)
    assert x_b.shape == (1000,)

    # The evaluation domain spans exactly the raw data range (padding=0.0),
    # which is the deliberate fix for the "negative values" issue.
    dom_min, dom_max, dom_range = simulator_fixture._calc_domain()
    assert x_a.min() == pytest.approx(dom_min, abs=1e-8)
    assert x_a.max() == pytest.approx(dom_max, abs=1e-8)
    assert np.median(x_a) == pytest.approx(0.5 * (dom_min + dom_max), abs=1e-8)

    # The pdf integrates (discretely) to resolution / dom_range by construction.
    assert x_b.sum() == pytest.approx(1000 / dom_range, rel=1e-8)
    assert np.all(x_b >= 0)
    assert np.argmax(x_b) == 463
    assert x_b.max() == pytest.approx(0.7664207111206898, abs=1e-8)

    # The cdf is a normalised, monotonically increasing distribution.
    assert cdf[-1] == pytest.approx(1.0, abs=1e-12)
    assert np.all(np.diff(cdf) >= 0)


def test_get_conditional_density_n100(simulator_fixture):
    # Test conditional density calculation at NEGATIVE value
    prev_value = -0.5
    # x_a is domain
    # x_b is density
    res_dict = simulator_fixture.get_conditional_density(prev_value, resolution=100)
    x_a, x_b, cdf = res_dict['domain'], res_dict['pdf'], res_dict['cdf']

    assert len(x_a) == len(x_b)
    assert x_a.shape == (100,)
    assert x_b.shape == (100,)

    # Domain spans the raw data range (padding=0.0), independent of resolution.
    dom_min, dom_max, dom_range = simulator_fixture._calc_domain()
    assert x_a.min() == pytest.approx(dom_min, abs=1e-8)
    assert x_a.max() == pytest.approx(dom_max, abs=1e-8)
    assert np.median(x_a) == pytest.approx(0.5 * (dom_min + dom_max), abs=1e-8)

    # density values
    assert x_b.sum() == pytest.approx(100 / dom_range, rel=1e-8)
    assert np.all(x_b >= 0)
    assert np.argmax(x_b) == 35
    assert x_b.max() == pytest.approx(0.8684212612932286, abs=1e-8)

    assert cdf[-1] == pytest.approx(1.0, abs=1e-12)
    assert np.all(np.diff(cdf) >= 0)


def test_get_next_state(simulator_fixture):
    # Test next state generation
    current_state = 0.0
    next_state = simulator_fixture.get_next_state(current_state, rng=42)
    assert isinstance(next_state, float)


def test_get_next_state_is_reproducible_from_a_seed(simulator_fixture):
    a = simulator_fixture.get_next_state(0.0, rng=42)
    b = simulator_fixture.get_next_state(0.0, rng=42)
    assert a == b


def test_a_shared_generator_advances_between_draws(simulator_fixture):
    """Passing one Generator must not restart the stream on every call.

    The old code reseeded the global RNG per step, so forwarding a seed produced the
    same draw every time. Threading a Generator is what fixes that.
    """
    rng = np.random.default_rng(0)
    draws = [simulator_fixture.get_next_state(0.0, rng=rng) for _ in range(5)]
    assert len(set(draws)) == 5


def test_no_global_random_state_is_touched(simulator_fixture):
    """Generating must not mutate process-wide numpy random state."""
    np.random.seed(1234)
    before = np.random.get_state()[1][:5].copy()
    simulator_fixture.get_next_state(0.0, rng=7)
    after = np.random.get_state()[1][:5]
    np.testing.assert_array_equal(before, after)


def test_plot_joint_distribution(simulator_fixture):
    # Test joint distribution plotting
    fig, ax = simulator_fixture.plot_joint_distribution()
    assert fig is not None
    assert ax is not None

def test_plot_conditional_densities(simulator_fixture):
    # Test conditional densities plotting
    fig, ax = simulator_fixture.plot_conditional_densities(prev_values=[-1.0, 0.0, 1.0])
    assert fig is not None
    assert ax is not None

def test_plot_transition_slice(simulator_fixture):
    # Test transition slice plotting
    fig, ax = simulator_fixture.plot_transition_slice(prev_value=0.0)
    assert fig is not None
    assert ax is not None

def test_summary(simulator_fixture):
    # Test summary generation
    summary = simulator_fixture.summary()
    assert isinstance(summary, pd.DataFrame)
    assert 'Data Points' in summary.Statistic.values
    assert 'Previous Value Range' in summary.Statistic.values
    assert 'Domain Range' in summary.Statistic.values
    assert 'KDE Bandwidth' in summary.Statistic.values
    assert 'Correlation (Previous to Current)' in summary.Statistic.values
