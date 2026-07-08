#%%
import pandas as pd
import numpy as np
from typing import List, Optional, Union

class MarkovChainSimulatorDiscrete:
    """
    A class to simulate Markov chain processes based on transition probabilities
    derived from historical data.
    """
    
    def __init__(self, data: pd.DataFrame):
        """
        Initialize the Markov chain simulator with historical data.
        
        Parameters:
        -----------
        data : pd.DataFrame
            DataFrame containing at least two columns representing previous and current values.
            The column names should be 'previous' and 'current'.
        """
        if 'previous' not in data.columns or 'current' not in data.columns:
            raise ValueError("DataFrame must contain 'previous' and 'current' columns")
            
        self.data = data
        self._build_transition_matrix()
        
    def _build_transition_matrix(self):
        """Build the transition probability matrix from the data."""
        # Get unique states
        self.states = sorted(list(set(self.data['previous'].unique()) | set(self.data['current'].unique())))
        self.state_indices = {state: i for i, state in enumerate(self.states)}
        
        # Create transition matrix
        n_states = len(self.states)
        self.transition_matrix = np.zeros((n_states, n_states))
        
        # Count transitions
        for _, row in self.data.iterrows():
            prev_idx = self.state_indices[row['previous']]
            curr_idx = self.state_indices[row['current']]
            self.transition_matrix[prev_idx, curr_idx] += 1
        
        # Convert counts to probabilities
        row_sums = self.transition_matrix.sum(axis=1)
        # Handle zero rows (states with no outgoing transitions)
        row_sums[row_sums == 0] = 1
        self.transition_matrix = self.transition_matrix / row_sums[:, np.newaxis]
    
    def get_next_state(self, current_state: Union[int, float, str], seed: Optional[int] = None) -> Union[int, float, str]:
        """
        Generate the next state based on the current state.
        
        Parameters:
        -----------
        current_state : int, float, or str
            The current state from which to transition
        seed : int, optional
            Random seed for reproducibility
            
        Returns:
        --------
        The next state according to transition probabilities
        """
        if seed is not None:
            np.random.seed(seed)
            
        if current_state not in self.state_indices:
            raise ValueError(f"State '{current_state}' not found in training data")
            
        current_idx = self.state_indices[current_state]
        probabilities = self.transition_matrix[current_idx]
        
        next_idx = np.random.choice(len(self.states), p=probabilities)
        return self.states[next_idx]
    
    def generate_sequence(self, 
                          start_state: Union[int, float, str], 
                          length: int, 
                          seed: Optional[int] = None) -> List[Union[int, float, str]]:
        """
        Generate a sequence of states starting from the given state.
        
        Parameters:
        -----------
        start_state : int, float, or str
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
    
    def get_transition_probabilities(self, state: Union[int, float, str]) -> pd.Series:
        """
        Get transition probabilities from a specific state to all other states.
        
        Parameters:
        -----------
        state : int, float, or str
            The state for which to get transition probabilities
            
        Returns:
        --------
        pd.Series containing transition probabilities to all possible states
        """
        if state not in self.state_indices:
            raise ValueError(f"State '{state}' not found in training data")
            
        state_idx = self.state_indices[state]
        probabilities = self.transition_matrix[state_idx]
        
        return pd.Series(probabilities, index=self.states, name=f"Transition from {state}")
    
    def summary(self) -> pd.DataFrame:
        """
        Return a summary DataFrame of the transition matrix.
        
        Returns:
        --------
        pd.DataFrame representation of the transition probability matrix
        """
        return pd.DataFrame(
            self.transition_matrix,
            index=self.states,
            columns=self.states
        )


# Example usage
if __name__ == "__main__":
    # Create sample data
    data = pd.DataFrame({
        'previous': [1, 1, 1, 2, 2, 3, 3, 3, 3],
        'current':  [1, 2, 3, 1, 3, 1, 2, 3, 3]
    })
    
    # Initialize the simulator
    simulator = MarkovChainSimulatorDiscrete(data)
    
    # Print transition matrix
    print("Transition Matrix:")
    print(simulator.summary())
    
    # Generate a single next state
    print("\nNext state from state 1 (with seed):", simulator.get_next_state(1, seed=42))
    
    # Generate a sequence
    print("\nSequence starting from state 2:")
    print(simulator.generate_sequence(2, length=10, seed=42))
    
    # Get transition probabilities from state 3
    print("\nTransition probabilities from state 3:")
    print(simulator.get_transition_probabilities(3))
# %%
