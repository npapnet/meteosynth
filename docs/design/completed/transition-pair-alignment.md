# Why transition pairs must be matched by date, not by position

Status: explainer · Author: N. Papadakis · Date: 2026-07-15

> **Archive note.** Moved to `docs/design/completed/` on 2026-07-22. The fix this
> document argues for landed alongside [rolling-day-window](rolling-day-window.md)
> on 2026-07-15 (`214250c`); the order-invariance regression test it specifies is in
> `tests/test_transition_pairs.py` and passes.

This document explains a bug that is **hiding** in `generators.py` right now. It is not
causing trouble today. But the rolling-day-window feature
([rolling-day-window](rolling-day-window.md)) is exactly the kind of code that would wake it up, and when
it wakes up it does something genuinely nasty: it produces wrong answers **without any
error message at all**.

It is worth understanding properly, so this document starts from the very beginning and
assumes nothing.

## What are we even trying to learn?

We want the computer to learn a rule like:

> *"If the sunlight at 4am was X, what is the sunlight at 5am likely to be?"*

To learn that, we need lots of **examples** of "4am and 5am **on the same day**". Like
this:

| the day | sunlight at 4am | sunlight at 5am |
|---|---|---|
| 1 Jan 2011 | 0 | 0 |
| 2 Jan 2011 | 0 | 12 |
| 3 Jan 2011 | 0 | 9 |

Each row is one **pair**: a `previous` value and a `current` value. Feed the computer a
few dozen pairs and it can learn the rule.

The important word is **"on the same day"**. Pairing 4am on Tuesday with 5am on Friday
teaches the computer nothing — it's just noise. Every pair must come from a single day.

## How the code does it right now

Our weather data is one enormous table. Each row is *one hour of one day*:

| year | month | day | hour | poa_direct |
|---|---|---|---|---|
| 2011 | 1 | 1 | 0 | 0 |
| 2011 | 1 | 1 | 1 | 0 |
| … | | | | |
| 2011 | 1 | 1 | 4 | 0 |
| 2011 | 1 | 1 | 5 | 0 |
| … | | | | |

Two years of it — 17,544 rows.

To build the 4am → 5am pairs, `generate_hr_simulator` (in `src/meteosynth/generators.py`)
does something that looks completely sensible. It makes **two piles**:

```python
prev_hour = met_data[met_data["hour"] == 4]   # pile A: every 4am row
cur_hour  = met_data[met_data["hour"] == 5]   # pile B: every 5am row
```

and then **staples them together**:

```python
transition_data = pd.DataFrame({
    "previous": prev_hour[attr_str].values,   # <- .values throws the dates away!
    "current":  cur_hour[attr_str].values,
})
```

Here is the crucial bit. `.values` means *"give me just the numbers, forget which day
each one came from."* So the staple is:

```
 1st number in pile A  <-->  1st number in pile B
 2nd number in pile A  <-->  2nd number in pile B
 3rd number in pile A  <-->  3rd number in pile B
 ...
```

It matches them by **position in the pile**. It never checks that the dates agree. It
*hopes* they do.

## Why does this work today?

Because both piles happen to come out in the same order:

```
pile A (4am):  1 Jan, 2 Jan, 3 Jan, 4 Jan, 5 Jan, ...
pile B (5am):  1 Jan, 2 Jan, 3 Jan, 4 Jan, 5 Jan, ...
                 ^       ^       ^
              staple   staple  staple      ...and they line up. 
```

The rows come out of the file in date order, and filtering keeps that order, so position
#3 in pile A really is the same day as position #3 in pile B. The hope holds.

It's a bit like a bookshelf that stays upright only because nobody has ever bumped into
it. It works — but not for a *reason*. It works by luck.

## The school photo analogy

Imagine you're making the school yearbook. You have two piles:

- **Pile A**: 30 cards, each with a pupil's **name**.
- **Pile B**: 30 **photos** of those same pupils.

Both piles are in alphabetical order, so you staple them together: 1st name to 1st photo,
2nd to 2nd, and so on. Alice's name gets Alice's photo. 

