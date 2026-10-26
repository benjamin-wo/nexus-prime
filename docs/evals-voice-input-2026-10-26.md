# Evals: voice input, 2026-10-26

Branch under test: `claude/adoring-lamport-4a97mv` at `2e6bb72` ("WIP: voice input backend,
evals, docs; raw AAC sent as aac"). No code was changed.

Flags: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks
--vision-model qwen/qwen3.8-flash --reasoning low`, speech model left at its default
(`openai/gpt-4o-mini-transcribe`, fallback `openai/whisper-large-v3-turbo`).

## Summary

- **Full set: 271/274** (the 261 cases on main plus 13 new voice-note cases). Everything
  outside the voice notes passed: 258/258, against today's baseline of 257–260/261 on main.
  Reply time per turn: median 1.9 s, p90 3.7 s. Cost $0.4706 ($0.00172 a case; this is the
  chat, photo and memory models and does not include speech-to-text).
- **Failing ids** (the same three in all four runs): `voice-bill-savings`,
  `voice-split-clean`, `voice-split-noisy`.
- **Voice notes, 3 runs of `--case voice-`:** 10 of 13 voice-note cases pass 3/3; the three
  above fail 3/3. None of the three failures is a mishearing (see Flags).
- **Voice-turn time** (transcription + reply, as the runner times `handle_voice`, 39 turns):
  median **2.38 s**, p90 **6.2 s**. The p90 is the two split cases, which take a confirm
  press as well (5.9–7.4 s); without them the median is 2.2 s. Transcription alone (timed
  separately, 39 calls): median 0.52 s, p90 0.73 s.
- **Transcription cost per note:** mean **$0.000153** (range $0.000114–$0.000186 for clips of
  2.3–5 s), about $0.002 for the 13 notes. Every call was answered by the primary model;
  the fallback was never used. OpenRouter returned no `usage.seconds` (only `cost`), so the
  log line prints "? s of audio".
- **Amounts:** every amount logged was right in every run. No heard line on a question; a
  heard line on every write except the two splits (see Flags).

`--case voice-` also matches three older cases about Nexus's tone (`voice-direct`,
`voice-cheeky`, `voice-default-no-stock`). They have no audio and passed 3/3; they're left out
of the tables below.

## Voice-note cases

Transcripts: the speech model's output after `tidy_transcript` (home currency SGD). They were
identical in all three runs, and in a separate pass of each clip three times through the
same `OpenRouterSpeech` + `tidy_transcript` path. The eval JSON doesn't store the transcript,
so that pass is where the raw text comes from; the heard lines in the replies match it.

| Case (clip) | Passes | Raw → tidied transcript | Logged |
|---|---|---|---|
| `voice-grab` (grab-us-clean) | 3/3 | `Grab $12.50.` → `Grab 12.50.` | expense 12.50 Grab, Transport |
| `voice-grab-noisy` (grab-gb-noisy) | 3/3 | `Grab $12.50.` → `Grab 12.50.` | expense 12.50 Grab, Transport |
| `voice-lunch-maxwell` (maxwell-in-clean) | 3/3 | `Lunch at Maxwell 8:40.` → `Lunch at Maxwell 8.40.` | expense 8.40 Maxwell, Dining Out |
| `voice-lunch-maxwell-noisy` (maxwell-in-noisy) | 3/3 | `Lunch at Maxwell, $8.40.` → `Lunch at Maxwell, 8.40.` | expense 8.40 Maxwell, Dining Out |
| `voice-taxi-last-friday` (taxi-in-clean) | 3/3 | `Taxi home, $23.50, last Friday.` → `Taxi home, 23.50, last Friday.` | expense 23.50 Taxi, Transport, dated 2026-09-25 |
| `voice-netflix` (netflix-in-clean) | 3/3 | `$17.99 for Netflix.` → `17.99 for Netflix.` | expense 17.99 Netflix, Subscriptions & Software |
| `voice-laptop` (laptop-au-clean) | 3/3 | `$1.8K for a new laptop.` → `1.8K for a new laptop.` | expense 1800, Shopping (merchant "Laptop" in run 1, none + note "New laptop" in runs 2–3) |
| `voice-rent-paid` (rent-gb-clean) | 3/3 | `Paid the rent.` → `Paid the rent.` | `mark_bill_paid` Rent (logs 1,800) |
| `voice-bill-savings` (savings-gb-clean) | **0/3** | `Move $300 to savings on the 25th.` → `Move 300 to savings on the 25th.` | nothing (refused before the model) |
| `voice-split-clean` (dtf-us-clean) | **0/3** | `Dinner $60 at Din Tai Fung, split with Anne.` → `Dinner 60 at Din Tai Fung, split with Anne.` | expense 60 Din Tai Fung, Dining Out; split half to Anne (run 1) / Ann (runs 2–3) |
| `voice-split-noisy` (dtf-us-noisy) | **0/3** | same as clean | expense 60 Din Tai Fung, Dining Out; split half to Ann (runs 1, 3) / Anne (run 2) |
| `voice-question` (query-us-clean) | 3/3 | `How much did I spend on Grab this month?` (unchanged) | nothing (`query_ledger`) |
| `voice-question-noisy` (query-au-noisy) | 3/3 | same | nothing (`query_ledger`) |

### Replies, run by run

Each reply is the full text the user sees (the heard line is the first line when present).

**voice-grab**
1. 🎙 heard: "Grab 12.50." / Grab 12.50 ✅ Transport's at 108.80 this month.
2. same
3. same

**voice-grab-noisy**
1. 🎙 heard: "Grab 12.50." / Grab 12.50 ✅ Transport's at 108.80 this month.
2. same
3. same

**voice-lunch-maxwell**
1. 🎙 heard: "Lunch at Maxwell 8.40." / 8.40 at Maxwell ✅ Dining Out's at 152.30 of 300 this month.
2. same
3. same

**voice-lunch-maxwell-noisy**
1. 🎙 heard: "Lunch at Maxwell, 8.40." / 8.40 at Maxwell ✅ Dining Out's at 152.30 of 300 this month.
2. same
3. same

**voice-taxi-last-friday**
1. 🎙 heard: "Taxi home, 23.50, last Friday." / Taxi home, 23.50 on Friday ✅ Transport's at 119.80 this month.
2. … / Taxi home, 23.50 on Fri 25 Sep ✅ Transport's at 119.80 this month.
3. as run 1

**voice-netflix**
1. 🎙 heard: "17.99 for Netflix." / Netflix 17.99 ✅ Subscriptions & Software.
2. same
3. same

**voice-laptop**
1. 🎙 heard: "1.8K for a new laptop." / 1,800 for the laptop ✅ Shopping. That's a big one — this month's spending jumps to 2,260.
2. … / 1,800 for the laptop, filed under Shopping ✅ That's a big one — Shopping's now your top category this month by a mile.
3. … / Laptop's in — 1,800 under Shopping ✅ That's a big one, so this month's spending jumps to about 2,260.

**voice-rent-paid**
1. 🎙 heard: "Paid the rent." / Rent's done ✅ 1,800 logged.
2. same
3. same

**voice-bill-savings** (all three, 0.5 s, no model call)
> I can't send or transfer money. I only keep track of it. Once you've moved it yourself,
> tell me ("I moved 500 to savings") and I'll record it. If it's a regular transfer, I can
> remind you before it's due: say "remind me to move 300 to savings every month".

**voice-split-clean** (each: a confirm prompt, pressed, then the reply)
1. Confirm: "… Din Tai Fung · Dining Out: Anne owes 30.00 SGD; your share 30.00 SGD?" → 60 at Din Tai Fung ✅ Anne owes you 30, your share 30. You've also got an "Ann" owing 40 in your IOUs — same person, or two different Ann(e)s?
2. Confirm: "… Ann owes 30.00 SGD …" → 60 at Din Tai Fung ✅ — Ann owes you 30 for it.
3. Confirm: "… Ann owes 30.00 SGD …" → 60 at Din Tai Fung ✅ Ann owes you 30 for it (your half's 30).

**voice-split-noisy**
1. Confirm: "… Ann owes 30.00 SGD …" → 60 at Din Tai Fung logged ✅ Split with Ann — she owes 30, your share's 30. (That's Ann in your contacts, not a new "Anne" — say if it's someone else.)
2. Confirm: "… Anne owes 30.00 SGD …" → Dinner's in: 60 at Din Tai Fung, your half 30, Anne owes 30 ✅
3. Confirm: "… Ann owes 30.00 SGD …" → 60 at Din Tai Fung ✅ — Ann owes you 30 for it.

**voice-question**
1. 96.30 on Grab this month, across 4 rides. Biggest was 42.10 on 27 Sep, then 25.40 on 5 Sep and 16.30 on 6 Sep.
2. 96.30 on Grab this month, across 4 rides (avg 24.08 each).
3. 96.30 on Grab this month, across 4 rides — averaging 24.08 each.

**voice-question-noisy**
1. 96.30 on Grab this month, across 4 rides (avg 24.08 each).
2. 96.30 on Grab this month, across 4 rides. • 42.10 on 27 Sep • 25.40 on 5 Sep • 16.30 on 6 Sep • 12.50 on 2 Sep
3. 96.30 on Grab this month, across 4 rides. Biggest: 42.10 on 27 Sep, then 25.40 on 5 Sep and 16.30 on 6 Sep.

### Voice-turn seconds (transcription + reply)

| Case | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| grab | 2.95 | 2.72 | 3.32 |
| grab-noisy | 1.98 | 3.22 | 2.20 |
| lunch-maxwell | 2.19 | 2.02 | 2.11 |
| lunch-maxwell-noisy | 2.81 | 3.17 | 2.66 |
| taxi-last-friday | 2.59 | 2.12 | 2.17 |
| netflix | 1.96 | 2.18 | 2.69 |
| laptop | 4.12 | 2.24 | 2.72 |
| rent-paid | 2.12 | 3.15 | 1.99 |
| bill-savings | 0.52 | 0.53 | 0.50 |
| split-clean (incl. confirm) | 6.54 | 6.38 | 6.19 |
| split-noisy (incl. confirm) | 6.25 | 6.09 | 6.77 |
| question | 2.24 | 2.41 | 2.38 |
| question-noisy | 2.06 | 1.86 | 1.95 |

## Flags

1. **`voice-split-*` fail on the check, not on the behaviour.** The seed already has Ann owing
   40.00 (the Jumbo Seafood dinner split three ways, `seed.ANN_OWES`), and `Owes` sums all of
   a person's open IOUs. A correct split leaves Ann owing 70.00, so `Owes("Ann", "30.00",
   also=("Anne",))` can never hold. The amounts were right every time: 60 logged, half
   (30.00) to Ann/Anne. The check needs 70.00 (or to look at the new IOU only).
2. **"Anne" vs "Ann" splits a person's debt in two.** The speech model always writes "Anne".
   In 3 of 8 split turns (voice runs 1-clean, 2-noisy and the full run's noisy) the model
   split with a new "Anne" instead of the existing Ann, so her 30 sits apart from her 40.
   Once it asked whether they're the same person; once it said nothing about it. In the other
   5 it mapped to Ann itself. The `also=("Anne",)` in the check hides this. Worth fixing in
   the product (offer the existing near-match name) rather than the check.
3. **No heard line on a split, which is a write.** `handle_voice` adds the heard line only
   when its *first* reply carries Undo. A split's first reply is the confirm prompt, and the
   reply after the press comes from `press()`, so the transcript is never shown although data
   changed. The case comment says this is deliberate ("a write that asks to confirm first
   changes nothing in the voice turn"), but from the user's side the confirm prompt and the
   write never show what was heard, and the mishearing here ("Anne") is exactly the kind the
   line exists to catch. The prompt does show "Anne owes…", which helps.
4. **`voice-bill-savings` is refused by a regex before the model.** The tidied transcript
   "Move 300 to savings on the 25th." matches the second `transfer` pattern in
   `agent/kernel.py` (a one-off "move N to …" with no "every/monthly/remind"), so it gets the
   canned "I can't send or transfer money" reply in 0.5 s: no model, no write, no heard line.
   The transcript is exact; typed, the same sentence would be refused the same way. Either
   the clip/case expectation is off (the typed twin, `plan-regular-transfer`, says "…on 25 oct every
   month"; the clip has no word for recurring), or the kernel should leave a dated "move N to
   savings on the 25th" to the model. Not a speech problem.
5. **Tidied transcripts:** nothing wrong. `8:40` → `8.40` worked (the clean Indian-English
   clip is the only one where the model dropped the `$` and wrote a time). `1.8K` is left as
   `1.8K` and the chat model reads it as 1800 every time. The `$` the speech prompt asks for
   is stripped each time, so no transcript carries a currency symbol. The heard line keeps
   the transcript's full stop ("Grab 12.50."), which reads a little oddly in quotes.
6. **No heard line on a question:** confirmed, 6/6 question turns plus the full run.
7. **Minor:** the "Openers after a change" stat in the eval report now counts the heard
   line, so it reports openers like "heard grab" 13% / "heard for" 13% in the voice runs.
   The opener measure should skip the heard line.

## Raw numbers

| Run | Passed | Median | p90 | Cost |
|---|---|---|---|---|
| `--case voice-` run 1 | 13/16 | 2.1 s | 5.8 s | $0.0210 |
| `--case voice-` run 2 | 13/16 | 2.1 s | 5.5 s | $0.0221 |
| `--case voice-` run 3 | 13/16 | 2.2 s | 5.6 s | $0.0213 |
| full set | 271/274 | 1.9 s | 3.7 s | $0.4706 |

(The voice runs' 16 cases include the three tone cases; their median/p90 are per turn,
tone turns included. Costs leave out speech-to-text, which is listed above.)
