# Evaluation: reply styles (26 October 2026)

Branch `claude/adoring-lamport-4a97mv` at `5be03a2`: reply styles (presets default, chill, direct, hype and cheeky, plus dials and a note; `set_voice` and `show_voice`; migration 0058) and the rule against stock phrases. Every run used `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low`. The data is made up (the seeded eval user).

## Full set (261 cases, default voice)

| Run | Passed | Median reply | p90 | Cost | Cost a case |
|---|---|---|---|---|---|
| 1 | 257/261 | 1.7s | 3.7s | $0.304 | $0.00117 |
| 2 | **260/261** | 1.7s | 4.1s | $0.312 | $0.00120 |

Baseline (main, today): 254/258, median 1.9s. The branch adds three voice cases, which passed in both runs.

Failures:

| Case | Runs | Why |
|---|---|---|
| `trip-set-aside` | 1, 2 | "put aside 400 each payday for the japan trip" made a monthly bill named "Japan trip" (`add_bill`) instead of calling `update_trip` with `set_aside`, and didn't ask to confirm first. This is a wrong action, in both runs. |
| `log-two-at-once` | 1 | "kopi 1.80 and kaya toast 2.50" logged both as merchant "Kopitiam", so "kaya toast" isn't mentioned on the 2.50 expense. |
| `trip-find-in-stop` | 1 | `find_ideas` was called without the Kyoto stop, and the lookup reported being down. |
| `wallet-find-likely-moves` | 1 | Eight `find_transactions` and `query_ledger` searches instead of `find_likely_moves`. Its answer, that nothing was found, may still be right. |

Logged noise that didn't fail a case: three memory-writer replies hit the 1,500-token limit (one of them was all reasoning) and were retried. In run 2, the photo model once returned a list of receipts where `ReceiptDraft` expects a single object; every receipt case still passed.

## Voice cases and `mem-short-replies` (3 runs each)

| Case | Runs passed |
|---|---|
| `voice-direct` | 3/3 |
| `voice-cheeky` | 3/3 |
| `voice-default-no-stock` | 3/3 |
| `mem-short-replies` | 2/3 |

Medians were 1.4–1.7s. The `mem-short-replies` failure was 165 characters against the 160 cap: the spending answer plus an extra line, "Dining Out's at 143.90 of your 300 budget, so you're fine there." The other two runs gave 99 and 106 characters.

## Tone samples

Each sample ran on its own freshly seeded user. The user first sent the voice's ask; the message then went in a new conversation. The default voice had no ask. Every action was graded by hand from the tool calls.

What each ask did:

- **chill:** `set_voice(preset=chill)`. Reply: "Chill mode on 😎".
- **direct:** "keep it short, no emoji" became `set_voice(length=short, emoji=none)` (dials, not the `direct` preset). Reply: "Done."
- **hype:** `set_voice(preset=hype)`. The confirmations ran long (up to about 300 characters), with three to four emoji, and recited the month's figures unprompted.
- **cheeky:** `set_voice(preset=cheeky)`. Reply: "Cheeky mode on. Go on then, hit me with your spending sins 😏".