Now your friend "helpfully" **sorts both piles by class** — all the 4A pupils first, then
the 4B pupils. They do it to each pile separately.

Here's the catch. Sorting by *class* only says "4A before 4B". It says **nothing** about
the order of pupils *within* 4A. Alice, Ben and Chloe are all in 4A, so as far as the
sorting is concerned they are **tied** — completely interchangeable. Your friend's
shuffling might leave pile A as *Alice, Ben, Chloe* but pile B as *Ben, Alice, Chloe*.

**Both piles are now correctly sorted by class.** Neither is "wrong". But when you staple
them:

```
Alice's name  <-->  Ben's photo      WRONG
Ben's name    <-->  Alice's photo    WRONG
Chloe's name  <-->  Chloe's photo    fine, by luck
```

And here's the part that should worry you: **both piles still have 30 items.** If you only
check the count, everything looks perfect. The yearbook goes to print with the wrong faces
next to the wrong names.

## Now the real thing: what "sorting" does to our weather data

The rolling-window code adds a `slot` column — the day of the year, 1 to 366. It's very
tempting to sort the window by it, so the days come out neatly in order:

```python
window = window.sort_values('slot')     # looks harmless!
```

But **every slot is a tie**, massively so. Slot 58 means "27 February", and our data has:

- 27 Feb **2011**, 24 hours of it
- 27 Feb **2012**, 24 hours of it

That's **48 rows all carrying `slot = 58`**. As far as the sort is concerned, all 48 are
identical and interchangeable — exactly like Alice, Ben and Chloe all being in 4A.

So what order do those 48 come out in? Here is the answer nobody wants to hear:

```python
>>> inspect.signature(pd.DataFrame.sort_values).parameters['kind'].default
'quicksort'
```

pandas sorts with **quicksort** by default, and quicksort is **not stable**. "Not stable"
is the technical way of saying: *when rows are tied, it makes no promise whatsoever about
what order they end up in.* It is allowed to shuffle them. And it does.

## The actual failing example

This is not hypothetical. Here is a real one, found by sweeping the real dataset — window
centred on **27 February** with n=2, building the 23:00 → 00:00 pairs:

```text
 slot_prev previous_from current_from  slot_cur
        56    2011-02-25   2011-02-25        56
        56    2012-02-25   2012-02-25        56
        57    2011-02-26   2011-02-26        57
        57    2012-02-26   2012-02-26        57
        58    2011-02-27   2012-02-27        58   <-- WRONG
        58    2012-02-27   2011-02-27        58   <-- WRONG
        59    2011-02-28   2011-02-28        59
        59    2012-02-28   2012-02-28        59
        60    2012-02-29   2012-02-29        60

  lengths: 9 vs 9 -> equal, so pandas raises nothing.
```

Look at slot 58. The `previous` pile went *2011 then 2012*. The `current` pile went *2012
then 2011*. **Both are perfectly sorted by slot.** Neither is "wrong". But stapled
together, the computer is now being taught:

> *"Here is what 11pm on 27 Feb **2011** looked like, and here is what midnight on 27 Feb
> **2012** looked like. Learn the rule connecting them."*

Those are **a year apart**. It is pure nonsense, and the computer will dutifully learn it.

Notice that the other slots came out fine — 2011 before 2012, in both piles. That's what
makes this so slippery: it doesn't fail everywhere, it fails *in patches*, wherever
quicksort happened to shuffle the two piles differently.

## Why this is genuinely scary

Look at that last line again:

```text
lengths: 9 vs 9 -> equal, so pandas raises nothing.
```

The two piles are still **the same size**. Sorting doesn't add or remove rows, it only
reorders them. So when the code says:

```python
pd.DataFrame({"previous": prev_hour[attr].values, "current": cur_hour[attr].values})
```

pandas checks *"are these two lists the same length?"* — yes, 9 and 9 — and builds the
table happily. **No error. No warning. No red text.** Nothing anywhere tells you that
some of your pairs are garbage.

The program runs. It produces charts. The charts look plausible. They are wrong.

A bug that crashes is a *good* bug — it tells you it exists. This is the other kind.

Across the whole dataset, sweeping all 366 possible window targets:

