# Spell lengths (run lengths)

**Suitability: ✅ Recommended.** This is the storage engineer's version of the autocorrelation.

## In plain words

Count how many **days in a row** the weather stays "bad": wind below its usual low
level, sun below its usual low level, or temperature unusually hot or cold. Then compare
how often real and synthetic data produce spells of 1, 2, 3… days. A battery or
hydrogen store is sized for the **longest lull**, not for a correlation coefficient, so
this is the form of persistence engineers actually use.

## How it is computed

1. Compute daily values (for example the daily mean wind speed).
2. Set a threshold from the **real** data, for example its 10th percentile.
3. Find the runs of consecutive days below (or above) the threshold and record their
   lengths.
4. Compare the run-length distributions, especially the longest runs, real against
   synthetic.

| Variable | Spell type |
| :--- | :--- |
| Wind | calm spells |
| Irradiance | overcast spells |
| Temperature | heat waves / cold spells |

## What it catches

- Multi-day lulls that are too rare or too short, which a yearly average would never
  show.

## What it misses

- Hour-level detail and the exact size of the deficit. For the size, see the net-load
  deficit on {doc}`energy-system`.

## Comment for meteosynth

- **Expected failure:** too few long spells. That follows from the ACF fading too fast,
  and from the known deficit of heavily overcast days (about 4× too rare against the
  training pool). Report it as a scope limit for storage studies.
- Needs year-long series (product Y) at M:N. Long spells are rare, so the uncertainty
  comes from the real record. Use the control band.

**See also:** {doc}`autocorrelation`, {doc}`tail-dependence`.
