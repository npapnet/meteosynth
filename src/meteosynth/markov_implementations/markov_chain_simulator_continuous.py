#%%
import pandas as pd
import numpy as np
from scipy import stats
from typing import List, Optional, Union, Tuple
import matplotlib.pyplot as plt

class ContinuousMarkovChainSimulator:
    """
    A class to simulate Markov chain processes with continuous (float) state values
    using kernel density estimation for transition modeling.
    """
    
    def __init__(self, data: pd.DataFrame, bandwidth: Optional[float] = None):
        """
        Initialize the continuous Markov chain simulator with historical data.
        
        Parameters:
        -----------
        data : pd.DataFrame
            DataFrame containing 'previous' and 'current' columns with float values.
        bandwidth : float, optional
            Bandwidth for kernel density estimation. If None, Scott's rule is used.
        """
        if 'previous' not in data.columns or 'current' not in data.columns:
            raise ValueError("DataFrame must contain 'previous' and 'current' columns")
            
        self.data = data
        self.bandwidth = bandwidth
        
        # Create conditional KDE models for transitions
        self._build_transition_models()
        
    def _build_transition_models(self):
        """Build transition models based on conditional kernel density estimation."""
        # Group data by previous value (rounded to improve estimation)
        self.precision = 2  # Decimal places for grouping
        self.data['prev_group'] = np.round(self.data['previous'], self.precision)
        
        # Get unique groups
        self.unique_groups = self.data['prev_group'].unique()
        
        # Dictionary to store KDE models for each group
        self.kde_models = {}
        
        for group in self.unique_groups:
            group_data = self.data[self.data['prev_group'] == group]['current'].values.reshape(-1, 1)
            if len(group_data) > 1:  # Need at least 2 points for KDE
                self.kde_models[group] = stats.gaussian_kde(group_data.T, bw_method=self.bandwidth)
            else:
                # If only one transition exists, use it deterministically
                self.kde_models[group] = group_data[0][0]
    
    def _find_nearest_group(self, value: float) -> float:
        """Find the nearest group to a value."""
        rounded = np.round(value, self.precision)
        if rounded in self.unique_groups:
            return rounded
        
        # Find nearest available group
        nearest_idx = np.abs(self.unique_groups - rounded).argmin()
        return self.unique_groups[nearest_idx]
    
    def _get_conditional_distribution(self, previous_value: float) -> Union[stats.gaussian_kde, float]:
        """Get the conditional distribution for a given previous value."""
        nearest_group = self._find_nearest_group(previous_value)
        return self.kde_models[nearest_group]
    
    def get_next_state(self, current_state: float, seed: Optional[int] = None) -> float:
        """
        Generate the next state based on the current state using conditional density.
        
        Parameters:
        -----------
        current_state : float
            The current state from which to transition
        seed : int, optional
            Random seed for reproducibility
            
        Returns:
        --------
        float: The next state sampled from the conditional distribution
        """
        if seed is not None:
            np.random.seed(seed)
        
        conditional_dist = self._get_conditional_distribution(current_state)
        
        # Handle deterministic case (when a group has only one sample)
        if isinstance(conditional_dist, (int, float)):
            return float(conditional_dist)
        
        # Sample from the conditional distribution
        return float(conditional_dist.resample(1)[0][0])
    
    def generate_sequence(self, 
                          start_state: float, 
                          length: int, 
                          seed: Optional[int] = None) -> List[float]:
        """
        Generate a sequence of states starting from the given state.
        
        Parameters:
        -----------
        start_state : float
            The starting state for the sequence
        length : int
            The number of transitions to simulate (resulting sequence will be length+1)
        seed : int, optional
            Random seed for reproducibility
            
        Returns:
        --------
        List of states including the start state and subsequent transitions
        """
        if seed is not None:
            np.random.seed(seed)
            
        sequence = [start_state]
        current_state = start_state
        
        for _ in range(length):
            current_state = self.get_next_state(current_state)
            sequence.append(current_state)
            
        return sequence
    
    def plot_transition_density(self, 
                               from_value: float, 
                               points: int = 1000, 
                               range_padding: float = 1.0) -> Tuple[plt.Figure, plt.Axes]:
        """
        Plot the transition probability density function for a given state.
        
        Parameters:
        -----------
        from_value : float
            The starting state
        points : int
            Number of points to evaluate the density function
        range_padding : float
            Factor to extend the range of the plot beyond observed data
            
        Returns:
        --------
        fig, ax: Figure and Axes objects
        """
        conditional_dist = self._get_conditional_distribution(from_value)
        
        # Handle deterministic case
        if isinstance(conditional_dist, (int, float)):
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.axvline(x=conditional_dist, color='r')
            ax.set_title(f"Transition from state {from_value} (deterministic)")
            ax.set_xlabel("Next state")
            ax.set_ylabel("Probability Density")
            return fig, ax
        
        # Get the range of the data
        data_min = self.data['current'].min()
        data_max = self.data['current'].max()
        range_width = data_max - data_min
        
        # Extend the range by padding
        x_min = data_min - range_width * range_padding
        x_max = data_max + range_width * range_padding
        
        # Create evaluation points
        x = np.linspace(x_min, x_max, points)
        
        # Evaluate the density
        density = conditional_dist.evaluate(x)
        
        # Create the plot
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(x, density)
        ax.fill_between(x, density, alpha=0.3)
        ax.set_title(f"Transition density from state {from_value}")
        ax.set_xlabel("Next state")
        ax.set_ylabel("Probability Density")
        
        return fig, ax
    
    def plot_sample_transitions(self, 
                              from_values: List[float], 
                              n_samples: int = 1000) -> Tuple[plt.Figure, plt.Axes]:
        """
        Plot sample transitions from multiple starting states.
        
        Parameters:
        -----------
        from_values : List[float]
            List of starting states
        n_samples : int
            Number of samples to draw for each starting state
            
        Returns:
        --------
        fig, ax: Figure and Axes objects
        """
        fig, ax = plt.subplots(figsize=(12, 8))
        
        for from_value in from_values:
            samples = []
            for _ in range(n_samples):
                samples.append(self.get_next_state(from_value))
            
            # Plot kernel density of samples
            density = stats.gaussian_kde(samples)
            x = np.linspace(min(samples), max(samples), 1000)
            ax.plot(x, density(x), label=f"From {from_value}")
            
        ax.set_title("Sample transitions from different states")
        ax.set_xlabel("Next state")
        ax.set_ylabel("Probability Density")
        ax.legend()
        
        return fig, ax

    def summary(self) -> pd.DataFrame:
        """
        Return a summary DataFrame of the transition model.
        
        Returns:
        --------
        pd.DataFrame with statistics about transitions from each state group
        """
        summary_data = []
        
        for group in self.unique_groups:
            group_data = self.data[self.data['prev_group'] == group]['current']
            
            # Calculate statistics
            summary_data.append({
                'prev_state': group,
                'count': len(group_data),
                'mean_next': group_data.mean(),
                'std_next': group_data.std(),
                'min_next': group_data.min(),
                'max_next': group_data.max()
            })
        
        return pd.DataFrame(summary_data)


