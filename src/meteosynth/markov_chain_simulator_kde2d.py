"""Markov chain simulator using 2D kernel density estimation (KDE).

Simulates a continuous Markov-chain process by fitting a 2D KDE to the joint
probability distribution of ``(previous, current)`` value pairs and sampling
from the resulting conditional distribution ``p(current | previous)``.

Sampling is confined to the physical support declared by a
:class:`~meteosynth.variables.VariableSpec`, so out-of-support values are unsamplable
by construction rather than merely unlikely. See
``docs/design/variable-specs-and-initialisation.md`` section 3.
"""

# Developer notes / TODO (kept out of the rendered API docs):
#   - get_conditional_density should expose singularity cases more directly.
#   - PERFORMANCE: move the KDE evaluation into __init__ instead of doing it on
#     every get_next_state call.
#   Done: singular-covariance handling, dict return {domain, pdf, cdf},
#   empirical CDF, common prev/current domain, CN/NC singularity cases,
#   support truncation (the old CRITICAL about padded domains producing
#   negatives -- the +/-10% padding is gone and the domain is clamped to the
#   spec's support in both the 1D and 2D paths).

#%%
import pandas as pd
import numpy as np
from scipy import stats
from scipy import integrate
from enum import Enum, auto
from typing import List, Optional, Tuple, Union
import matplotlib.pyplot as plt
import logging
from matplotlib.colors import LinearSegmentedColormap

from .variables import VariableSpec


class Kind(Enum):
    """
    What kind of transition the *data* supports -- not what kind of variable it is.

    Degeneracy is empirical: which hours are constant depends on latitude and season,
    so it is detected from the data and cannot be declared in a spec. Irradiance is
    identically zero at night and so degenerates there; wind and temperature never do.

    Replaces the old two-letter ``singularity_type`` codes:

    ============  ==============================================  =========
    ``Kind``      meaning                                         was
    ============  ==============================================  =========
    ``KDE_2D``    previous and current both vary                   ``NN``
    ``KDE_1D``    previous constant, current varies                ``CN``
    ``CONSTANT``  current constant                                 ``NC``, ``CC``
    ============  ==============================================  =========

    ``NC`` and ``CC`` collapse into one: both already dispatched to the same routine
    (return the constant), and the distinction never affected behaviour.
    """

    KDE_2D = auto()
    KDE_1D = auto()
    CONSTANT = auto()


def _as_rng(rng: Union[None, int, np.random.Generator]) -> np.random.Generator:
    """
    Coerce ``None`` / an int seed / a Generator into a Generator.

    Every stochastic path in this package draws from an explicit
    :class:`numpy.random.Generator` rather than the global ``np.random`` state. The old
    code called ``np.random.seed``, which mutates process-wide state as a side effect --
    reproducible, but only by making the whole process reproducible, and impossible to
    thread through an ensemble built from many independent calls.
    """
    if isinstance(rng, np.random.Generator):
        return rng
    return np.random.default_rng(rng)