| what the code does | mispaired rows | errors raised |
|---|---|---|
| leaves the window alone | 0 | 0 |
| `.sort_values('slot')` | **26,808** | **0** |
| `.sort_values('month')` | **54,017** | **0** |

Fifty-four thousand wrong pairs, in total silence, from adding one reasonable-looking
line of code.

> **Note**
>
> To be completely clear: **today's code is not broken.** Nobody sorts, so nothing
> mispairs. The problem is that today's code is only correct by *accident*, and the accident
> is easy to break. The rolling-window feature adds a `slot` column that is practically an
> invitation to sort by it. We are about to hand someone a loaded foot-gun.

## The fix: staple by date, not by position

The whole problem is that `.values` throws the dates away and trusts the piles to line up.
So: **don't throw the dates away.** Keep them, and use them to do the matching.

We already have a function that does exactly this — `convert_to_daily_wide` in
`met_data_processor.py`. It reshapes the data so that **each row is a whole day** and each
column is an hour:

| date_str | 0 | 1 | 2 | 3 | 4 | 5 | … | 23 |
|---|---|---|---|---|---|---|---|---|
| 20110101 | 0 | 0 | 0 | 0 | 0 | 0 | … | 0 |
| 20110102 | 0 | 0 | 0 | 0 | 0 | 12 | … | 0 |
| 20110103 | 0 | 0 | 0 | 0 | 0 | 9 | … | 0 |

Now getting the 4am → 5am pairs is just:

```python
previous = wide[4]      # the 4am column
current  = wide[5]      # the 5am column
```

And **look what happened to the problem.** The 4am value and the 5am value are *in the
same row*. They came from the same day because they are physically sitting on the same
line of the table. There is no "pile A" and "pile B" to fall out of step. There is no
staple. There is nothing to line up.

The pairing is now correct **by construction**, not by luck:

- **Sort it however you like** — rows move as whole units, so 4am and 5am travel together.
  Sorting can never separate them.
- **A day with missing hours** gets a blank, and `dropna` removes just that one day,
  instead of shifting every later pair by one and corrupting the lot.
- **A duplicated hour** makes `pivot` raise a loud error, instead of silently sailing on.

The bookshelf now stands up for a *reason*.

> **Note**
>
> **Pivot once, not 24 times.** Reshaping is cheap but not free: doing it inside each of the
> 24 hourly models costs 635 ms, versus 20 ms if done once and shared. Since fitting all 24
> KDEs only takes 58 ms, the naive version would spend **12× more time reshaping than
> learning**. So the reshape happens once in `EnvSeriesGenerator.__init__` and the wide
> table is passed down.

## Does the fix change any results?

**No — and that's checked.** The new construction was compared against the old one on a
month subset, for all 24 hours: the numbers come out **bit-for-bit identical**. This is a
change to *how* the pairs are built, not *which* pairs are built. Existing users see
exactly the same output.

That includes one existing oddity that is deliberately kept. Because of
`hour_prev = (hour - 1) % 24`, the "previous" for hour 0 is hour **23 of the same day** —
not 11pm the night before, as you'd probably expect. The wide version reproduces this
faithfully (`wide[23]` and `wide[0]` are the same row), which is precisely what lets us
prove nothing else changed. Fixing that quirk is a one-line `.shift(1)` and a separate
conversation — see [rolling-day-window](rolling-day-window.md).

## The test that keeps it fixed

One test matters more than the others:

```python
def test_pairs_are_order_invariant():
    window = mdp.get_day_window_subset(month=2, day=27, n_days=2)
    a = build_pairs(window, hour=0)
    b = build_pairs(window.sample(frac=1, random_state=0), hour=0)   # shuffled!
    assert_frame_equal(a.sort_values(...), b.sort_values(...))
```

Shuffle the input; the pairs must not change. That's the whole property, in one line.

This test **fails on today's code and passes on the fixed code.** It is the executable
proof that the foot-gun is unloaded — and, more importantly, it means that if someone in
2027 "optimises" the pairing back to the positional version, the test suite tells them
immediately, instead of letting them publish a paper with 54,000 nonsense training pairs
in it.
