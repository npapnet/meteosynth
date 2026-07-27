# Concepts and terminology

The rest of the documentation assumes a handful of words. This page defines them in
plain language, starting with the one everything else hangs off: **ensemble**.

If you want the mathematics instead, go to {doc}`theory`. If you want to run something,
go to {doc}`quickstart`.

---

## Start here: what an ensemble is

Suppose you want to know how much sun a solar panel gets on **21 May** at your site.

- You could look at **last 21 May**. That gives you one number — but it might have been
  a freakishly cloudy day, and you would never know.
- You could look at **every 21 May you have records for**. Eleven years gives eleven
  numbers. Better. But eleven is not many, and none of them is *next* year's 21 May.
- Or you can build a machine that has learned **what 21 May is like** at your site, and
  ask it for two hundred fresh 21 Mays. All different. None of them a copy of a real
  day. All of them days the local weather knows how to make.

That pile of two hundred days is an **ensemble**. Each single day in it is a
**realisation** (or a *draw*).

It is a bit like weather dice — except the dice are shaped by history, so they can only
roll days your site could actually have. Roll once and you get a day. Roll two hundred
times and you get something one day could never give you: *how often* each kind of day
happens, including the rare bad ones.

```{mermaid}
flowchart LR
    R["11 years of<br/>real 21 Mays"] --> M["one fitted model<br/>of '21 May here'"]
    M --> D1["synthetic day 1"]
    M --> D2["synthetic day 2"]
    M --> D3["synthetic day 3"]
    M --> Dn["… day 200"]
    D1 --> E["the ensemble"]
    D2 --> E
    D3 --> E
    Dn --> E
```

**Why bother?** Because the questions worth asking are about the rare days, not the
average one. *How big must the battery be for the worst week? How low can production go
in a bad year? What do I promise a lender?* One day answers "what happened". An ensemble
answers "what can happen, and how often" — and that is a *distribution*, not a number.

```{note}
An ensemble cannot invent information the record does not contain. It re-samples the
statistics it was shown, so a site with eleven mild years produces a synthetic ensemble
of mild years. It fills in the *gaps between* observed weather; it does not predict
weather the site has never had, and it knows nothing about a changing climate.
```

## Ensemble versus the alternatives

| Option | What it is | What it tells you | What it hides |
| :--- | :--- | :--- | :--- |
| **One historical year** | Real measurements from one specific past year | Exactly what happened, once | Everything else that could have happened |
| **The whole record** | All the measurements you have (here: 11 years) | The range that did occur — 11 answers | The tail. Eleven years cannot show you a 1-in-50 event, and you cannot ask for a twelfth answer |
| **TMY** (Typical Meteorological Year) | Twelve real months, each picked from a different year, stitched into one "representative" year | A sensible average year, in one file | Variability *by construction* — it is built to be typical, so it has no bad years in it. One profile, one answer |
| **One synthetic realisation** | One fresh series drawn from the fitted model | One plausible alternative history | Same blind spot as one real year: no spread |
| **An ensemble** | Many independent realisations of the same thing | A distribution: P50, P90, worst case, spread | Nothing about spread — but it is only ever as good as the model and the record behind it |

The one-line version: **the historical record is a sample of fixed size; an ensemble lets
you draw as many samples as you like from the same statistics.**

## Two ways to build one here

Inside `meteosynth` the word "ensemble" covers two different things, and picking the
wrong one is the most common way to get a plausible-looking but meaningless answer.

| | **Independent days** | **Chained series** |
| :--- | :--- | :--- |
| Call | `gen_day()` in a loop | `generate_series(start, n_days)` |
| Each day starts from | that date's fitted initial distribution π(x₀) | the *previous day's* 23:00 value, via the cross-midnight model |
| Days are | independent of each other | linked in order |
| Answers | "What can a 21 May look like?" | "What does a whole May / year look like, in sequence?" |
| Use it for | single-day questions, distributions of a daily quantity | anything where **order** matters: battery state, streaks of cloudy days, monthly and annual totals |
| Example script | `use_cases/day_envelope_*.py` | `use_cases/synthetic_year.py` |

You can also have an **ensemble of chained series** — call `generate_series` twelve times
and you have twelve synthetic Mays (`use_cases/monthly_statistics.py`), or a hundred times
for a hundred synthetic years. That is the shape a real Monte-Carlo study takes.

```{note}
**The boundary of a call is the reset.** Within one `generate_series` call the days are
chained across midnight; between two calls nothing is carried over. So "500 independent
days" is `generate_series(..., n_days=1)` called 500 times, *not* one call with
`n_days=500`.
```

---

## The vocabulary

### What you start with

| Term | What it means |
| :--- | :--- |
| **Record** / observed data | The historical measurements you train on — here, hourly PVGIS data. Also called the *training data*. |
| **Attribute** | One measured quantity, named by its column: `poa_global`, `temp_air`, `wind_speed`. Each is modelled separately. |
| **Index columns** | `year`, `month`, `day`, `hour` — the calendar every record must carry. |
| **Wide format** | The record reshaped to one row per day and one column per hour (24 columns). Pairing values within a day is safe in this shape, which is why the package pivots into it. |
| **Training subset** | The slice of the record one model is fitted to. Two ways to cut it: a **month subset** (all of May) or a **rolling day window**. |
| **Rolling day window** | Every day within ±*n* days of a target date, pooled across **all** years. A 21 May window with `n_days=15` pools 6 May – 5 June from all eleven years: 341 days. Centred on the target and slides smoothly from one day to the next, which a month subset does not. |
| **Pooled** / climatological | Taken from all years at once, treated as samples of "what this time of year is like" rather than of any specific year. |