class MarkovChainSimulator2dKDE:
    """
    A class to simulate continuous Markov chain processes using a 2D KDE for
    joint probability distribution between previous and current values.

    Parameters
    ----------
    data : pd.DataFrame
        DataFrame containing ``previous`` and ``current`` columns of floats.
    bandwidth : float, optional
        Bandwidth for the KDE. ``None`` uses Scott's rule.
    spec : VariableSpec, optional
        Physical constraints of the quantity. When given, the evaluation domain is
        clamped to ``spec.support`` in both sampling paths, making out-of-support
        samples impossible. When ``None`` the domain is the observed range alone,
        which is the old (unconstrained) behaviour.
    """

    #: What the data supports. See :class:`Kind`.
    kind: Optional[Kind] = None

    def __init__(
        self,
        data: pd.DataFrame,
        bandwidth: Optional[float] = None,
        spec: Optional[VariableSpec] = None,
    ):
        if 'previous' not in data.columns or 'current' not in data.columns:
            raise ValueError("DataFrame must contain 'previous' and 'current' columns")

        self.data = data
        self.bandwidth = bandwidth
        self.spec = spec

        # Default so that degenerate kinds still expose a ``joint_kde`` attribute
        # (only KDE_2D builds a real 2D KDE).
        self.joint_kde = None

        # Extract array of values
        self.previous_values:np.array = data['previous'].values
        self.current_values:np.array = data['current'].values

        self._cat_singularity()

    @property
    def is_degenerate(self) -> bool:
        """True when the data does not support a full 2D conditional model."""
        return self.kind is not Kind.KDE_2D

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
        Detect what kind of transition the data supports, and fit accordingly.

        Sets :attr:`kind`. See :class:`Kind` for the categories and the codes they
        replace.
        """
        std_prev = np.std(self.previous_values)
        std_curr = np.std(self.current_values)

        if std_curr == 0:
            # Current is constant: nothing to sample, whatever previous does.
            # This is the old NC and CC collapsed into one.
            self.kind = Kind.CONSTANT
        elif std_prev == 0:
            self.kind = Kind.KDE_1D
            self._cdf_table = self.calculate_next_state_cdf(bandwidth=self.bandwidth)
        else:
            self.kind = Kind.KDE_2D
            # Build the 2D joint distribution
            self._build_joint_distribution()

        return self.kind

    @staticmethod
    def _calculate_1d_kde_distribution(
        values, bandwidth=None, num_points=1000, spec: Optional[VariableSpec] = None
    ) -> pd.DataFrame:
        """
        Calculate a kernel density estimation distribution for a set of values.

        Args:
            values (array-like): Values to calculate KDE for
            bandwidth (float, optional): Bandwidth for KDE. Defaults to None (uses Scott's rule).
            num_points (int, optional): Number of points for evaluation. Defaults to 1000.
            spec (VariableSpec, optional): If given, the evaluation domain is clamped to
                its physical support.

        Returns:
            pd.DataFrame: columns ``x``, ``pdf``, ``cdf``.

        Notes
        -----
        The evaluation domain is the observed range, **not** padded. This used to pad by
        +/-10% on both sides, which is where generated irradiance got its negative
        values: for the dawn hour the padded domain reached -8.10 W/m2 against an
        observed minimum of 0.00, and 30.8% of that hour's samples came out negative.
        Since ``np.interp`` cannot return a value outside the domain it is given,
        removing the padding and clamping to the support makes out-of-support samples
        impossible rather than merely rare.
        """
        # Ensure inputs are numpy arrays
        values = np.asarray(values)

        # Calculate the kernel density estimation (KDE)
        kde = stats.gaussian_kde(values, bw_method=bandwidth)

        # Domain is the observed range, clamped to the physical support. No padding.
        min_val, max_val = float(values.min()), float(values.max())
        if spec is not None:
            min_val, max_val = spec.clamp_domain(min_val, max_val)
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
                                                                           bandwidth=bandwidth,
                                                                           spec=self.spec)
        return df_cdf

    def _get_x_domain(self, resolution: int = 1000, padding:float=0.0) -> np.ndarray:
        """
        Get the domain of x values for the current value based on the data range.

        Clamped to ``self.spec.support`` when a spec is present, so that inverse-transform
        sampling over this domain cannot return an out-of-support value.

        Parameters:
        -----------
        resolution : int
            Number of points to evaluate
        padding : float
            Padding to extend the domain range (default is 0.0, no padding). Applied
            *before* the support clamp, so padding can never push the domain outside the
            physical bounds.

        Returns:
        --------
        np.ndarray: Array of x values (current values) for the KDE evaluation.
        """
        dom_min, dom_max, dom_range = self._calc_domain()
        lo = dom_min - padding * dom_range
        hi = dom_max + padding * dom_range
        if self.spec is not None:
            lo, hi = self.spec.clamp_domain(lo, hi)
        return np.linspace(lo, hi, resolution)
    
    
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

        # Clamp the conditioning value into the range the model was actually fitted
        # over. Far enough outside it, every kernel evaluates to ~0, the joint density
        # sums to zero, and the 0/0 below yields NaN -- which then kills the *next*
        # hour with "array must not contain infs or NaNs". Extrapolating a KDE beyond
        # its data is not meaningful anyway, so the nearest fitted value is both the
        # safest and the most faithful answer.
        #
        # This is reachable in ordinary use: in a rolling series, day d's 23:00 value
        # comes from day d's window fit while day d+1's cross-midnight model is fitted
        # on a different (overlapping) sample, so the conditioning value can land just
        # outside. See tests/test_window_boundary_continuity.py.
        prev_value = float(
            np.clip(prev_value, self.previous_values.min(), self.previous_values.max())
        )

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
        total = np.sum(joint_density)
        if not np.isfinite(total) or total <= 0:
            # Belt and braces: clamping should make this unreachable, but a NaN escaping
            # here corrupts the rest of the day silently, so fall back to the marginal
            # of ``current`` -- the honest answer when conditioning carries no
            # information -- rather than propagating it.
            logging.warning(
                "joint density vanished at previous=%.6g; falling back to the marginal "
                "of `current`. This suggests the conditioning value is far outside the "
                "fitted range.", prev_value,
            )
            joint_density = np.histogram(
                self.current_values, bins=len(x_values),
                range=(float(x_values[0]), float(x_values[-1])),
            )[0].astype(float)
            total = np.sum(joint_density)
            if total <= 0:
                joint_density = np.ones_like(x_values, dtype=float)
                total = float(len(x_values))

        conditional_density = joint_density / total
        conditional_density *= resolution / dom_range  # Scale by range
        
        # TODO: Add empirical CDF to the output
        cdf = np.cumsum(conditional_density)
        cdf /= cdf[-1]

        return {"domain":x_values, 
                "pdf":conditional_density, 
                "cdf":cdf,
                "singularity":singularity, 
                "singul_vals": (singl_value_0, singl_value_1)}
    


    def get_next_state(
        self,
        current_state: float,
        rng: Union[None, int, np.random.Generator] = None,
    ) -> float:
        """
        Sample the next state, dispatching on :attr:`kind`.

        Parameters
        ----------
        current_state : float
            The current state from which to transition. Ignored when
            :attr:`kind` is not :attr:`Kind.KDE_2D` -- a 1D or constant model has
            nothing to condition on.
        rng : None, int or np.random.Generator, optional
            Source of randomness. An int is treated as a seed for a fresh generator;
            ``None`` draws from a fresh unseeded one. Pass a ``Generator`` to draw
            successive values from one stream, which is what the chain walkers do.

        Returns
        -------
        float
            The next state, guaranteed inside ``self.spec.support`` when a spec is set.
        """
        rng = _as_rng(rng)

        match self.kind:
            case Kind.KDE_2D:
                return self._get_next_state_kde2d(current_state, rng)
            case Kind.KDE_1D:
                return self._get_next_state_kde1d(rng)
            case Kind.CONSTANT:
                return self._get_next_state_constant()
            case _:
                raise ValueError(f"Unknown kind: {self.kind!r}")

    def generate_sequence(self,
                          start_state: float,
                          length: int,
                          rng: Union[None, int, np.random.Generator] = None) -> List[float]:
        """
        Generate a Markov sequence of states starting from ``start_state``.

        Parameters
        ----------
        start_state : float
            The initial state of the sequence.
        length : int
            Number of transitions to simulate. The returned list has
            ``length + 1`` elements (the start state plus each transition).
        rng : None, int or np.random.Generator, optional
            Source of randomness, resolved once so the whole trajectory is
            reproducible while remaining stochastic from step to step.

        Returns
        -------
        List[float]
            The generated sequence, including ``start_state`` as the first item.
        """
        rng = _as_rng(rng)

        sequence = [start_state]
        current_state = start_state
        for _ in range(length):
            # Draw from the one stream: re-resolving per step would restart it and
            # produce an identical draw every time.
            current_state = self.get_next_state(current_state, rng=rng)
            sequence.append(current_state)
        return sequence

    def _get_next_state_kde2d(self, current_state: float, rng: np.random.Generator) -> float:
        """Sample from ``p(current | previous=current_state)`` via the 2D KDE.

        Slices the joint density vertically at ``current_state`` and inverse-transform
        samples the resulting 1D conditional.
        """
        res_dict = self.get_conditional_density(current_state)
        curr_values, cdf = res_dict['domain'], res_dict['cdf']

        return float(np.interp(rng.random(), cdf, curr_values))

    def _get_next_state_kde1d(self, rng: np.random.Generator) -> float:
        """Sample from the marginal of ``current``, ignoring the previous value.

        Used when ``previous`` is constant: there is no information in it to condition
        on, so the transition reduces to a draw from the current hour's own
        distribution.
        """
        return float(
            np.interp(rng.random(), self._cdf_table.cdf.values, self._cdf_table.x.values)
        )

    def _get_next_state_constant(self) -> float:
        """Return the constant value that ``current`` always takes.

        Deterministic, so it consumes no randomness -- which is why the walkers can
        share one generator across degenerate and non-degenerate hours without the
        degenerate ones perturbing the stream.
        """
        return float(self.current_values[0])
   
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
    demo_rng = np.random.default_rng(42)
    n_samples = 1000

    # Generate data where the next value is related to the previous
    # next = previous * 0.8 + random noise
    prev_values = demo_rng.uniform(0, 10, n_samples)
    next_values = prev_values * 0.8 + demo_rng.normal(0, 1, n_samples)
    
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
    start_state = 7.0
    print(f"\nNext state from {start_state} (with seed):", simulator.get_next_state(start_state, rng=42))

    # Generate a sequence
    print(f"\nSequence starting from {start_state}:")
    sequence = simulator.generate_sequence(start_state, length=5, rng=42)
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
