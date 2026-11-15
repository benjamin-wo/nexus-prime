# Routing and Surfacing Accuracy: deciding which domain(s) and which UI to show, when

Scope: how Prime (a single LangGraph tool-calling agent on a cheap, fast open-weights model) can reliably decide which domain panels (Finance, Travel, later Health and others) to surface, handle multi-domain turns, time the surfacing, decide when to be proactive, and measure all of this. Research date: 2026-11-14. Note on access: arxiv.org and blog.langchain.com could not be fetched from this session (network allowlist), so figures from those sources come from search-result abstracts and summaries and are flagged as such. Exact numbers should be checked against the primary PDFs before they are quoted in a decision document.

## Q1. Approaches (derive UI from tool calls / router-classifier / explicit "show panel" tool / supervisor or multi-agent): what evidence exists on accuracy, latency, cost, and degradation as tool count grows?

### Takeaway
No published benchmark measures "which UI panel to show" directly. The closest evidence is on tool selection and multi-agent routing. Accuracy falls as the number of tools and domains in context grows, and narrowing the candidate set (tool search or retrieval, on-demand skills, sub-agents) recovers much of that loss. For Nexus, the most accurate and cheapest default is to derive panels deterministically from the domain tools Prime actually calls, which costs no extra model decision. An explicit `show_panel` tool and a lightweight embedding router can supplement it for turns where no tool is called. Supervisor or multi-agent routing is not needed at Nexus's current size, and it has measurable "translation" costs.

### Cited Findings