| Message | default | chill | direct | hype | cheeky |
|---|---|---|---|---|---|
| grab 12 | "Grab 12.00 ✅ Transport's at 108.30 this month." | "Grab 12.00 ✅ Transport's at 108.30 this month." | "Grab 12.00 logged under Transport." | "Grab ride logged — 12.00 under Transport ✅" | "Grab 12.00 ✅ Transport's at 108.30 this month — the car's earning its keep." |
| bubble tea 6.50 | "6.50 bubble tea ✅ Dining Out's at 150.40 of 300 this month." | "6.50 bubble tea ✅ Dining Out's at 150.40 of 300 now." | "6.50 bubble tea, under Dining Out." | "Bubble tea 6.50 ✅ Dining Out's at 150.40 of 300 now 🧋" | "6.50 for bubble tea ✅ That's 150.40 of your 300 Dining Out budget — still plenty of pearls left this month." |
| i paid the rent | "Rent's done ✅ 1,800 logged, and October's bill is marked paid." | "Rent's done ✅ 1,800 logged." | "Rent's done for October, 1,800 logged." | "Rent's sorted ✅ 1,800 logged, and that's the big one off the board for October." | "Rent's sorted ✅ 1,800 out the door, and that's the big one for October done." |
| how's my dining out budget looking | "Dining Out's at 143.90 of 300 — 47% used, 156.10 left with a few days to go. Comfortable ✅" | "Dining Out's at 143.90 of 300 — 47% used, 156.10 left. Plenty of room 👍" | "Dining Out's at 143.90 of 300, so 156.10 left with a few days to go. Comfortable." | "Dining Out's at 143.90 of 300 — 156.10 still in the tank 🎉 Halfway through the month and not even at 50% used." | "Looking good — 143.90 of 300 used, so 156.10 still in the tank 🎉 That's 47% with only a few days left in September. Your kopi habit's not even making a dent." |
| dinner 60 at din tai fung | "60 at Din Tai Fung ✅ Dining Out's at 203.90 of 300 this month." | "60 at Din Tai Fung ✅ Dining Out's at 203.90 of 300 now." | "60 at Din Tai Fung logged under Dining Out. That's 203.90 of your 300 dining budget this month." | "60 at Din Tai Fung ✅ Dining Out's at 203.90 of 300 now — still comfy for the rest of the month 🎉" | "60 at Din Tai Fung ✅ Dining Out's at 203.90 of 300 now — still room, but the xiao long bao are doing their best." |
| i went over budget this month, feeling bad | "Good news — you haven't actually gone over. The only budget you've set is Dining Out, and it's at 143.90 of 300, so 156.10 still there. Total spend this month is 460.03, against 5,000 in. Nothing's blown. If it's the overall picture that's bugging you, want me to set a monthly budget so there's a line to measure against?" | "Good news — you're not actually over anything. Only budget you've got is Dining Out, and it's at 143.90 of 300 (47%). Total spend this month is 460.03, against 5,000 in. You're fine 🙂 Want me to set an overall monthly budget so there's a line to watch?" | "You're not over, actually. Dining Out's at 143.90 of 300, so 156.10 left, and there's no overall budget set to blow. If it feels tight, it's probably the 1,800 rent landing Thursday. Want me to set an overall monthly budget so you can see the whole picture?" | "Good news — you haven't actually gone over anything 🎉 Your only budget is Dining Out, and it's at 143.90 of 300 (47%), with 156.10 still left. Total spend this month is 460.03 against 5,000 in — that's a pretty tidy month, honestly. Want me to set an overall monthly budget so you've got a line to watch?" | "Good news — you're not actually over. The only budget you've got running is Dining Out: 143.90 of 300, so 156.10 still there. If it's the overall month that's bugging you, you've spent 460.03 so far — want me to set an overall budget so there's a line to watch?" |

Actions: every voice did the same thing. `log_expense` ran for Grab (Transport), bubble tea (Dining Out) and Din Tai Fung (Dining Out). "i paid the rent" ran `mark_bill_paid(Rent)`. The budget question was answered from the money snapshot without a tool call. "feeling bad" ran `list_budgets` (and `spending_summary` in some voices) and changed nothing. **No wrong actions in the tone samples.**

## Flags

- **Stock phrases (the main finding).** "Noted" is on the banned list, yet the model opened with it in three full-set cases, in both runs:
  - `trip-note`: "Noted on the Japan trip ✅"
  - `trip-they-paid`: "Noted — Ann's 460 for the ryokan, …"
  - `mem-episode`: "Noted the 42.10 Grab ride as work ✅"

  Only `voice-default-no-stock` checks for these phrases, so the full set doesn't catch the leak. The hype ask in `tone-hype-3` said "a budget absolutely behaving itself": the word, though not the stock "Absolutely!" opener. No "Fair enough", "Certainly", "Understood", "Great question" or "I hope this helps" anywhere.
- **"Feeling bad".** Nothing unkind or teasing in any voice. Cheeky dropped the jokes and every voice reassured with the actual figures. One small mismatch: hype opened with 🎉 ("you haven't actually gone over anything 🎉") on a message about feeling bad.
- **Emoji in direct.** None, in all six replies or the ask ("Done.").
- **Factual slips:**
  - Hype said "Halfway through the month" on 28 September, when only a few days were left.
  - Cheeky's "the car's earning its keep" for a Grab ride implies the user owns a car.
- **Voice strength.** Hype mostly shows in the ask's confirmation; its later replies are close to default, with one or two extra emoji. Chill is near-identical to default. Direct ("keep it short") gave a 2–3 sentence answer to "feeling bad", which is reasonable for that message.
- **Wrong action in the full set.** `trip-set-aside` (above) created a recurring bill instead of a trip set-aside, without confirming, in both runs.
