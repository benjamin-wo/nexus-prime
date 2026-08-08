# Nexus Prime — Capability Recipes (Orchestration Catalog)

Recipes are multi-tool orchestration plans composed from the flat capability
registry. Each one lists the tools, the order, the guardrails, and what is
missing. The deterministic planner expresses the fixed-shape recipes; the LLM
planner expresses open-ended ones. Anything marked "needs X" is a candidate
for the C7 promotion pipeline.

Implemented in `orchestrator/recipes.py` with planner triggers in
`orchestrator/planner.py` (recipe decisions run before generic routing).

Legend: ✅ composable today · 🔶 needs a small new tool/data · 🔴 needs a new
integration (gap record today).

---

## R1. Morning Briefing — ✅ built

**Triggers:** "good morning", "what's up today", "brief me"

**Tools (order):** email scan → expenses (auto-log found receipts) → reminders
(today's schedule) → routes (ETA to work) → general (weather/headlines)

**Flow:** inbox receipts get logged silently; the reply is a capped digest:
2-3 expense hits, today's reminders, commute ETA, one-line weather. No action
is taken without a user ask.

**Guardrails:** read-only except email label writes; hard cap on length;
ambient quiet hours apply if scheduled.

**Missing:** a `briefing` manifest is optional — the LLM planner can compose
it directly from the shortlist.

---

## R2. Spend Autopsy — ✅ built

**Triggers:** "where did my money go last month", "top 5 merchants",
"analyze my spending"

**Tools (order):** expenses (fetch transactions) → code_exec (sandboxed
aggregation by merchant/category/month) → general (plain-language summary)

**Flow:** the sandbox runs the aggregation script (no network, no vault), the
result is summarized conversationally. This gives `code_exec` its first
high-value production use.

**Guardrails:** generated code runs in the sandbox only; no writes to
expense data; HITL not needed (read-only).

---

## R3. Grocery Run — ✅ built

**Triggers:** "I need groceries", "plan my grocery run"

**Tools (order):** recipes (current grocery list) → routes (route to the
supermarket) → reminders (remind before leaving / at store) → general
(weather: will it rain?)

**Flow:** returns the list, the fastest route, and one reminder set with
user confirmation.

**Guardrails:** reminder creation is a write → inline confirm button; store
preference can be a data-only profile field.

---

## R4. Commute + Conditions — ✅ built

**Triggers:** "what's my commute like tomorrow at 8", "leave early if it rains"

**Tools (order):** routes (ETA + transit steps) → general (weather via web
search) → reminders (optional leave-early reminder) → ambient (delivery gate)

**Flow:** route ETA plus weather, with a conditional reminder that respects
quiet hours.

---

## R5. Bill Watch — ✅ built (scan + listing)

**Triggers:** "track my bills", "when is the M1 bill due", "did I pay the rent?"

**Tools (order):** email (scan for bills/receipts) → expenses (match against
logged payments) → reminders (due-date reminders) → code_exec (optional
monthly comparison)

**Flow:** finds the bill email, checks whether a matching expense is logged,
creates a reminder with confirmation. Unmatched bills become gap records.

**Guardrails:** HITL before creating reminders; amount comparison is
read-only; "pay " never triggers a transfer refusal here (planner-level
missing-policy already scopes this).

**Built:** email scan for bill-like messages, recent-payments listing, and
reminder listing. **Remaining:** bill↔payment matching and due-date reminders
need bill due-date extraction from email bodies (see requirements below).

---

## R6. Travel Day — 🔶 needs additions

**Triggers:** "my flight is Friday", "I'm travelling to Tokyo next week"

**Tools (order):** email (find itinerary/booking confirmation) → reminders
(check-in, leave-for-airport) → routes (route to airport timed to leave) →
timezone (switch on arrival) → general (destination weather)

**Flow:** extracts the flight time from email, plans the airport route with a
leave-early reminder, and prepares the timezone switch.

**Needs:** itinerary extraction (small LLM tool over the email summary) and
flight-detail storage. Booking remains a gap record (`flight_booking`).

---

## R7. Payday Flow — 🔶 needs additions

**Triggers:** "did my salary come in?", "payday"

**Tools (order):** email (salary credit detection) → expenses (log expected
standing payments?) → reminders ("split bills Friday") → budget (gap record)

**Flow:** confirms the credit, creates the split-bills reminder, and names the
missing budget capability instead of faking a forecast.

**Needs:** salary-credit pattern in the email summary (small classifier over
the existing email output).

---

## R8. Dinner Party Planner — 🔶 needs additions

**Triggers:** "plan dinner for 4 on Saturday", "what should I cook tonight"

**Tools (order):** general (web search recipes) → recipes (parse + grocery
list) → routes (supermarket) → reminders (shop/cook times) → expenses
(estimate ingredients cost)

**Flow:** picks a recipe for the guest count, diffs ingredients against the
current list, adds only missing items, sets reminders, and estimates cost.

**Needs:** recipe "diff vs grocery list" (small addition to the recipes
plugin) and a cost estimate (LLM, non-binding).

---

## R9. Kitchen Inventory → Meal — 🔶 needs additions

**Triggers:** "what can I cook with eggs, tomatoes, onion?"

**Tools (order):** recipes (inventory state) → general (recipe search) →
code_exec (match ingredients) → recipes (add missing items to list)

**Needs:** a persistent inventory list (data-only extension of the grocery
list or a new manifest).

---

## R10. Refund / Dispute Tracker — 🔶 needs additions

**Triggers:** "did I get refunded for the flight?", "track my refunds"

**Tools (order):** email (refund/credit emails) → expenses (match against
logged purchase) → reminders (nudge if refund not received in N days)

**Needs:** refund-classification in the email tool and a match window.

---

## R11. Home Arrival — 🔴 needs integration

**Triggers:** "turn on the lights when I get home", "cool the flat before I arrive"

**Tools (order):** routes (arrival ETA/geofence trigger) → ambient (trigger
invokes the agent) → smart_home (execute) → reminders (fallback)

**Status:** smart_home is a registered gap tag today; the ambient trigger
machinery exists. Requires the home-integration provider before this recipe
can execute.

---

## R12. Health Check-in — 🔴 needs integration

**Triggers:** "weekly health summary", "how's my sleep this week"

**Tools (order):** general (wearable data via future connector) → expenses
(fitness spend) → reminders → ambient

**Status:** needs wearable/health integrations; today it logs the gap tag.

---

## Implementing a recipe

1. **Fixed-shape recipes:** add a planner rule (deterministic) or let the LLM
   planner compose from manifest descriptions.
2. **New tools:** draft a manifest, run it through `orchestrator/promotion.py`
   (validation → approval → `skills-lock.json` provenance → rollback).
3. **Guardrails:** every write step needs HITL (`interrupt()`), every refusal
   emits a gap record, every claim needs a trace.
4. **Probes:** extend the replay set with the recipe's trigger phrases and add
   a probe trace (input → retrieval → decision → tool calls → final text).