**Tool count degrades selection accuracy**
- Anthropic, Nov 24 2025: "The most common failures are wrong tool selection and incorrect parameters, especially when tools have similar names" (example: `notification-send-user` vs `notification-send-channel`). In Anthropic's internal MCP evaluations, the Tool Search Tool raised Opus 4 from 49% to 74% and Opus 4.5 from 79.5% to 88.1%. In a 58-tool, five-server example, context dropped from about 77K to about 8.7K tokens, an 85% reduction. — [Anthropic Engineering, "Introducing advanced tool use"](https://www.anthropic.com/engineering/advanced-tool-use)
- Anthropic's guidance on when tool search helps: tool definitions over about 10K tokens, tool-selection accuracy problems, multiple MCP servers, or 10+ tools. It helps less with fewer than 10 tools, when every tool is used in every session, or when definitions are compact. It recommends: "Keep your three to five most-used tools always loaded, defer the rest" (via `defer_loading`). — [Anthropic Engineering](https://www.anthropic.com/engineering/advanced-tool-use)
- Tool Use Examples (1–5 example calls per tool) improved accuracy on complex parameter handling from 72% to 90% in Anthropic's internal testing. — [Anthropic Engineering](https://www.anthropic.com/engineering/advanced-tool-use)
- RAG-MCP (Gan and Sun, arXiv 2505.03275, May 2025) ran a needle-in-a-haystack stress test: one correct tool schema among N−1 distractors, with N increasing. Retrieving the top-k tools semantically and injecting only the best one more than tripled selection accuracy (43.13% vs a 13.62% baseline) and cut prompt tokens by more than 50%. The paper also says retrieval precision degrades as the registry grows to thousands of tools. A secondary summary reports baseline accuracy falling "from 85% with 5 tools to 45% with 20 tools"; that figure is unverified against the paper. — [arXiv abstract 2505.03275](https://arxiv.org/abs/2505.03275v1); secondary: [alphaXiv overview](https://www.alphaxiv.org/overview/2505.03275v1)
- Berkeley Function Calling Leaderboard (BFCL) V3 added multi-turn and multi-step evaluation (1,000 expert-labeled multi-turn conversations across eight API domains). It also weights relevance and irrelevance detection: the model gets only irrelevant functions, and the correct behavior is to call none. One reported multi-turn failure mode is "Empty Turn Response", where no function is called when one was needed. — [Gorilla BFCL blog](https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html); [HF dataset card](https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard)
- A secondary source gives BFCL V4's weighting as 10% non-live single-turn, 10% live, 10% irrelevance, 30% multi-turn and 40% agentic. Epoch AI's audit of 50 sampled items rated BFCL v4 "Flawed", flagging label noise in irrelevance and multi-turn items. — [Emergent Mind BFCL v4 topic](https://api.emergentmind.com/topics/berkeley-function-calling-leaderboard-v4-bfclv4); [Epoch AI benchmark review](https://epoch.ai/benchmarks/berkeley-function-calling-leaderboard/review)

**Supervisor / swarm / single-agent routing**
- LangChain, June 10 2025, "Benchmarking Multi-Agent Architectures": a modified τ-bench (retail) with six added distractor domains (home improvement, tech support, pharmacy, automotive, restaurant, Spotify), first 100 retail test examples, and an increasing number of distractor domains. Results:
  - The single-agent baseline drops sharply at two or more distractor domains.
  - Swarm slightly outperforms supervisor across the board. The authors attribute the supervisor's gap to "translation" errors, because sub-agents cannot answer the user directly.
  - Single-agent token use rises with the number of distractor domains; swarm and supervisor stay roughly flat, and supervisor uses more tokens than swarm.
  - Tuning the supervisor gave a "nearly 50% increase" in performance. The tuning included removing handoff messages and letting sub-agents forward their messages to the user directly.
  - A secondary summary (plushcap) contradicts the swarm-leads finding; the primary post should be preferred.
  — [LangChain blog](https://blog.langchain.com/benchmarking-multi-agent-architectures) (could not fetch; findings from search summary); conflicting secondary: [plushcap summary](https://www.plushcap.com/content/langchain/blog/langchain-benchmarking-multi-agent-architectures)
- OpenAI's "A practical guide to building agents" (2025) recommends starting with a single agent and adding tools incrementally before splitting into multiple agents. It describes two multi-agent patterns: a manager that calls agents as tools, and decentralized peers that pass control through one-way handoffs, which the Agents SDK implements as a kind of tool. I found no explicit tool-count threshold; the guide was read only through secondary summaries. — [OpenAI guide landing page](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/); [Maginative summary](https://www.maginative.com/article/how-to-build-ai-agents-a-detailed-practical-guide-from-openai/)

**Dedicated router / classifier (embeddings, small model, rules)**
- Thumbtack (arXiv 2504.04277, 2025): when proprietary labeled data exists, an embeddings-based multiclass classifier was 49.5% more accurate than the best LLM prompting approach. It was also better calibrated, cheaper, and 14x (images) to 81x (text) faster. — [arXiv 2504.04277](https://arxiv.org/abs/2504.04277v1)
- "Intent Detection in the Age of LLMs" (arXiv 2410.01627, Oct 2024) compared seven LLMs with SetFit sentence-transformer classifiers. A hybrid system that routes uncertain cases to the LLM came within 2% of native LLM accuracy at 50% less latency. — [arXiv 2410.01627](https://arxiv.org/html/2410.01627v1)
- A 2026 voice-assistant paper (arXiv 2608.30738) reports embedding classifiers matching or beating every LLM tested on F1 for intent gating. Classifier latency was under 14 ms, against 184–1,661 ms for the LLMs. Skill routing across 18 skills added about 40 ms per utterance. I could not verify this paper independently. — [arXiv 2608.30738](https://arxiv.org/pdf/2608.30738)

**Generative UI frameworks (approach a / c in practice)**
- Vercel AI SDK: the established pattern maps each tool to a UI component and renders that component from the tool-call part, showing loading, result and error states. `streamUI` (RSC) is experimental; Vercel recommends AI SDK UI (`useChat` with tool parts) for production, which supports parallel and multi-step tool calls. — [AI SDK docs: rendering UI with language models](https://ai-sdk.dev/v5/docs/advanced/rendering-ui-with-language-models); [Vercel Academy: multi-step and generative UI](https://vercel.com/academy/ai-sdk/multi-step-and-generative-ui)
- assistant-ui follows the same per-tool component pattern ("Tool UI"), with loading, result and error states. — [assistant-ui Tool UI guide](https://www.assistant-ui.com/docs/guides/tool-ui)

### Inferences
- **(a) Derive the UI from tool calls (recommended primary mechanism).** If `finance.get_budget` runs, the Finance panel shows that budget. Routing accuracy then equals tool-selection accuracy, which Nexus's eval harness already measures, and it adds zero extra LLM calls, zero latency and no new failure mode. It also guarantees the panel shows data the agent actually retrieved and grounded its answer on, which is what "the right information" means in practice. This is the industry pattern in the Vercel AI SDK and assistant-ui. The weakness is turns where the agent answers from memory or the conversation and calls no tool. Example: "remind me what my grocery budget was" when the figure is already in context. These would surface nothing (the BFCL "empty turn" failure).
- **(c) Explicit `show_panel(domain, view, params)` tool.** This covers the no-tool case and lets Prime pin an overview. It is one more tool decision for a cheap model, though, and the evidence above says each extra decision and each similar-looking tool costs accuracy. If Nexus adds it, keep it among the 3–5 always-bound core tools with a few concrete usage examples, per Anthropic's guidance. Treat it as an override or supplement to (a), never the only path; otherwise surfacing accuracy depends on the model remembering to call a non-functional tool, which cheap models tend to skip.
- **(b) Embedding or small-model router.** Its main value is upstream of the agent: choosing which skills or domain tools to load (tool retrieval), not choosing the UI. The published evidence (Thumbtack, SetFit hybrid, RAG-MCP) favors embeddings for speed and cost, with an LLM fallback when confidence is low. It can also pre-warm a panel skeleton within about 50 ms, before the agent finishes. It needs labeled examples, which Nexus can mine from eval cases and logs.
- **(d) Supervisor or swarm.** The LangChain data suggests a single agent holds up with one domain but degrades at three or more domains in context. Prime's on-demand skill loading already narrows context in a similar way to sub-agents, without the supervisor's "translation" overhead. Revisit sub-agents only if evals show tool-selection accuracy falling as Health and other domains are added. If it comes to that, the swarm-style pattern, where the agent responds directly, tested better than a supervisor.
- Domain tool namespacing (for example the `finance_` and `travel_` prefixes) both reduces similar-name confusion and makes deriving domains from tool calls trivial.

### Gaps
- No published benchmark for "panel/UI selection accuracy". All evidence is a proxy (tool selection, intent detection).
- No published tool-count degradation curve was found for deepseek-class flash models specifically. Nexus has to measure this on its own harness by adding distractor tools or domains, as LangChain did.
- Primary numbers from LangChain (exact per-architecture scores) and RAG-MCP (85%→45% curve) could not be fetched and verified.

## Q2. Multi-intent / multi-domain turns ("can I afford the Japan trip?"): how are they detected and handled?

### Takeaway
Classic multi-intent spoken language understanding (SLU) work treats the task as multi-label classification: predict the number of intents, then select them. LLMs now match or beat specialist models on these benchmarks, especially with decompose-then-solve prompting. The benchmarks overstate real-world difficulty in some ways (template conjunctions like "X and Y") and understate it in others (implicit multi-domain questions like "can I afford X"). For a tool-calling agent, implicit multi-domain turns are handled naturally when the agent calls tools from both domains, so the UI should be a set of panels derived from the union of domains touched, not a single "winner".

### Cited Findings
- Yin et al. (arXiv 2403.04481, Mar 2024; revised through Oct 2025 as "ECLM") built LM-MixATIS and LM-MixSNIPS for LLMs and introduced the Entity Slot Accuracy and Combined Semantic Accuracy metrics. They found LLMs "can match and potentially excel beyond" state-of-the-art multi-intent SLU models. Later versions report overall-accuracy gains of +3.7% on MixATIS and +3.1% on MixSNIPS over strong baselines, and +8.5% / +21.2% over supervised fine-tuning of LLMs. — [arXiv 2403.04481](https://arxiv.org/html/2403.04481v3); [v4 (ECLM)](https://arxiv.org/html/2403.04481v4)
- MIDLM (COLING 2025, same first author) explicitly combines intent-number detection with multi-intent selection, and notes that multi-intent detection resources are "notably limited". — [COLING 2025 paper](https://aclanthology.org/2025.coling-main.179.pdf)
- Divide-Solve-Combine prompting (AAAI 2025) handles zero-shot multi-intent detection in three steps: split the query into single-intent sub-sentences, classify each, and combine the results. It reports gains on MixATIS and MixSNIPS. — [AAAI 2025](https://ojs.aaai.org/index.php/AAAI/article/view/34688)
- BlendX (LREC-COLING 2024) criticizes MixATIS and MixSNIPS for building multi-intent examples from only four conjunction templates, so high scores may overstate real-world ability. It evaluates ChatGPT in-context learning on harder blended patterns. — [BlendX](https://galsang.github.io/hyu-nlp-publications/papers/blendx.html); [LREC 2024 paper](https://aclanthology.org/2024.lrec-main.218.pdf)
- Dataset scale for reference: MixATIS has 13,162 training examples and 18 intents; MixSNIPS has 39,776 training examples and 7 intents. — [Multi-intent SLU survey, arXiv 2512.11258](https://arxiv.org/pdf/2512.11258)
- Vercel AI SDK UI supports parallel and multi-step tool calls rendered as separate tool parts, so several domain components can render in one turn. — [Vercel Academy](https://vercel.com/academy/ai-sdk/multi-step-and-generative-ui)

### Inferences
- Model domain surfacing as **multi-label** (a set of domains per turn), never argmax/single-label. This matches the owner's "no artificial limit" requirement and the multi-intent SLU literature. Score it with set metrics (see Q5).
- "Can I afford the Japan trip?" is an *implicit* (compositional) multi-domain question, not a conjunction ("show my budget and my trip"). The trip cost (Travel) feeds an affordability check (Finance). The benchmark literature mostly covers the conjunction type. With approach (a), a correct agent calls `travel.get_trip(Japan)` and then `finance.get_budget` or `finance.cash_flow`, and both panels surface automatically. Handling implicit multi-domain turns therefore reduces to the agent's multi-step tool planning, which can be tested directly in the eval harness.
- If Nexus adds a pre-agent router, it should output a set of domains above a confidence threshold, not a top-1. A decomposition prompt along the lines of Divide-Solve-Combine is a cheap option for a small LLM router.
- Write explicit eval cases for implicit multi-domain turns, as BlendX's critique suggests: templated "X and Y" cases will overstate accuracy.

### Gaps
- No published benchmark on *implicit* cross-domain personal-assistant queries (e.g., finance x travel) was found.
- No data was found on how many panels users tolerate at once before clutter hurts. Layout limits are a design choice, not an evidence-based number.

## Q3. Timing: when should UI appear, and when should it update, replace or stay? How to avoid flicker and over-surfacing, and how to carry context across turns ("and last month?")?

### Takeaway
Evidence here is mostly framework convention and HCI principle rather than measured studies. The established pattern renders a panel at the moment of the tool call: a skeleton or loading state while the tool runs, then filled with the result, before or alongside the streamed answer. Horvitz's principles argue for timing services to the user's attention, scoping precision to certainty, and keeping working memory of recent interactions. In practice that means updating the existing panel for follow-ups and not replacing or flickering it.

### Cited Findings
- Vercel AI SDK and assistant-ui render tool-call parts with explicit loading, result and error states. The UI appears when the tool is called (loading) and fills when the result arrives, independently of the streamed text. — [assistant-ui Tool UI](https://www.assistant-ui.com/docs/guides/tool-ui); [Vercel Academy](https://vercel.com/academy/ai-sdk/multi-step-and-generative-ui)
- Horvitz (CHI '99) principles relevant to timing and persistence: consider the status of the user's attention when timing services; scope the precision of a service to match uncertainty about the user's goals; minimize the cost of poor guesses about action and timing; allow efficient direct invocation and termination; maintain working memory of recent interactions. Reading note: this list was compiled from the paper and course summaries, not a full fetch. — [Horvitz, "Principles of Mixed-Initiative User Interfaces" (paper PDF)](https://www.erichorvitz.com/chi99horvitz.pdf); [Microsoft Research page](https://www.microsoft.com/en-us/research/publication/principles-mixed-initiative-user-interfaces/)
- Course material on Horvitz describes three decision regions (act autonomously, open a dialog, do nothing) set by probability thresholds that shift with user attention and error cost ("cheap and reversible" vs "costly or permanent"). — [UW-Madison CS639 lecture on proactivity timing](https://wisc-hci.github.io/cs639-s26/lectures/w09-1-proactivity-timing.pdf); [Cambridge IWML lecture](https://www.cl.cam.ac.uk/teaching/2021/InteractML/IWML-Lecture-2.pdf)
- BFCL V3's multi-turn evaluation shows that keeping state across turns is a distinct failure area ("Instance State Mismatch", "Empty Turn Response"). — [Gorilla BFCL blog](https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html); [HF dataset card](https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard)

### Inferences (design rules for Nexus; principle-derived, not measured)
- **Appear:** open a skeleton panel when the domain tool call is emitted. This is the earliest moment it is certain, and it is earlier than the text answer. An optional embedding router could pre-open a skeleton even earlier, but a wrong pre-open is visible flicker. If used at all, gate it at high confidence only (Horvitz: scope precision to certainty).
- **Update vs replace vs stay.** Key panels by `(domain, view, entity)`.
  - Same key with new params (e.g., "and last month?" means `finance.spending(period=Oct)` after `period=Nov`): update in place, perhaps with a period toggle. This avoids flicker and preserves orientation.
  - New domain: add a panel alongside.
  - Topic leaves a domain entirely: keep the panel but de-emphasize or collapse it after N turns of non-use, rather than removing it immediately.
  - Never remove a panel the user has interacted with or pinned (Horvitz: efficient direct invocation and termination; user control).
- **Follow-up carry-over.** "And last month?" depends on the agent re-calling the same tool with a changed argument. That is an agent-memory and tool-argument problem the eval harness can test with multi-turn cases: expected tool = same as the previous turn, with a changed `period`. The UI then follows automatically under approach (a).
- **Anti-over-surfacing:** surface only for domain *data* tools, not for incidental lookups (e.g., a currency conversion inside a travel answer should not open the whole Finance dashboard). Keep an explicit per-tool `surfaces_panel: bool` / `view` mapping in the tool registry.

### Gaps
- No controlled study was found on panel timing (before vs with vs after the answer) in chat assistants, or on flicker thresholds for agent-driven UI.
- No public write-ups were found from ChatGPT, Gemini or Copilot teams describing their measured rules for when to render widgets or cards.

## Q4. Proactive / mixed-initiative surfacing: when should the assistant show something unasked?

### Takeaway
The classic rule (Horvitz 1999) is to act unasked only when the expected value of acting beats inaction, given uncertainty about the user's goal and the cost of interrupting. Modern LLM proactive-agent benchmarks find that models are good at helping when help is needed but bad at staying silent, giving high false-alarm rates. Notification research finds that proactive or unsolicited information is rated least interesting and that persistent irrelevant prompts drive users to disable features or abandon apps. For Nexus: be conservative, gate proactive surfacing on a calibrated threshold, prefer low-cost, ignorable placements, and measure false alarms explicitly.

### Cited Findings
- Horvitz (CHI '99): "Autonomous actions should be taken only when an agent believes that they will have greater expected value than inaction for the user." Under uncertainty, the system should "engage in an efficient dialog with the user, considering the costs of potentially bothering a user needlessly." The principles were developed in the Lookout scheduling system. — [Horvitz paper](https://www.erichorvitz.com/chi99horvitz.pdf); [erichorvitz.com HTML version](https://erichorvitz.com/uiact.htm)
- Proactive Agent / ProactiveBench (Lu et al., arXiv 2410.12361, Oct 2024) uses a reward model, validated against human annotators, to simulate whether a user would accept each proactive suggestion. It reports a False-Alarm metric for suggestions made when no help was needed. Models "succeed in assisting when the user needs it but fail to stay silent when the user does not require any assistance, resulting in a relatively high false alarm ratio". Fine-tuned models reduced false alarms to a level comparable with GPT-4o. — [arXiv 2410.12361](https://arxiv.org/pdf/2410.12361)
- PRISM (arXiv 2602.01532, ICLR 2026) gates proactive interventions on a calibrated probability of user acceptance, with the threshold set by the relative costs of missed help and false alarms ("Festina Lente": make haste slowly). It is evaluated on ProactiveBench. — [PRISM](https://arxiv.org/html/2602.01532v1)
- ProVoice-Bench (arXiv 2604.15037) reports a False Positive Rate for unnecessary interventions by proactive voice agents. — [arXiv 2604.15037](https://arxiv.org/pdf/2604.15037.pdf)
- Intelligent-notification survey (Mehrotra & Musolesi, arXiv 1711.10171): information triggered by proactive services is considered the least interesting by users, and people get annoyed and consider deleting apps that consistently trigger such notifications. — [arXiv 1711.10171](https://arxiv.org/pdf/1711.10171)
- An in-the-wild study (CHI 2016) logged 10,372 notifications and 474 questionnaire responses from 20 users, and found that psychological traits strongly shape how people react to notifications. This argues for per-user adaptation. — [UCL CHI'16 PDF](https://discovery.ucl.ac.uk/1502364/1/CHI16.pdf)
- A meta-analysis of context-aware notification management systems found they increase response rates, but it was based on only 8 studies. — [ETH Research Collection](https://www.research-collection.ethz.ch/bitstream/handle/20.500.11850/218431/Efficacy_of_Mobile_Context-aware_Notification_Management_Systems_A_Systematic_Literature_Review_and_Meta-Analysis.pdf?sequence=1)
- A 2022 experience-sampling study (17 participants) examined why users dismiss smartphone notifications; users frequently deactivate whole app categories. — [FH OÖ publication](https://pure.fh-ooe.at/en/publications/an-experience-sampling-study-to-evaluate-why-users-dismiss-smartp/)

### Inferences
- Separate **reactive surfacing** (the user asked; the panel follows tool calls; high precision is easy) from **proactive surfacing** (unasked; for example, "your card bill is due" or a Travel panel when a flight is tomorrow). Evaluate and gate them separately.
- Proactive surfacing should use a placement that is cheap to ignore (a small chip or card, not a full dashboard takeover) and should be triggered by high-certainty, deterministic signals (calendar or date events, thresholds) rather than LLM speculation. A cheap model is exactly the kind ProactiveBench found over-eager.
- Use an explicit cost-weighted threshold, as in Horvitz and PRISM. Track per-user and per-proactive-type acceptance and dismissal rates, and auto-suppress types the user repeatedly dismisses. The notification literature suggests that ignoring this leads users to turn features off entirely.
- Inside the conversation, a mild form of proactivity, adding a related second panel (e.g., Finance when discussing the cost of a trip), is relatively low-risk if it is a collapsed or secondary panel. Even so, it should count toward the false-alarm metric.

### Gaps
- No primary data was found on Google Now / Google Assistant proactive-card engagement or dismissal rates. Google does not appear to have published them; secondary claims were not found or verified.
- No published evidence on proactive UI surfacing *within* a chat session (as opposed to push notifications).

## Q5. Evaluation: metrics and methods for "right info at the right time"

### Takeaway
Treat surfacing as multi-label prediction per turn and score it with set-based precision, recall and F1 (plus exact-set match) against expected domains and views. Extend this with multi-turn cases for carry-over, irrelevance or "show nothing" cases (as in BFCL), distractor-domain stress tests (as in LangChain), and a false-alarm rate for proactive surfacing (as in ProactiveBench). Online, track panel interactions and dismissals as implicit labels, and feed real conversations back into the offline set.

### Cited Findings
- BFCL scores irrelevance detection separately: the model must abstain from calling any function when none fits. It also scores multi-turn conversations against expert-labeled ground-truth trajectories. — [Gorilla BFCL blog](https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html); [HF dataset card](https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard)
- Epoch AI's audit of BFCL v4 found label errors in irrelevance and multi-turn items, a reminder that ground-truth labels for "what should be called" are themselves error-prone and need review. — [Epoch AI review](https://epoch.ai/benchmarks/berkeley-function-calling-leaderboard/review)
- LangChain's method: hold the target task fixed and add distractor domains step by step, measuring accuracy and token cost at each step. — [LangChain blog](https://blog.langchain.com/benchmarking-multi-agent-architectures)
- RAG-MCP's needle-in-a-haystack tool-selection stress test (one correct tool among N−1 distractors, N increasing). — [arXiv 2505.03275](https://arxiv.org/abs/2505.03275v1)
- ProactiveBench reports false-alarm and missed-need metrics using a reward model, validated against human labels, as a simulated user judge (an LLM-as-judge pattern). — [arXiv 2410.12361](https://arxiv.org/pdf/2410.12361)
- Multi-intent SLU metrics: overall (exact-set) accuracy, plus the Entity Slot Accuracy and Combined Semantic Accuracy metrics proposed for LLM evaluation. — [arXiv 2403.04481](https://arxiv.org/html/2403.04481v3)
- Notification research uses acceptance or response rates and dismissals as primary online signals. — [arXiv 1711.10171](https://arxiv.org/pdf/1711.10171); [ETH meta-analysis](https://www.research-collection.ethz.ch/bitstream/handle/20.500.11850/218431/Efficacy_of_Mobile_Context-aware_Notification_Management_Systems_A_Systematic_Literature_Review_and_Meta-Analysis.pdf?sequence=1)

### Inferences (a concrete eval design for Nexus's existing harness)
- **Per-turn labels.** Each eval case gets `expected_panels: set[(domain, view)]` (can be empty), plus optional `forbidden_panels`. If the UI is derived from tool calls, these labels come almost for free from the existing expected tool calls through the tool-to-panel map.
- **Offline metrics, computed over the existing N repeated runs and reporting mean and variance across runs:**
  - Micro- and macro-averaged precision, recall and F1 over panels.
  - Exact-set match rate.
  - Over-surfacing rate: fraction of turns with an unexpected panel.
  - Under-surfacing rate: expected panel missing, including the "empty turn" case where no tool was called.
  - Correct-silence rate on "show nothing" cases (small talk, general knowledge).
  - Per-domain confusion matrix.
- **Case categories to include:**
  - Single-domain.
  - Explicit multi-domain ("X and Y").
  - Implicit multi-domain ("can I afford Japan").
  - Follow-up carry-over (multi-turn: "and last month?" should update the same panel key with changed params).
  - Topic switch (the new panel appears; the old panel is not wrongly re-fetched).
  - Irrelevance or no-panel cases.
  - Near-miss distractors (incidental currency conversion should not open the Finance dashboard).
  - Proactive cases with both "should surface" and "should stay silent" labels.
- **Scaling stress test.** As in LangChain and RAG-MCP, re-run the suite with the tool or skill sets of extra domains (Health, stub domains) bound or loaded, to see where the flash model's selection accuracy breaks. That breakpoint is the signal for tool search or sub-agents.
- **Timing check.** Assert on event order in traces (panel event emitted at tool-call time, before the final text) and on no-flicker (no panel removed and re-added for the same key within a turn).
- **LLM-as-judge.** Reserve it for questions set metrics cannot answer: "Given this conversation, was the surfaced content the most useful information at this moment? Was anything missing or distracting?" Use a stronger model than Prime, and calibrate the judge on a few dozen human-labeled turns before trusting it, since ProactiveBench validated its judge against human annotators and Epoch found label noise even in curated benchmarks.
- **Online signals:**
  - Panel interaction rate (clicked, expanded, scrolled within N seconds).
  - Dismiss or close rate.
  - Time-to-dismiss (fast dismissals likely mark false positives).
  - Manual opens of a panel the agent did not surface (likely false negatives).
  - Re-ask rate ("show me my budget" right after an answer about the budget implies under-surfacing).
  Sample dismissed and manually-opened turns weekly into the offline eval set; this is the "offline eval set from real conversations" loop.

### Gaps
- No standard published metric or benchmark exists for "right info at the right time" in agent-driven UI. The metric set above is assembled by analogy to tool-calling, multi-intent and proactive-agent evaluation.
- No published baseline was found for acceptable panel dismissal or interaction rates in chat assistants.