### What the model is

| Term | What it means |
| :--- | :--- |
| **Distribution** | The full picture of what values are possible and how likely each is — not just an average. |
| **Conditional distribution** | A distribution *given* something else. "How windy at 14:00, **given** it was 3 m/s at 13:00." Written $p(x_t \mid x_{t-1})$. |
| **Transition** | One step from one hour to the next. The model holds 23 of them per day (01:00 → 23:00), each fitted separately. |
| **Transition pair** | One `(previous, current)` observation — the raw material a transition is fitted from. |
| **Markov chain, first-order** | The assumption that the next value depends only on the *current* one, not on the whole history. It is what makes an hour-by-hour walk possible. |
| **KDE** (kernel density estimation) | A way of turning scattered points into a smooth distribution — a histogram with soft edges rather than bars. |
| **Bandwidth** | How much smoothing the KDE applies. Small = follows the data closely and can look lumpy; large = smooth but washes out detail. |
| **π(x₀)** (initial distribution) | The distribution of the *first* value of a chain — the observed midnight values for that date. Nothing precedes hour 0, so it cannot be a transition. For irradiance every observed midnight is 0, so π(x₀) is a spike at zero and every synthetic day starts there — from the data, not from a hard-coded rule. |
| **Cross-midnight model** | The transition 23:00 (yesterday) → 00:00 (today), fitted from genuinely consecutive calendar dates. It is what carries a chained series across midnight. |
| **Degenerate** | A transition with nothing to model, because the data does not vary — night-time irradiance is exactly 0 every hour of every year. The package detects this and returns the constant instead of fitting a density to it. |
| **Support** | The physical bounds of a quantity: irradiance ≥ 0, wind speed ≥ 0, temperature ≥ −273.15 °C. Sampling is truncated to the support, so an impossible value is *unsamplable*, not merely unlikely. |
| **Spec** / registry | The declaration of what a column physically is (support, units, name). A column can be modelled if and only if it has one, which is how the package stays open to new quantities. |

### What comes out

| Term | What it means |
| :--- | :--- |
| **Synthetic** | Generated, not measured. Every value is drawn from a fitted distribution; nothing is copied from the record. |
| **Realisation** / draw | One generated series — one day, one month, one year. |
| **Ensemble** | Many realisations of the same thing, treated as a sample of what is possible. |
| **Chained** | Days joined in order across midnight, so the series is continuous. |
| **Seed** / RNG | The number that fixes the randomness. Same seed, same output — which is what makes a stochastic script reproducible. |

### How you judge it

| Term | What it means |
| :--- | :--- |
| **Envelope** / band | A shaded region showing where most observed days fall, usually between the 10th and 90th percentile at each hour. |
| **Cloud** | The individual observed days drawn as separate thin lines, rather than summarised into a band. |
| **Percentile** | The value below which a given share of cases falls. The 90th percentile is exceeded by only 10% of days. |
| **P50 / P90** | The energy-industry convention, and it runs the *other way*: the value **exceeded** in 50% / 90% of cases. So P90 is the pessimistic figure — the one a lender asks about — and it sits at the 10th percentile. |
| **Coverage** | The share of synthetic values landing inside the observed p10–p90 band. About 80% means the ensemble is as wide as the weather. Much higher means it is too narrow; much lower means too wide. |
| **Bias** | A systematic offset: the synthetic mean sitting consistently above or below the observed one. |
| **Spread ratio** | Synthetic standard deviation ÷ observed standard deviation. Near 1 is right; below 1 understates risk, above 1 overstates it. |
| **Calibrated** | Getting the *magnitudes* right, not just the shape. A generator can trace a perfect diurnal curve and still deliver 14% too much energy. |
| **Monte-Carlo** | Answering a question by running it over many random realisations and looking at the distribution of answers, instead of one "best guess" run. |

---

## Reading an envelope figure

The `use_cases/day_envelope_*.py` scripts all produce the same picture, so it is worth
learning once:

| What you see | What it is |
| :--- | :--- |
| Pale blue band | Observed p10–p90 — where the middle 80% of nearby real days fall, hour by hour |
| Thin blue lines | The actual observed days for that exact date, one per year — the cloud |
| Dashed blue line | Median of the observed days |
| Thin orange lines | A handful of individual synthetic days, to show their texture |
| Dotted orange lines | The synthetic ensemble's own p10–p90 |
| Solid orange line | Median of the synthetic ensemble |
| Right-hand panel | One number per day (daily total or mean) — the quantity an energy model actually consumes |

A good result is: the orange median tracks the dashed blue one (**shape**), the orange
band is about as wide as the blue one (**spread**), and the orange mass in the right-hand
panel sits on top of the blue (**quantity**). Those three can fail independently, which
is why all three are reported.

---

## Where to go next

- {doc}`quickstart` — install and generate something.
- {doc}`workflow` — the order the pieces are used in.
- {doc}`theory` — the mathematics behind the words above.
- {doc}`examples` — runnable scripts, including the use cases referenced here.
