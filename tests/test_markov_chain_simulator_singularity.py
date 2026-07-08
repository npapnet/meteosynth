
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde
import pytest
from meteosynth.markov_chain_simulator_kde2d import MarkovChainSimulator2dKDE


@pytest.fixture
def simulator_fixtureCC():
    # Create sample data for testing
    # Test joint distribution calculation with trivial case
    data = pd.DataFrame({'previous': np.zeros(20), 'current': np.zeros(20)})
    return MarkovChainSimulator2dKDE(data)


def test_get_joint_singularity_CC():
    cur_val = 3.0
    data = pd.DataFrame({'previous': np.zeros(20), 'current': cur_val*np.ones(20)})
    simulator_fixtureCC =  MarkovChainSimulator2dKDE(data)
    x_l,x_r, x_n = -3.,3.,101

    xvalues_rng = np.linspace(x_l, x_r, x_n)
    next_state = simulator_fixtureCC.get_next_state(current_state=0, seed=42)

    assert next_state == cur_val


@pytest.mark.parametrize("current_state, expected_next_state", [
    (0.0, 1.0),
    (1.0, 1.0),
    (0.5, 1.0),
    (-1.0, 1.0),
])
def test_get_joint_singularity_NC(current_state, expected_next_state):
    """Test with a singularity when the xvalues don't fall exactly on the value of interest.
    
    Tests different starting states, all of which should lead to 0.0 since all 'current' values in data are 0.
    """
    curr_value = 3
    data = pd.DataFrame({'previous': np.random.random(size=20), 'current': curr_value*np.ones(20)})
    simulator_fixtureNC = MarkovChainSimulator2dKDE(data)
    
    assert simulator_fixtureNC.singularity_type == 'NC', "Expected singularity type to be 'NC'"

    x_l, x_r, x_n = -2.95, 3.05, 101
    xvalues_rng = np.linspace(x_l, x_r, x_n)
    
    next_state = simulator_fixtureNC.get_next_state(current_state=current_state, seed=42)
    assert next_state == expected_next_state *curr_value



