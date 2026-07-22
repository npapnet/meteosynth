"""Markov chain simulator using 2D kernel density estimation (KDE).

Simulates a continuous Markov-chain process by fitting a 2D KDE to the joint
probability distribution of ``(previous, current)`` value pairs and sampling
from the resulting conditional distribution ``p(current | previous)``.
"""

# Developer notes / TODO (kept out of the rendered API docs):
#   - CRITICAL (open): NN/CN slices can still produce negative values if the
#     evaluation domain is padded; the domain is currently kept tight to the
#     data (padding=0) to avoid this.
#   - get_conditional_density should expose singularity cases more directly.
#   - PERFORMANCE: move the KDE evaluation into __init__ instead of doing it on
#     every get_next_state call.
#   Done: singular-covariance handling, dict return {domain, pdf, cdf},
#   empirical CDF, common prev/current domain, CN/NC singularity cases.

#%%
import pandas as pd
import numpy as np
from scipy import stats
from scipy import integrate
from typing import List, Optional, Tuple
import matplotlib.pyplot as plt
import logging
from matplotlib.colors import LinearSegmentedColormap

class MarkovChainSimulator2dKDE:
    """
    A class to simulate continuous Markov chain processes using a 2D KDE for
    joint probability distribution between previous and current values.

    Assumptions:
     -  the domain of the data (previous and current) is the common
    """
    singularity_type: Optional[str] = None  # type of singularity (CC, CN, NC, NN)

    def __init__(self, data: pd.DataFrame, bandwidth: Optional[float] = None):
        """
        Initialize the continuous Markov chain simulator with historical data.
        
        Parameters:
        -----------
        data : pd.DataFrame
            DataFrame containing 'previous' and 'current' columns with float values.
        bandwidth : float or str, optional
            Bandwidth for kernel density estimation. If None, Scott's rule is used.
        """
        if 'previous' not in data.columns or 'current' not in data.columns:
            raise ValueError("DataFrame must contain 'previous' and 'current' columns")
            
        self.data = data
        self.bandwidth = bandwidth

        # Default so that non-NN singularity types (CN/NC/CC) still expose a
        # ``joint_kde`` attribute (only the NN case builds a real 2D KDE).
        self.joint_kde = None

        # Extract array of values
        self.previous_values:np.array = data['previous'].values
        self.current_values:np.array = data['current'].values

        self._cat_singularity()
        

        
    def _build_joint_distribution(self):
        """Build 2D joint kernel density estimation."""
        # Stack previous and current values
        values = np.vstack([self.previous_values, self.current_values])
        
        try:
            # Create 2D KDE
            self.joint_kde = stats.gaussian_kde(values, bw_method=self.bandwidth)
        except np.linalg.LinAlgError as e:
            # Handle the case where the covariance matrix is singular.
            # This case happens where there is no variation in the data 
            # (e.g. in the case of a PV plant when measuring sun direct irradiance at night time)
            self.joint_kde = None
            logging.info("KDE failed due to singular covariance matrix. %s", e)

    def _cat_singularity(self):
        """
        Categorise the singularity type using two-letter directional codes.

        Codes (first letter ⇒ previous values, second ⇒ current values):
            • "CC" – constant  → constant
            • "CN" – constant  → non-constant
            • "NC" – non-constant → constant
            • "NN" – non-constant → non-constant
        """
        std_prev = np.std(self.previous_values)
        std_curr = np.std(self.current_values)

        if std_prev == 0 and std_curr == 0:
            self.singularity_type = "CC"
        elif std_prev == 0 and std_curr > 0:
            self.singularity_type = "CN"
            self._cdf_table = self.calculate_next_state_cdf(bandwidth=self.bandwidth)
        elif std_prev > 0 and std_curr == 0:
            self.singularity_type = "NC"
        else:
            self.singularity_type = "NN"
            # Build the 2D joint distribution
            self._build_joint_distribution()

        return self.singularity_type  # adjust if you prefer a different return value

    @staticmethod
    def _calculate_1d_kde_distribution(values, bandwidth=None, num_points=1000)->pd.DataFrame:
        """
        Calculate kernel density estimation distribution for a set of values.
        
        Args:
            values (array-like): Values to calculate KDE for
            bandwidth (float, optional): Bandwidth for KDE. Defaults to None (uses Scott's rule).
            num_points (int, optional): Number of points for evaluation. Defaults to 1000.
            
        Returns:
            tuple: (evaluation_points, pdf_values, cdf_values)
        """
        # Ensure inputs are numpy arrays
        values = np.asarray(values)
        
        # Calculate the kernel density estimation (KDE)
        kde = stats.gaussian_kde(values, bw_method=bandwidth)
        
        # Create a range slightly wider than the data for evaluating the PDF and CDF
        min_val = values.min() - 0.1 * (values.max() - values.min())
        max_val = values.max() + 0.1 * (values.max() - values.min())
        eval_points = np.linspace(min_val, max_val, num_points)
        
        # Calculate the PDF
        pdf_values = kde(eval_points)

        # Calculate the CDF using cumulative integration
        cdf = np.zeros_like(eval_points)
        trapz_func = getattr(integrate, 'trapezoid', getattr(integrate, 'trapz', None))
        if trapz_func is None:
            raise AttributeError("scipy.integrate does not have trapz or trapezoid attribute")
            
        for i in range(1, len(eval_points)):
            cdf[i] = cdf[i-1] + trapz_func(pdf_values[i-1:i+1], eval_points[i-1:i+1])
        
        # Normalize CDF to ensure it ends at 1.0
        cdf = cdf / cdf[-1]
        
        return pd.DataFrame({'x':eval_points, 'pdf':pdf_values, 'cdf':cdf})

    def calculate_next_state_cdf(self, bandwidth:float=None, update_bandwidth:bool = True) -> pd.DataFrame:
        """_summary_

        Args:
            bandwidth (float, optional): _description_. Defaults to None.

        Returns:
            pd.DataFrame: _description_
        """
        if update_bandwidth:
            self.bandwidth = bandwidth 
        df_cdf =  MarkovChainSimulator2dKDE._calculate_1d_kde_distribution(values=self.current_values, 
                                                                           bandwidth=bandwidth)
        return df_cdf

    def _get_x_domain(self, resolution: int = 1000, padding:float=0.0) -> np.ndarray:
        """
        Get the domain of x values for the current value based on the data range.
        
        Parameters:
        -----------
        resolution : int
            Number of points to evaluate
        padding : float
            Padding to extend the domain range (default is 0.0, no padding)
        
        Returns:
        --------
        np.ndarray: Array of x values (current values) for the KDE evaluation.
        """
        dom_min, dom_max, dom_range = self._calc_domain()
        return np.linspace(dom_min - padding*dom_range, 
                           dom_max + padding*dom_range, 
                           resolution)
    
    
    def _calc_domain(self, previous=None, current=None):
        """Function that calculates the data range based on the data

        This is primarily used by plotting functions to determine the domain.
        """
        if previous is None:
            previous = self.previous_values
        
        if current is None:
            current = self.current_values

        dom_min = min(previous.min(), current.min())
        dom_max = max(previous.max(), current.max())
        dom_range = dom_max - dom_min
        return dom_min, dom_max, dom_range

    def get_conditional_density(self, prev_value: float, resolution: int = 1000) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get the conditional probability density function for a given previous value.
        
        Parameters:
        -----------
        x_values : np.ndarray
            Array of the x domain values to evaluate the conditional density
        prev_value : float
            The previous value to condition on
        resolution : int
            Number of points to evaluate the conditional density
            
        Returns:
        --------
        Tuple containing:
            - points: Array of current values
            - density: Conditional probability density at each point
        """
        
        x_values = self._get_x_domain(resolution)

        return self.get_conditional_density_gen(prev_value, x_values)


    def get_conditional_density_gen(self, prev_value: float, x_values:np.array=None) -> Tuple[np.ndarray, np.ndarray]:
        """
        Generate the conditional probability density function given a previous value.

        This method creates a conditional probability density function
        ``p(current|previous)`` by evaluating the joint density of the previous
        and current values, then normalizing.

        Parameters
        ----------
        prev_value : float
            The previous value to condition on.
        x_values : np.array, optional
            Array of x values at which to evaluate the conditional density.
            If None, a default grid will be created based on the domain.

        Returns
        -------
        Tuple[np.ndarray, np.ndarray]
            A tuple containing:

            - Array of x values
            - Corresponding conditional density values

        Notes
        -----
        The conditional density is calculated as
        ``p(current|previous) = p(previous, current) / p(previous)``.
        If the joint KDE is not available (typically when there is no variation
        in the data), a fallback singularity joint density will be used.
        """
        
        if x_values is None:
            # Create grid of points to evaluate
            x_values = self._get_x_domain(resolution=1000)
        
        dom_min, dom_max, dom_range = self._calc_domain(previous=x_values, current=x_values)
        resolution = len(x_values)

        # Create grid points combining fixed previous value with all current values
        grid_points = np.vstack([np.full_like(x_values, prev_value), x_values])
        
        # Evaluate joint density at these points
        if self.joint_kde is not None:
            joint_density = self.joint_kde(grid_points)
            singularity, singl_value_0,singl_value_1= False, None,None
        else:
            #  This is a fallback if KDE is there is no variation in the data
            self._calc_domain(previous=x_values, current=x_values)
            joint_density = None
            singularity = True
            singl_value_0 = self.previous_values.mean()
            singl_value_1 = self.current_values.mean()
                
        # Normalize to get conditional density
        # p(current|previous) = p(previous,current) / p(previous)
        # We can skip computing p(previous) since we'll normalize the density anyway
        conditional_density = joint_density / np.sum(joint_density)
        conditional_density *= resolution / dom_range  # Scale by range
        
        # TODO: Add empirical CDF to the output
        cdf = np.cumsum(conditional_density)
        cdf /= cdf[-1]

        return {"domain":x_values, 
                "pdf":conditional_density, 
                "cdf":cdf,
                "singularity":singularity, 
                "singul_vals": (singl_value_0, singl_value_1)}
    


    def get_next_state(self, current_state: float, seed: Optional[int] = None) -> float:
        """
        Dispatch to the appropriate transition routine, depending on the
        previously-computed singularity code held in ``self.singularity_type``.
        
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
        
        # --- Python ≥ 3.10: match-case “switch” -------------------------------
        match self.singularity_type:
            case "NN":
                return self._get_next_state_NN(current_state, seed=seed)
            case "CN":
                return self._get_next_state_CN(current_state, seed=seed)
            case "NC"|"CC":
                return self._get_next_state_CC(current_state, seed=seed)
            case _:
                raise ValueError(f"Unknown singularity_type: {self.singularity_type!r}")

    def generate_sequence(self,
                          start_state: float,
                          length: int,
                          seed: Optional[int] = None) -> List[float]:
        """
        Generate a Markov sequence of states starting from ``start_state``.

        The seed (if given) is applied once, at the start of the sequence, so
        the whole trajectory is reproducible while remaining stochastic from
        step to step.

        Parameters
        ----------
        start_state : float
            The initial state of the sequence.
        length : int
            Number of transitions to simulate. The returned list has
            ``length + 1`` elements (the start state plus each transition).
        seed : int, optional
            Random seed for reproducibility of the whole sequence.

        Returns
        -------
        List[float]
            The generated sequence, including ``start_state`` as the first item.
        """
        if seed is not None:
            np.random.seed(seed)

        sequence = [start_state]
        current_state = start_state
        for _ in range(length):
            # Do not forward the seed here, otherwise every step would reseed
            # to the same value and produce an identical draw each time.
            current_state = self.get_next_state(current_state)
            sequence.append(current_state)
        return sequence

    def _get_next_state_NN(self, current_state: float, seed: Optional[int] = None) -> float:
        """Generate the next state for non-constant previous and current values.

        Args:
            current_state (float): _description_
            seed (Optional[int], optional): _description_. Defaults to None.

        Returns:
            float: _description_
        """
                
        # Get conditional distribution
        res_dict = self.get_conditional_density(current_state)
        curr_values, conditional_density, cdf = res_dict['domain'], res_dict['pdf'], res_dict['cdf']
        
        # Generate random value and find corresponding point in CDF
        random_value = np.random.random()

        # Use inverse transform sampling to get samples from the distribution
        sample = np.interp(random_value, cdf, curr_values)
        return sample
    


    def _get_next_state_CN(self, current_state:float, seed:Optional[int] = None, bandwidth:float= None) -> float:
        """Generate the next state for constant previous and non-constant current values.

        Samples from a continuous distribution defined by values and their PDF.

        Args:
            current_state (float): starting point for the next state (obsolete for this case). 
                                   This is kept only for consistency with the other methods.
            seed (Optional[int], optional): _description_. Defaults to None.

        Returns:
            float: _description_
        """
        # in this case, the markov chain only uses the current value to generate the next state. 
        # So the idea is to create a cdf of the current values and sample from it.
        # calculate the pdf of the current values

        # Set random seed if provided
        if seed is not None:
            np.random.seed(seed)

        if bandwidth is not None:
            # update the cdf with the new bandwidth
            self._cdf_table  = self.calculate_next_state_cdf(bandwidth=bandwidth)
        
        # Generate uniform random numbers
        uniform_sample = np.random.random()
        
        # Use inverse transform sampling to get samples from the distribution
        samples = np.interp(uniform_sample, self._cdf_table.cdf.values, self._cdf_table.x.values)
        return samples
    
    
    def _get_next_state_CC(self, current_state: float, seed: Optional[int] = None) -> float:
        """Generate the next state for constant previous and current values.

        Args:
            current_state (float): _description_
            seed (Optional[int], optional): _description_. Defaults to None.

        Returns:
            float: _description_
        """
        # In this case, the next state is always the same independent of the current state
    
        
        # Return the sampled state
        return self.current_values[0]
   
    def plot_joint_distribution(self, resolution: int = 100) -> Tuple[plt.Figure, plt.Axes]:
        """
        Plot the joint distribution of previous and current values.
        
        Parameters:
        -----------
        resolution : int
            Grid resolution for plotting
            
        Returns:
        --------
        fig, ax: Figure and Axes objects
        """
        # Create grid for evaluation
        # x = np.linspace(self.dom_min - 0.1*self.prev_range, self.prev_max + 0.1*self.prev_range, resolution)
        # y = np.linspace(self.curr_min - 0.1*self.curr_range, self.curr_max + 0.1*self.curr_range, resolution)
        x = self._get_x_domain(resolution)
        y = self._get_x_domain(resolution)
        X, Y = np.meshgrid(x, y)
        
        dom_min, dom_max, dom_range = self._calc_domain(previous=x, current=y)

        # Reshape for KDE evaluation
        positions = np.vstack([X.ravel(), Y.ravel()])
        
        # Evaluate density
        if self.joint_kde is None:
            # this is a fallback if thre is no variation in the data
            logging.info("KDE is not available. Cannot plot joint distribution.")
            return None, None
        
        Z = self.joint_kde(positions)
        Z = Z.reshape(X.shape)
        
        # Create plot
        fig, ax = plt.subplots(figsize=(10, 8))
        
        # Custom colormap - from white to blue
        colors = [(1, 1, 1), (0, 0, 0.8)]
        cmap = LinearSegmentedColormap.from_list('WhiteBlue', colors, N=100)
        
        # Plot contour
        contour = ax.contourf(X, Y, Z, cmap=cmap, levels=50)
       
        # Add colorbar
        plt.colorbar(contour, ax=ax, label='Density')

        # Plot scatter of original data points
        ax.scatter(self.previous_values, self.current_values,
                 c='r', alpha=0.1, s=5, label='Data Points')

        # Plot the identity line y=x
        min_val = dom_min
        max_val = dom_max
        ax.plot([min_val, max_val], [min_val, max_val], 'k--', alpha=0.5, label='y=x')
        
        # Labels and title
        ax.set_xlabel('Previous Value')
        ax.set_ylabel('Current Value')
        ax.set_title('Joint Distribution of Previous and Current Values')
        ax.legend()
        
        return fig, ax
    
    def plot_conditional_densities(self, 
                                  prev_values: List[float], 
                                  resolution: int = 1000) -> Tuple[plt.Figure, plt.Axes]:
        """
        Plot conditional probability densities for multiple previous values.
        
        Parameters:
        -----------
        prev_values : List[float]
            List of previous values to show conditional distributions for
        resolution : int
            Number of points to evaluate each conditional density
            
        Returns:
        --------
        fig, ax: Figure and Axes objects
        """
        fig, ax = plt.subplots(figsize=(12, 8))
        
        for prev_value in prev_values:
            # Get conditional density
            res_dict = self.get_conditional_density(prev_value, resolution)

            curr_values, density, cdf = res_dict['domain'], res_dict['pdf'], res_dict['cdf']
            
            # Plot density
            ax.plot(curr_values, density, label=f'Previous = {prev_value:.2f}')
            
        # Labels and title
        ax.set_xlabel('Next Value')
        ax.set_ylabel('Conditional Probability Density')
        ax.set_title('Conditional Probability Distributions')
        ax.legend()
        
        return fig, ax
    
    def plot_transition_slice(self, 
                             prev_value: float,
                             resolution: int = 100) -> Tuple[plt.Figure, plt.Axes]:
        """
        Visualize a slice through the joint distribution at a specific previous value.
        
        Parameters:
        -----------
        prev_value : float
            The previous value to slice at
        resolution : int
            Grid resolution for plotting
            
        Returns:
        --------
        fig, ax: Figure and Axes objects
        """
        # Create the joint distribution plot
        fig, ax = self.plot_joint_distribution(resolution)
        
        # Add a vertical line for the slice
        ax.axvline(x=prev_value, color='g', linestyle='-', linewidth=2, 
                  label=f'Slice at Previous = {prev_value:.2f}')
        
        # Get conditional density for this value
        res_dict = self.get_conditional_density(prev_value)
        curr_values, density, cdf = res_dict['domain'], res_dict['pdf'], res_dict['cdf']

        # Create inset plot for the conditional density
        ax_inset = fig.add_axes([0.2, 0.6, 0.35, 0.25])
        ax_inset.plot(curr_values, density, 'g-')
        ax_inset.set_title(f'Conditional Density at Previous = {prev_value:.2f}')
        ax_inset.set_xlabel('Next Value')
        ax_inset.set_ylabel('Density')
        
        # Update main plot legend
        ax.legend()
        
        return fig, ax
    
    def summary(self) -> pd.DataFrame:
        """
        Return a summary DataFrame of the model.
        
        Returns:
        --------
        pd.DataFrame with statistics about the data and model
        """
        dom_min, dom_max, dom_range = self._calc_domain()
        # Calculate statistics
        stats_dict = {
            'Data Points': len(self.data),
            'Previous Value Range': f"{self.previous_values.min():.4f} to {self.previous_values.max():.4f}",
            'Current Value Range': f"{self.current_values.min():.4f} to {self.current_values.max():.4f}",
            'Domain Range': f"{dom_min:.4f} to {dom_max:.4f}",	
            'KDE Bandwidth': self.joint_kde.factor if self.bandwidth is None else self.bandwidth
        }
        
        # Create correlation statistics
        corr = np.corrcoef(self.previous_values, self.current_values)[0, 1]
        stats_dict['Correlation (Previous to Current)'] = f"{corr:.4f}"
        
        # Convert to DataFrame
        return pd.DataFrame(list(stats_dict.items()), columns=['Statistic', 'Value'])


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
    simulator = MarkovChainSimulator2dKDE(data)
    
    # Print summary
    print("Model Summary:")
    print(simulator.summary())
    
    # Generate a single next state
    start_value = 7.0
    print(f"\nNext state from {start_value} (with seed):", simulator.get_next_state(start_value, seed=42))
    
    # Generate a sequence
    print(f"\nSequence starting from {start_value}:")
    sequence = simulator.generate_sequence(start_value, length=5, seed=42)
    print(sequence)
    
    # Plot joint distribution
    plt.figure(1)
    simulator.plot_joint_distribution()
    plt.tight_layout()
    
    # Plot conditional densities for several points
    plt.figure(2)
    simulator.plot_conditional_densities([2.0, 5.0, 8.0])
    plt.tight_layout()
    
    # Plot a transition slice
    plt.figure(3)
    simulator.plot_transition_slice(7.0)
    plt.tight_layout()
    
    plt.show()
