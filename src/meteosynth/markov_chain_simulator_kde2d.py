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
#   Done: the KDE evaluation is cached for hot simulators (see _build_quantile_grid
#   and docs/design/precomputed-conditional-quantiles.md),
#   singular-covariance handling, dict return {domain, pdf, cdf},
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

    "Constant" means constant *to within tolerance* -- see :data:`_DEGENERACY_RTOL`. A
    physically-zero night stored as ``1e-16`` is constant, whatever an exact comparison
    against zero would say.
    """

    KDE_2D = auto()
    KDE_1D = auto()
    CONSTANT = auto()


#: Relative tolerance for calling a slice constant.
#:
#: Degeneracy used to be an **exact** ``np.std(...) == 0`` test, which worked only
#: because PVGIS happens to store literal zeros at night. Any source that stores a
#: physically-zero night as ``1e-16`` -- interpolation, resampling, unit conversion, or a
#: provider that keeps near-zero noise -- fell through to the 2D branch instead, and a 2D
#: KDE was then fitted across a ``previous`` spanning ~50 and a ``current`` spanning
#: ~1e-14. That covariance is catastrophically ill-conditioned, which is the failure this
#: tolerance exists to prevent.
#:
#: The comparison is against the scale of *this simulator's own data*, not against the
#: slice being tested. A night slice's spread is large relative to itself -- values of
#: ~1e-14 vary by ~1e-14 -- so a purely relative test would still call it varying. What
#: makes it degenerate is that it is negligible next to the other axis, and that
#: disparity is precisely what conditions the covariance badly.
#:
#: 1e-9 sits far below any real meteorological signal (irradiance resolved to 1e-6 W/m2
#: against a 800 W/m2 day) and far above float64 residue from a trigonometric identity.
_DEGENERACY_RTOL = 1e-9


#: Nodes along the ``previous`` axis of the cached conditional-quantile grid.
#:
#: 64 uniform nodes. Measured on 21 March, Heraklion 2005-2023, +/-7 days at
#: ``bandwidth=0.1``: against the direct path over 20 000 draws, the cached sampler is
#: within **0.03 % on the mean** and **0.31 % on the standard deviation** at three
#: different hours. 32 nodes is within 0.04 % / 0.42 %, 16 within 0.13 % / 1.2 %.
#:
#: Spacing is deliberately **uniform, not quantile-based**. Quantile spacing was measured
#: and is worse at every node count -- irradiance's ``previous`` piles up near zero at
#: night, so quantile nodes cluster there and starve the daytime range where the chain
#: actually moves (at 16 nodes: -11.9 % on the sd against -1.2 % for uniform).
_CDF_GRID_NODES = 64

#: Calls to one simulator's 2D path before its quantile grid is built.
#:
#: Building the grid costs one KDE evaluation over ``_CDF_GRID_NODES`` x 1000 points,
#: which is ``_CDF_GRID_NODES`` direct calls' worth of work -- so a simulator asked for
#: fewer samples than this must not pay for it. Setting the threshold equal to the node
#: count bounds the worst case at **2x** the direct cost (a simulator asked for exactly
#: 2 x 64 samples), while a simulator asked for 1000 runs about **8x** faster.
#:
#: This is what keeps :meth:`~meteosynth.generators.DayWindowGenerator.generate_series`
#: unaffected: a year-long walk fits each day's generator, takes **one** sample from each
#: of its 24 hourly simulators, and moves on. None of them ever reaches the threshold, so
#: none of them builds a grid and none of them spends the memory.
_GRID_ACTIVATION_CALLS = 64

#: Quantile levels at which the cached inverse CDF is stored.
_GRID_QUANTILE_LEVELS = 1001

#: The three ways a draw can be answered, named so a caller can **say which** rather than
#: discover it from call history (``FEAT-17``).
#:
#: ``"exact"``
#:     Evaluate the conditional density live, every time. No grid is ever built -- not
#:     lazily, not eagerly. Deterministic and auditable: a number came from the density and
#:     will again next run. ~13x slower than ``"grid"`` for a large ensemble.
#: ``"grid"``
#:     Build the cached quantile grid up front and draw from it throughout. Right when many
#:     draws are coming; a pessimisation when few are (a chained year takes one draw per
#:     simulator, so building grids would cost ~9x more than it saves).
#: ``"auto"``
#:     Decide from whatever is known, **once, before any drawing starts**. Callers that know
#:     their draw count -- an ensemble knows ``n_realisations`` -- resolve to ``"exact"`` or
#:     ``"grid"`` up front and never switch. Only a caller that knows nothing, such as a
#:     bare ``gen_day`` loop, falls back to :data:`_GRID_ACTIVATION_CALLS` and switches
#:     part-way, which is then a stated choice rather than a hidden one.
#:
#: **"Exact" means no grid, not no approximation.** The live path still discretises the
#: value axis and integrates by cumulative sum; the grid adds interpolation across
#: :data:`_CDF_GRID_NODES` nodes and a quantile axis of :data:`_GRID_QUANTILE_LEVELS` on
#: top of that. Measured, the grid's extra error is 0.03 % on the mean and 0.04-0.31 % on
#: the standard deviation -- ~100x below what this repo can resolve. **The choice is
#: about determinism, not accuracy.**
SAMPLING_PATHS = ("auto", "exact", "grid")

#: What ``"auto"`` resolves to when the caller knows nothing at all.
_DEFAULT_SAMPLING = "auto"


def resolve_sampling(sampling: str, n_expected_draws: Optional[int] = None) -> str:
    """
    Turn a requested path and a known draw count into the path that will actually run.

    Parameters
    ----------
    sampling : {"auto", "exact", "grid"}
        What the caller asked for.
    n_expected_draws : int, optional
        How many draws each simulator will see, when the caller knows. ``None`` means
        genuinely unknown -- not zero.

    Returns
    -------
    str
        ``"auto"``, ``"exact"`` or ``"grid"``. ``"auto"`` is returned only when the count
        is unknown, and means *"let the counter advise"*.

    Raises
    ------
    ValueError
        For an unknown path. Failing here rather than silently defaulting is the point:
        a typo in a sampling mode must not quietly change what a result was drawn from.

    Examples
    --------
    >>> resolve_sampling("auto", n_expected_draws=1000)
    'grid'
    >>> resolve_sampling("auto", n_expected_draws=1)
    'exact'
    >>> resolve_sampling("auto")
    'auto'
    >>> resolve_sampling("exact", n_expected_draws=1000)
    'exact'
    """
    if sampling not in SAMPLING_PATHS:
        raise ValueError(
            f"sampling must be one of {SAMPLING_PATHS}, got {sampling!r}"
        )
    if sampling != "auto" or n_expected_draws is None:
        return sampling
    # The same crossover the counter uses, applied up front where the count is a fact.
    return "grid" if n_expected_draws > _GRID_ACTIVATION_CALLS else "exact"


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
        sampling: str = _DEFAULT_SAMPLING,
    ):
        if 'previous' not in data.columns or 'current' not in data.columns:
            raise ValueError("DataFrame must contain 'previous' and 'current' columns")

        self.data = data
        self.bandwidth = bandwidth
        self.spec = spec

        #: Which path answers a draw. See :data:`SAMPLING_PATHS`. Validated here so a typo
        #: fails at construction rather than silently sampling from something else.
        self.sampling = resolve_sampling(sampling)

        # Default so that degenerate kinds still expose a ``joint_kde`` attribute
        # (only KDE_2D builds a real 2D KDE).
        self.joint_kde = None

        # Extract array of values
        self.previous_values:np.array = data['previous'].values
        self.current_values:np.array = data['current'].values

        # Cached conditional quantile grid, built lazily once this simulator turns out
        # to be sampled often enough to pay for it. See _build_quantile_grid.
        self._grid_prev_nodes: Optional[np.ndarray] = None
        self._grid_quantiles: Optional[np.ndarray] = None
        self._grid_levels: Optional[np.ndarray] = None
        self._kde2d_calls: int = 0

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

    def _degeneracy_tolerance(self) -> float:
        """The spread below which a slice counts as constant, in this data's units.

        Scaled by the largest magnitude the simulator holds across *both* axes, so the
        test asks "is this negligible next to the rest of the data?" rather than "is this
        exactly zero?". When every value is exactly zero the tolerance is zero too, and
        the comparison still succeeds -- so literal-zero sources behave as they always
        did.
        """
        scale = max(
            float(np.max(np.abs(self.previous_values))),
            float(np.max(np.abs(self.current_values))),
        )
        return _DEGENERACY_RTOL * scale

    def _cat_singularity(self):
        """
        Detect what kind of transition the data supports, and fit accordingly.

        Sets :attr:`kind`. See :class:`Kind` for the categories and the codes they
        replace, and :data:`_DEGENERACY_RTOL` for why the comparison is scale-aware
        rather than exact.
        """
        tolerance = self._degeneracy_tolerance()
        std_prev = float(np.std(self.previous_values))
        std_curr = float(np.std(self.current_values))

        if std_curr <= tolerance:
            # Current is constant: nothing to sample, whatever previous does.
            # This is the old NC and CC collapsed into one.
            self.kind = Kind.CONSTANT
        elif std_prev <= tolerance:
            self.kind = Kind.KDE_1D
            self._cdf_table = self.calculate_next_state_cdf(bandwidth=self.bandwidth)
        else:
            self.kind = Kind.KDE_2D
            # Build the 2D joint distribution
            self._build_joint_distribution()

            if self.joint_kde is None:
                # The covariance was singular despite both axes varying -- perfectly
                # collinear data does this. Without this branch `kind` stayed KDE_2D
                # with no KDE behind it, and the first sample died in
                # `get_conditional_density_gen` with an unreadable
                # "ufunc 'isfinite' not supported for the input types".
                #
                # Degrade rather than raise, matching what this class already does when
                # the joint density vanishes: fall back to the marginal of `current`.
                # One unfittable hour should not take a whole synthetic year with it.
                logging.warning(
                    "2D KDE could not be fitted (singular covariance); falling back to "
                    "the marginal of `current` for this transition. The previous value "
                    "carries no information in this model."
                )
                self.kind = Kind.KDE_1D
                self._cdf_table = self.calculate_next_state_cdf(bandwidth=self.bandwidth)

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
        #
        # `joint_density` is None when no 2D KDE was built. _cat_singularity now
        # re-categorises that case as KDE_1D so it should never reach here, but the
        # check is cheap and the alternative is `np.sum(None)` raising a TypeError about
        # ufunc casting rules -- which says nothing about what actually went wrong.
        total = -1.0 if joint_density is None else np.sum(joint_density)
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

    @property
    def has_quantile_grid(self) -> bool:
        """True once this simulator has cached its conditional quantile grid."""
        return self._grid_quantiles is not None

    def precompute_grid(self) -> None:
        """
        Build the conditional quantile grid now, rather than waiting for it to pay off.

        Sampling normally uses the direct path until a simulator has been asked for
        :data:`_GRID_ACTIVATION_CALLS` samples, because building the grid costs about as
        much as that many direct calls. Call this when the ensemble size is known in
        advance and is large -- it removes the threshold's crossover from the timing, and
        makes every draw come from the same sampler.

        A no-op unless :attr:`kind` is :attr:`Kind.KDE_2D`: the 1D and constant paths are
        already a single interpolation and a lookup.
        """
        if self.kind is Kind.KDE_2D and not self.has_quantile_grid:
            self._build_quantile_grid()

    def _build_quantile_grid(self) -> None:
        """
        Cache the conditional inverse CDF on a grid of ``previous`` values.

        One vectorised KDE evaluation over ``_CDF_GRID_NODES x 1000`` points replaces one
        1000-point evaluation *per sample*. Sampling then costs two interpolations: along
        ``previous`` between the two bracketing nodes, and along the quantile axis.

        **The quantile function is what is interpolated across ``previous``, not the CDF
        or the density.** The conditional's location moves with ``previous`` -- that is
        the whole content of the model -- and averaging two CDFs of distributions centred
        in different places produces a bimodal blend of them, whereas averaging their
        quantile functions shifts one into the other. Measured on 21 March at
        ``bandwidth=0.1``, quantile interpolation reaches a given accuracy at roughly half
        the node count.
        """
        x_values = self._get_x_domain(resolution=1000)
        lo = float(np.min(self.previous_values))
        hi = float(np.max(self.previous_values))
        nodes = np.linspace(lo, hi, _CDF_GRID_NODES)

        # One evaluation of the joint density over the whole (previous, current) grid.
        prev_mesh, curr_mesh = np.meshgrid(nodes, x_values, indexing="ij")
        density = self.joint_kde(
            np.vstack([prev_mesh.ravel(), curr_mesh.ravel()])
        ).reshape(_CDF_GRID_NODES, x_values.size)

        # A row whose density vanished gets the marginal of `current`, which is what the
        # direct path falls back to for the same reason -- conditioning that carries no
        # information should answer with the unconditional distribution rather than NaN.
        totals = density.sum(axis=1)
        vanished = ~np.isfinite(totals) | (totals <= 0)
        if vanished.any():
            logging.warning(
                "joint density vanished at %d of %d grid nodes; those rows fall back to "
                "the marginal of `current`.", int(vanished.sum()), _CDF_GRID_NODES,
            )
            marginal = np.histogram(
                self.current_values, bins=x_values.size,
                range=(float(x_values[0]), float(x_values[-1])),
            )[0].astype(float)
            if marginal.sum() <= 0:
                marginal = np.ones_like(x_values, dtype=float)
            density[vanished] = marginal
            totals = density.sum(axis=1)

        cdf = np.cumsum(density / totals[:, None], axis=1)
        cdf /= cdf[:, -1:]

        levels = np.linspace(0.0, 1.0, _GRID_QUANTILE_LEVELS)
        self._grid_quantiles = np.stack(
            [np.interp(levels, cdf[i], x_values) for i in range(_CDF_GRID_NODES)]
        )
        self._grid_prev_nodes = nodes
        self._grid_levels = levels

    def _get_next_state_kde2d(self, current_state: float, rng: np.random.Generator) -> float:
        """Sample from ``p(current | previous=current_state)`` via the 2D KDE.

        Slices the joint density vertically at ``current_state`` and inverse-transform
        samples the resulting 1D conditional. Below the activation threshold this
        evaluates the KDE directly; above it, it reads the cached quantile grid. Both
        consume exactly one number from ``rng``, so which path is taken never perturbs
        the random stream.
        """
        if not self.has_quantile_grid:
            # Counted on every path, because the count is worth knowing even when it
            # decides nothing -- see the advisory note below.
            self._kde2d_calls += 1

            if self.sampling == "auto" and self._kde2d_calls > _GRID_ACTIVATION_CALLS:
                # Only "auto" with no draw count reaches here: the caller knew nothing, so
                # the counter advises. Every other path was settled before drawing began.
                self._build_quantile_grid()
            elif self.sampling != "grid":
                if self.sampling == "exact":
                    self._advise_grid_once()
                res_dict = self.get_conditional_density(current_state)
                curr_values, cdf = res_dict['domain'], res_dict['cdf']
                return float(np.interp(rng.random(), cdf, curr_values))
            else:
                # sampling == "grid" but nobody built it: build now rather than silently
                # taking the other path.
                self._build_quantile_grid()

        return self._sample_from_grid(current_state, rng)

    def _advise_grid_once(self) -> None:
        """Say once that a grid would have paid for itself, then never again.

        The counter knows something worth knowing -- *this simulator has answered many
        draws the slow way and nobody asked for the grid* -- and `FEAT-17` keeps it for
        exactly that. It no longer changes any number; it only makes the optimisation
        discoverable instead of silently forgone.
        """
        if self._kde2d_calls == _GRID_ACTIVATION_CALLS + 1:
            logging.info(
                "simulator drew %d times on the exact path; pass sampling='grid' "
                "(or a draw count to sampling='auto') for the cached grid -- ~13x "
                "faster for a large ensemble, same distribution",
                self._kde2d_calls,
            )

    def _sample_from_grid(self, current_state: float, rng: np.random.Generator) -> float:
        """Two interpolations: along ``previous``, then along the quantile axis."""
        nodes = self._grid_prev_nodes

        # Same clamp as the direct path: outside the fitted range every kernel is ~0, and
        # the nearest fitted value is the only meaningful answer.
        prev_value = float(np.clip(current_state, nodes[0], nodes[-1]))

        j = int(np.clip(np.searchsorted(nodes, prev_value) - 1, 0, nodes.size - 2))
        width = nodes[j + 1] - nodes[j]
        weight = 0.0 if width <= 0 else (prev_value - nodes[j]) / width
        quantiles = (1.0 - weight) * self._grid_quantiles[j] + weight * self._grid_quantiles[j + 1]

        return float(np.interp(rng.random(), self._grid_levels, quantiles))

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