# Example usage
if __name__ == "__main__":
    # Create a sample dataset with continuous values
    np.random.seed(42)
    n_samples = 1000
    
    # Generate data where the next value is related to the previous
    # next = previous * 0.8 + random noise
    prev_values = np.random.uniform(0, 10, n_samples)
    next_values = prev_values * 0.8 + np.random.normal(0, 1, n_samples)

    data = pd.DataFrame({
        'previous': prev_values,
        'current': next_values
    })
    
    # Initialize the simulator
    simulator = ContinuousMarkovChainSimulator(data)
    
    # Print summary
    print("Transition Model Summary:")
    print(simulator.summary())
    
    # Generate a single next state
    start_value = 5.0
    print(f"\nNext state from {start_value} (with seed):", simulator.get_next_state(start_value, seed=42))
    
    # Generate a sequence
    print(f"\nSequence starting from {start_value}:")
    sequence = simulator.generate_sequence(start_value, length=5, seed=42)
    print(sequence)
    
    # Plot transition density from a specific state
    fig, ax = simulator.plot_transition_density(5.0)
    plt.tight_layout()
    plt.show()
    
    # Plot sample transitions from multiple starting states
    fig, ax = simulator.plot_sample_transitions([2.0, 5.0, 8.0])
    plt.tight_layout()
    plt.show()
# %%
