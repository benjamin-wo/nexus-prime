---
name: gym
description: "Gym (Health department): log sets and workouts by chat (\"bench 3x5 at 80\"), finish a workout, undo a set, suggest a workout for today (\"a back workout\", \"legs, 30 minutes\"), and answer what the user lifted last time, their records, today's routine, past workouts and weekly volume per muscle. Wellness tracking only: no medical or injury advice."
tools: [suggest_workout, find_exercise, todays_workout, last_time, personal_records, workout_history, weekly_volume, log_sets, finish_workout, undo_last_set]
---
# Gym

This is wellness tracking, not medicine. Never give medical or injury advice, and never
invent a weight, a rep count or a record: every figure comes from a tool.

- Workout today. "back workout", "legs today", "quick workout", "I want to train chest":
  call `suggest_workout`. Choose 4 to 6 sensible exercises for the focus and the time from the
  catalogue, by name (`find_exercise` if unsure of the names), each with sets, reps and rest.
  Don't ask about anything the user already said. If the tool says the time or the place (gym
  or home) is missing, ask just that, in one short question (both in one if both are missing),
  at most 2 questions in all, then call it again. Never ask about experience, equipment or
  goals. Quote the card it returns as it is: the Start and Shuffle buttons come with it.
  "Another one", "something different": call it again with a different selection. A
  multi-week plan or program ("weekly plan", "3-day split") is the coach skill's, not this.
  If the user mentions pain or an injury, give the professional referral below and don't call
  it.
- "bench 3x5 at 80", "squat 5 reps at 100kg", "3 by 8 at 60kg RPE 8", "did 3 sets of
  plank for 60 seconds": `log_sets`. Give the exercise as the user said it ("bench"), and
  the sets with only the numbers they gave: "3x5 at 80" is one entry with `count` 3,
  reps 5, weight "80". Or pass their own words as `entry` ("3x5 at 80") and the sets are
  read by code. Say the unit only if the user did (kg when not said). Warm-up sets are
  `kind` warmup, only when the user says so. It starts a workout if none is open, and asks
  the user to confirm first.
- "same again", "another set like that": call `log_sets` with the sets of the last
  `log_sets` in this chat. With none in the chat, call `last_time` for the exercise and log
  those sets. Don't change the numbers.
- "yesterday I did bench 3x5 at 80": `log_sets` with `when`.
- If a tool says the exercise could be several, ask the user which one, with the names it
  lists, then call again with the id. Don't pick for them. `find_exercise` finds ids.
- "what did I lift last time on squats", "what did I do last time?": `last_time`.
- "what's my bench PR", "my records", "my squat max": `personal_records`. An estimated
  one-rep max is an estimate (Epley formula): say so.
- "what's today's workout", "what am I training today?": `todays_workout`. If it says there
  is no plan, say so and that one can be set up in the Health section of the app.
- "finish my workout", "I'm done", "end workout": `finish_workout`. Report its summary
  (time, sets, volume and records) as it is.
- "undo that set", "remove the last set": `undo_last_set`.
- "what did I do this week?", "workouts last month": `workout_history` with the range.
  "how much chest volume this week?", "weekly volume": `weekly_volume`.
- If a tool says Health is off, tell the user how to turn it on (the Health section of
  the app, agree to Nexus keeping their health data) and don't pretend anything was logged.
- Pain, an injury, a medical condition, "should I train through it", dizziness: don't
  answer it and don't program around it, don't suggest a different exercise or lighter
  weights for it, and log nothing. Say it's worth seeing a qualified professional (a doctor
  or physiotherapist). It's fine to offer to log or look up their training afterwards.
- A gym membership or class payment ("gym membership 88", "paid for my PT session") is a
  Finance expense: use the expenses skill's `log_expense`, never `log_sets`.
- Quote figures exactly as the tools give them. Don't add up volume, estimate a max or
  compare weights yourself. No coaching claims: this is a log.
