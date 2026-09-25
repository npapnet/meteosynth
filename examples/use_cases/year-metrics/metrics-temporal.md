# Temporal fidelity: reading the autocorrelation figure

`metrics-temporal.py` asks one question: **does synthetic weather remember the past the way
real weather does?** It answers it with a 2×2 figure per variable, written to
`output/temporal_acf_leros_<variable>.png`, and a per-lag table beside it (`.csv`).

```
                 RAW ACF                         ANOMALY ACF
            (values as they are)          (typical day/season removed)
         ┌──────────────────────────┐   ┌──────────────────────────┐
 0–240 h │ Does the synthetic data   │   │ Do weather spells last as │
         │ have the right average    │   │ long as real ones?        │
         │ day and average year?     │   │   ← the real test         │
         └──────────────────────────┘   └──────────────────────────┘
         ┌──────────────────────────┐   ┌──────────────────────────┐
 0–72 h  │ same, zoomed on the first │   │ same, zoomed on the first │
         │ three days                │   │ three days                │
         └──────────────────────────┘   └──────────────────────────┘

 in every panel:  grey band  = spread of the 19 real years (5th–95th percentile)
                  dark line  = average of the 19 real years
                  red line   = average of the 1000 synthetic years
```

**Short version of the results for Leros:**

| Variable | Raw ACF | Anomaly ACF | Memory τ, real → synthetic | Verdict |
|---|---|---|---|---|
| `poa_global` | matches | no memory from one day to the next | 6.4 h → 5.6 h | a cloudy day doesn't make the next day cloudier, as it does in reality |
| `temp_air` | too persistent | far too persistent at every lag | 134.5 h → 287.5 h (×2.1) | warm and cold spells last about twice as long as real ones |
| `wind_speed` | inside the band | mostly inside, too persistent at 15–25 h | 73.2 h → 127.0 h (×1.7) | looks acceptable, **but only because of broken data**. See [§7](#7-data-problem-broken-late-december-wind-in-five-of-the-19-years) |

All three synthetic curves behave like a process that only remembers the last hour
([§6](#6-why-the-synthetic-curves-look-the-way-they-do)). The wind "pass" rests on corrupted
blocks in the training record: when they're removed, synthetic wind is clearly too
persistent too ([§7](#7-data-problem-broken-late-december-wind-in-five-of-the-19-years)).

---

## 1. What an autocorrelation is

### In plain words

Take one year of hourly wind speed. Pick any hour and ask: *"it's windier than usual right
now. Will it still be windier than usual in 6 hours? In 24? In 5 days?"* Averaged over all
the hours of the year, the answer is the **autocorrelation at lag *k***: the correlation
between the series and a copy of itself shifted by *k* hours.

- **ρ = 1**: knowing now tells you exactly how things will be *k* hours later.
- **ρ = 0**: knowing now tells you nothing about *k* hours later.
- **ρ < 0**: the opposite tends to happen *k* hours later.

At lag 0 the series is compared with itself, so the value is always 1. After that the curve
falls as the series "forgets". **How fast it falls is the whole subject of this test.**

An analogy is a rumour in a school. At lag 0 everyone has just heard it. An hour later most
people still remember it exactly. After a day it's fuzzy, and after a week it's forgotten. A
series whose curve falls slowly holds on to a rumour for a long time. One whose curve falls
fast forgets it quickly.

### The mathematics

For one series $x_1, \dots, x_T$ with mean $\bar x$ (a year: $T = 8760$ hours, or $8784$ in
a leap year), the script uses the **biased** sample autocovariance and autocorrelation:

$$
\hat\gamma(k) = \frac{1}{T}\sum_{t=1}^{T-k} (x_t - \bar x)(x_{t+k} - \bar x),
\qquad
\hat\rho(k) = \frac{\hat\gamma(k)}{\hat\gamma(0)}, \qquad k = 0, 1, \dots, 240 .
$$

"Biased" means dividing by $T$ at every lag, not by $T-k$, the number of pairs actually
summed. That shrinks the long lags slightly toward zero. In return the curve decays smoothly
and is guaranteed to be a valid correlation function, and the long lags, where the fewest
pairs exist, are not amplified. At $k = 240$ the factor is $(T-k)/T \approx 0.97$, so the
shrinkage is small.

`acf_rows` computes this for all lags at once with an FFT (the Wiener–Khinchin theorem:
the autocovariance is the inverse Fourier transform of the power spectrum). It pads to at
least $2T$ so the series doesn't wrap around onto itself. The result is the same as the sum
above, just faster.

### Computed within a year, then averaged

Each real year gives one curve $\hat\rho_m(k)$, $m = 1..M$ with $M = 19$ (2005–2023). Each
synthetic realisation gives one curve $\hat\rho_n(k)$, $n = 1..N$ with $N = 1000$. The
figure shows

$$
\bar\rho_{\text{obs}}(k) = \frac{1}{M}\sum_m \hat\rho_m(k) \;\;\text{(dark line)},
\qquad
\bar\rho_{\text{syn}}(k) = \frac{1}{N}\sum_n \hat\rho_n(k) \;\;\text{(red line)},
$$

and the grey band from $q_{5\%}(k)$ to $q_{95\%}(k)$ across the 19 real curves. With 19
years, NumPy's percentile interpolation places the 5% point between the lowest and
second-lowest year, and the 95% point between the second-highest and highest. Roughly, **the
band runs from the second-lowest year to the second-highest year.**

Realisations are never joined end to end. Joining two independent years puts a jump at
every join, and that jump would show up as extra decay that has nothing to do with the
generator.

The red line has no band of its own because it doesn't need one. Its standard error,
$s/\sqrt{N}$ and stored as `syn_*_sem` in the CSV, is at most 0.0013 (`poa_global`), 0.0052
(`temp_air`) and 0.0033 (`wind_speed`), thinner than the line. **All the uncertainty in
the figure comes from having only 19 real years.**

---

## 2. Left column: the raw ACF

### What it is

$\hat\rho(k)$ of the values exactly as recorded.

### Why it mostly measures the calendar

Hourly weather is a **repeating pattern plus weather** on top of it. Write it as

$$
x_t = s_t + w_t ,
$$

where $s_t$ is the repeating part (the average day and the average year) and $w_t$ is
everything else. If the two are unrelated, the ACF of the sum is a **variance-weighted
mix** of the two ACFs:

$$
\rho_x(k) = \frac{\operatorname{Var}(s)\,\rho_s(k) + \operatorname{Var}(w)\,\rho_w(k)}
                 {\operatorname{Var}(s) + \operatorname{Var}(w)} .
$$

Whichever part has the bigger variance dominates the raw ACF. In plain words: if the daily
rhythm is loud and the weather is quiet, the raw ACF mostly measures the rhythm.

That is why the three raw panels look so different:

- **`poa_global` (sunlight on the panel):** the day/night rhythm is huge, from 0 at night to
  hundreds of W/m² at noon. The raw ACF is almost a pure 24-hour wave. It is +0.94 at 24 h
  (noon matches noon) and −0.50 at 12 h (noon matches midnight).
- **`temp_air`:** the seasonal cycle dominates. A July hour and the hour 10 days later are
  both July hours, so the raw ACF is still 0.82 at 240 h. The small ripple every 24 h is the
  daily cycle.
- **`wind_speed`:** Leros has almost no daily wind rhythm. The hourly mean only varies from
  6.9 to 7.7 m/s across the day. The raw ACF is therefore nearly all weather, and the raw and
  anomaly panels differ by at most 0.05.

### How to interpret it

Passing the raw panel means the generator reproduces the **shape of the average day and
the average year**. That is useful but easy: a generator could pass it with completely wrong
weather, as long as the rhythm is right. **Don't read the raw panel alone.**

---

## 3. Right column: the anomaly ACF

### What it is

The ACF after the average rhythm has been subtracted, which leaves **the weather**: how much
windier, warmer or sunnier than usual this hour is for its date and time of day.

### The climatology that gets subtracted

`compute_climatology` estimates the "usual" value from the 19 real years in two steps.

1. **Raw mean per (day of year, hour).** For every calendar slot $d \in 1..366$ (Feb 29 is
   an ordinary slot) and hour $h \in 0..23$:
   $$ c(d, h) = \text{mean of } x \text{ over all real hours at slot } d, \text{ hour } h . $$
   That is about 19 values per cell, too few to be smooth.

2. **Smoothing over ±15 days, wrapping around New Year:**
   $$
   \tilde c(d, h) = \operatorname{mean}\{\, c(d', h) : \operatorname{dist}(d, d') \le 15 \,\},
   \qquad
   \operatorname{dist}(d, d') = \big|\big((d' - d + 183) \bmod 366\big) - 183\big| .
   $$
   The distance is measured around a circle, so 31 December and 1 January are 1 day apart,
   not 365. The ±15-day width matches the generator's own training window.

The anomaly is then

$$
a_t = x_t - \tilde c\big(d(t), h(t)\big),
$$

and the **same** $\tilde c$, built from real data only, is subtracted from both the real
and the synthetic series. Both sides are measured against the same ruler.

Both day of year *and* hour are needed. Subtracting only an hour-of-day average would leave
the seasonal slope in. At lags of up to 10 days, that slope would pass for persistence.

### Why this is the real test

The generator is a **first-order chain**: each hour is drawn given only the previous hour.
Nothing in it is fitted to memory longer than one hour. So:

- **Lag 1** matches by construction. It is what the model was fitted to, so it proves nothing.
- **Lags 6–48 h** are where the model must produce multi-hour persistence it was never
  directly given. This is the synoptic scale: weather systems that last from half a day to a
  few days.
- **Red below the band:** synthetic weather spells end too quickly (storms, calms and cloudy
  spells are too short).
- **Red above the band:** synthetic spells last too long.

---

## 4. Top row vs bottom row

The two rows show the same curves at different horizontal scales.

- **Top, 0–240 h (10 days):** the full synoptic range, which matters for storage sizing and
  multi-day deficits.
- **Bottom, 0–72 h:** at 240 h the first day or two, where the curves usually separate
  first, are squeezed into the left edge. The zoom stretches them out.

The faint vertical lines mark every 24 h.

---

## 5. The memory time τ in the title

### What it is

The **integral decorrelation time**, computed from the anomaly curve of each year or
realisation and then averaged:

$$
\tau = 1 + 2\sum_{k=1}^{K} \rho(k),
$$

where $K$ is the last lag before the curve first reaches zero or below. The sum stops there
because beyond that point the terms are mostly noise around zero.

### What it means

Roughly: **how many hours pass before the weather has "forgotten" itself**. In a year of
$T$ hours there are only about $T/\tau$ truly independent pieces of weather. The variance of
an annual mean scales the same way:

$$
\operatorname{Var}(\text{annual mean}) \approx \frac{\sigma^2\,\tau}{T} .
$$

So τ predicts **how much synthetic years will differ from one another**. With τ twice too
large and everything else equal, the variance of synthetic annual means is about twice too
large, so their spread is about 1.4× too wide. Any study that depends on bad years inherits
that error.

For a first-order linear process with $\rho(k) = \varphi^k$, $\tau = (1+\varphi)/(1-\varphi)$.

**τ can't see memory that comes after a zero crossing.** This matters for `poa_global`, whose
anomaly ACF reaches zero near 12 h and rises again at 24 h
([§8.1](#81-poa_global)). There τ understates the gap between real and synthetic.

---

## 6. Why the synthetic curves look the way they do

A first-order linear process that keeps only its lag-1 correlation $\rho_1$ has the ACF
$\rho(k) = \rho_1^{\,k}$. Plugging in the **synthetic** $\rho_1$ reproduces the synthetic
anomaly curve almost exactly:

| lag | `temp_air` real | `temp_air` synthetic | $\rho_1^k$ | `wind_speed` real | `wind_speed` synthetic | $\rho_1^k$ |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.994 | 0.995 | 0.995 | 0.984 | 0.983 | 0.983 |
| 6 | 0.925 | 0.968 | 0.970 | 0.839 | 0.902 | 0.901 |
| 12 | 0.843 | 0.938 | 0.941 | 0.666 | 0.817 | 0.812 |
| 24 | 0.724 | 0.889 | 0.886 | 0.391 | 0.677 | 0.659 |
| 48 | 0.464 | 0.792 | 0.786 | 0.161 | 0.467 | 0.435 |
| 72 | 0.303 | 0.708 | 0.696 | 0.094 | 0.324 | 0.287 |
| 240 | 0.038 | 0.332 | 0.299 | 0.038 | 0.020 | 0.016 |

(Anomaly ACF means, from `output/temporal_acf_leros_*.csv`.)

So **the generator behaves like a process with one hour of memory**, and real weather does
not. The difference is visible in the first three lags, from the loss $1 - \rho(k)$:

| | $1-\rho(1)$ | $1-\rho(2)$ | $1-\rho(3)$ | growth |
|---|---:|---:|---:|---|
| `temp_air` real | 0.006 | 0.016 | 0.030 | accelerating (×2.7, ×5) |
| `temp_air` synthetic | 0.005 | 0.010 | 0.016 | straight line (×2, ×3) |
| `wind_speed` real | 0.016 | 0.043 | 0.072 | accelerating (×2.7, ×4.5) |
| `wind_speed` synthetic | 0.017 | 0.034 | 0.051 | straight line (×2, ×3) |

**Analogy: a car on a road.** If you know only *where* the car is, your best guess for the
next minute is "about here", and that guess degrades slowly and steadily. The real car also
has a *direction*: it keeps moving the same way for a while, so after an hour it's much
farther away than the steady guess suggests. Real temperature and wind have that kind of
momentum. Hour to hour they barely change, so $\rho_1$ is close to 1, but the changes keep
going the same way, so they drift away within a day or two. A chain that sees only the
position must choose: match lag 1 and decay too slowly (what happens here), or decay at the
right speed and get lag 1 wrong. It can't do both.

---

## 7. Data problem: broken late-December wind in five of the 19 years

The training record `data/pvgis_hourly_leros_2005_2023.parquet` has **wind values that are
not weather** from about 12 to 31 December in five years:

| year | wind, 12–31 Dec: mean | std | what it looks like |
|---|---:|---:|---|
| 2007 | 23.06 m/s | 1.57 | stuck near 23 m/s for 20 days |
| 2014 | 0.02 m/s | 0.27 | dead calm for 20 days |
| 2015 | 11.71 m/s | 0.92 | nearly constant |
| 2016 | 6.00 m/s | **0.00** | exactly constant |
| 2017 | 37.53 m/s | 2.83 | 99% of hours exactly 37.8 m/s |
| other 14 years | 6.0–8.5 m/s | 2.6–4.3 | normal weather |

Outside these blocks, the whole 19-year record has only **8 hours** above 20 m/s.
Temperature in the same blocks looks normal.

### Effect on the observed band

A value held flat for 20 days has near-perfect memory, which pushes those years' ACFs up.
2007 and 2017 are the two highest wind curves (raw ACF at 24 h: 0.70 and 0.86, against
0.31–0.47 for the other 17 years). Those two years alone form the top of the grey band.
Recomputed without them (raw ACF, which for wind is within 0.05 of the anomaly ACF):

| observed wind, raw ACF | mean @24 h | mean @48 h | mean @72 h | band top @24 h | τ (raw) |
|---|---:|---:|---:|---:|---:|
| all 19 years, as plotted | 0.423 | 0.204 | 0.140 | 0.717 | 83.0 h |
| 14 clean years | 0.371 | 0.143 | 0.076 | 0.409 | 56.0 h |
| 19 years, 12–31 Dec removed | 0.376 | 0.139 | 0.073 | 0.429 | 56.5 h |

The synthetic raw ACF at 24 h is 0.688. **Against a clean band, whose top is about 0.41–0.43,
synthetic wind is well outside, and too persistent**, the same failure as temperature,
only milder. The current "inside the band" result for wind comes from the broken years.

### Effect on the ensemble

The generator was trained on this record, and its ±15-day window wraps across New Year. So
the broken blocks feed every synthetic day from mid-November to mid-January. The ensemble
shows it: 3.1% of synthetic December hours and 0.8% of January hours are above 30 m/s,
the synthetic maximum is exactly 37.8 m/s, and no other month has any. This probably makes
synthetic wind *more* persistent as well, since the model learned "37.8 is followed by
37.8". That effect has **not been measured**.

The climatology used for the anomaly ACF is also distorted for late December, because
2017's 37.8 m/s enters the mean for those slots.

---

## 8. Variable by variable

### 8.1 `poa_global`

![poa_global](output/temporal_acf_leros_poa_global.png)

- **Raw panels:** red lies on top of grey (inside the band at 231 of 241 lags). The daily
  rhythm of sunlight is reproduced. The misses are at lag 3 and at 20–28 h, where the red
  peak at 24 h is slightly low (0.931 against a band of 0.933–0.955), for the reason given
  in the next point.
- **Anomaly panels:** the real curve falls to about 0 by 10–12 h, then **rises to 0.19 at
  24 h** (band 0.13–0.28), with smaller bumps at 48, 72 h and later. That bump means *a
  cloudier-than-usual day tends to be followed by another one*. The synthetic curve has
  **no bump at all**: 0.000 at 24 h and 0.002 at 48 h. It falls below the band at lags 3–6
  and 16–30, 19 lags, every one of them below.
- **Why:** sunlight is 0 overnight in every realisation. A chain that only remembers the
  previous hour passes through the same state each night, so nothing carries over to the
  next morning. The 24 h bump can't survive a night of zeros under a one-hour memory. This
  is the most likely mechanism consistent with the data. The ensemble's cross-midnight
  model hasn't been checked separately.
- **Also:** the dip near 12 h is not a finding. Night anomalies are about zero, so pairing
  noon with midnight gives a product of about zero.
- **τ:** 6.4 h real, 5.6 h synthetic. The sum stops at the first zero near 10–12 h, so τ
  **can't see** the missing 24 h bump and understates the problem (see [§5](#5-the-memory-time-τ-in-the-title)).
- **What it means for use:** synthetic cloudy spells don't last from one day to the next.
  Multi-day low-solar periods will be too rare, which matters directly for storage sizing.

### 8.2 `temp_air`

![temp_air](output/temporal_acf_leros_temp_air.png)

- **Raw panels:** red is above the band from lag 3 onward (157 of 241 lags outside, all
  above). It returns inside at long lags only because the seasonal cycle then dominates both
  curves and the band widens.
- **Anomaly panels:** the clearest failure in the set. Inside the band at **2 of 241 lags**
  (0 and 1, the fitted ones). Above it at every other lag: 0.889 against 0.68–0.78 at 24 h,
  and 0.708 against 0.19–0.45 at 72 h.
- **τ:** 134.5 h real against 287.5 h synthetic, **×2.1**.
- **Why:** the one-hour-memory behaviour of [§6](#6-why-the-synthetic-curves-look-the-way-they-do). Real hourly
  temperature is very smooth ($\rho_1 = 0.994$), and a chain that matches that smoothness
  decays as $0.995^k$, far too slowly.
- **What it means for use:** warm and cold spells last about twice as long as real ones.
  From §5's variance formula, synthetic annual-mean temperatures should spread more between
  years than real ones do.

### 8.3 `wind_speed`

![wind_speed](output/temporal_acf_leros_wind_speed.png)

- **Raw and anomaly panels look almost the same**, because Leros has almost no daily wind
  rhythm ([§2](#2-left-column-the-raw-acf)).
- **As plotted:** raw ACF inside the band at all 241 lags, anomaly ACF at 230 of 241. It is
  outside, above the band, only at 15–25 h. Red runs along the **top edge** of the band for
  the first three days, well above the dark line.
- **τ:** 73.2 h real against 127.0 h synthetic, **×1.7**.
- **Why the band is so wide and lopsided:** the dark line sits near the bottom of the band.
  The top edge is set by the two broken years, 2007 and 2017 ([§7](#7-data-problem-broken-late-december-wind-in-five-of-the-19-years)).
  With the broken blocks removed, the band top at 24 h drops from 0.72 to about 0.42, and
  the synthetic 0.69 is clearly outside.
- **What it means for use:** synthetic windy and calm spells last too long. The pattern is
  the same as for temperature, only milder. That is hidden in the figure by corrupted
  training data.

---

## 9. Limits of the figure

- **Red is an average; grey is the spread of individual years.** Red inside the band means
  "the *average* synthetic year sits within the range of real years". That is a lenient
  comparison. A stricter one would compare the observed mean (dark line), whose own
  uncertainty is roughly the band width ÷ 14 with 19 years, or would plot the 5–95% band of
  the 1000 synthetic curves next to the grey one. The script does neither.
- **19 years is a small sample.** The band edges are set by just the one or two most extreme
  years, as the wind case shows.
- **The anomaly ACF is only as good as the climatology.** Broken data in the record (§7) goes
  into $\tilde c$ as well.
- **One site, one ensemble** (`ensemble_leros_2023_n1000_3attr.parquet`, seed fixed). The
  results describe this generator configuration on this record.

---

## 10. What's in the CSV

`output/temporal_acf_leros_<variable>.csv`, one row per lag 0–240:

| column | meaning |
|---|---|
| `lag_hours` | $k$ |
| `obs_raw_mean`, `obs_anomaly_mean` | $\bar\rho_{\text{obs}}(k)$, the dark line |
| `obs_*_p5`, `obs_*_p95` | grey band edges |
| `syn_raw_mean`, `syn_anomaly_mean` | $\bar\rho_{\text{syn}}(k)$, the red line |
| `syn_*_sem` | standard error of the red line, $s/\sqrt{N}$ |
| `raw_inside_band`, `anomaly_inside_band` | whether red is within the grey band at that lag |

τ is not in the CSV. It is printed by `print_report` and shown in the figure title.
