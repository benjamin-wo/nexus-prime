# UX Patterns and Evidence for Agent-Driven (Adaptive / Generative) UI: Chat + Dynamic Domain Panels

Scope: evidence-backed guidance for Nexus (one agent "Prime" + domain panels for Finance, Travel, later Health), desktop web first, mobile second. Today Nexus has a chat drawer plus classic tabs (Home, Money, Invest, Travel), and also runs as a Telegram Mini App.

Method note: research ran on 2026-11-14 with web search. Direct page fetches to nngroup.com, openai.com and arxiv.org were blocked by this session's network policy, so several findings rely on search-result excerpts of those pages rather than a full read. Each such case is marked "(excerpt)". To verify them, those hosts must be allowed in the session's network settings.

## 1. Layout patterns for chat + canvas/panels (desktop and mobile): what works, what fails

### Takeaway
The pattern the major assistants have converged on (2024-2026) is a two-pane workspace: conversation on one side, and on the other a persistent, editable, versioned object (a canvas, artifact or page). The panel appears either on the user's request or when the model judges the task needs it. Version history and targeted editing (highlight-to-act) are the features most often credited with making it usable. On mobile, platform conventions point to a nonmodal bottom sheet that becomes modal when expanded, with no stacked sheets. No rigorous comparative user study of these product layouts was found.

### Cited Findings
- OpenAI launched ChatGPT Canvas on 2024-10-03. Their post describes it as "a new interface for working with ChatGPT on writing and coding projects that go beyond simple chat", opening "in a separate window" next to the chat — [OpenAI, Introducing canvas](https://openai.com/index/introducing-canvas/) (excerpt via search; fetch blocked)
- Canvas could be opened in three ways: choosing the model explicitly, automatically "when needed", or by the user typing "use Canvas". Users can highlight a section to tell the model where to focus — [Tom's Guide, Oct 2024](https://www.tomsguide.com/ai/chatgpt/openai-launches-chatgpt-canvas-an-ai-powered-writing-and-code-editor); [OpenAI](https://openai.com/blog/introducing-canvas)
- Canvas became available to all ChatGPT users, free tier included, in December 2024 — [VentureBeat](https://venturebeat.com/ai/openai-expands-chatgpt-canvas-to-all-users)
- Third-party descriptions disagree on which side of the screen holds the chat and which holds the canvas. Placement varies across products and across reviewers' accounts — [Tom's Guide](https://www.tomsguide.com/ai/chatgpt/openai-launches-chatgpt-canvas-an-ai-powered-writing-and-code-editor) vs. [Fast Company](https://www.fastcompany.com/91202944/open-ai-canvas-word-doc?partner=rss) (as summarised in search results)
- Gemini Canvas and Claude Artifacts are both side-pane workspaces. Commentators say Artifacts leans toward small interactive apps and Canvas toward writing and inline editing, and that Gemini Canvas exports to Google Docs — [bootstrapcreative 2026 feature map](https://bootstrapcreative.com/chatgpt-vs-claude-vs-gemini-terminology/); [aipedia glossary](https://aipedia-en.pages.dev/glossary/ai-canvas)
- One reviewer describes Claude's split as roughly 50/50 between chat and preview — [AlgoCademy](https://algocademy.com/blog/?p=1038) (low-rigor blog)
- Blog du Modérateur compared the canvases of ChatGPT, Gemini, Claude and Le Chat. It rated Claude's interface the most pleasant, mainly because of its **version history** — [BDM](https://www.blogdumoderateur.com/canvas-comparatif-ia/) (excerpt)
- Microsoft Copilot Pages is a persistent shared document that the user and Copilot edit together, shared through Teams, Outlook and Microsoft 365. It is not an app surface that runs code — [SSW rules](https://www.ssw.com.au/rules/use-ai-artifacts)
- Google Research's "Generative UI" (blog dated 2025-11-18) runs inside the Gemini app as two experiments, "dynamic view" and "visual layout", and dynamic view is also in AI Mode in Search. Human raters preferred generated UIs over standard LLM text output; expert human-designed sites still ranked highest. Google notes that generation "can take a minute or more" and that outputs are sometimes inaccurate — [Google Research blog](https://research.google/blog/generative-ui-a-rich-custom-visual-interactive-user-experience-for-any-prompt/)
- Academic evidence: in "Generative Interfaces for Language Models" (Chen, Zhang, Zhang, Shao, Yang; arXiv 2508.19227, Aug/Oct 2025), generated task-specific UIs were preferred over conversational replies in over 70% of cases, with up to a 72% improvement in human preference. The authors attribute this to visual organisation, interactivity and lower cognitive load, with the largest gains in **structured, information-dense domains** — [arXiv 2508.19227](https://arxiv.org/abs/2508.19227v2) (abstract and secondary summaries; per-domain numbers not verified)
- Mobile, NN/g on bottom sheets: a nonmodal bottom sheet leaves the background interactive, while a modal one blocks it. Bottom sheets "start off as nonmodal in their minimized state but become modal when expanded". Guidelines include letting Back dismiss the sheet, giving it a clear close (X) control, and **not stacking bottom sheets**. Google Maps is the cited nonmodal example — [NN/g, Bottom Sheets](https://www.nngroup.com/articles/bottom-sheet/) (excerpt)
- eBay's design system advises against launching other modal elements from a sheet because "this quickly becomes inaccessible and disorienting", and recommends full-screen overlays instead — [eBay Playbook](https://playbook.ebay.com/design-system/components/bottom-sheet)
- NN/g has a separate article on accidental dismissal of overlays, a known failure mode of swipe- and tap-outside-to-dismiss sheets — [NN/g, Accidental overlay dismissal](https://www.nngroup.com/articles/accidental-overlay-dismissal/) (title only seen)

### Inferences
- **Desktop for Nexus:** a persistent chat column plus a main "stage" area holding domain panels matches the converged canvas/artifact model. Panels should be persistent objects: they stay after the turn ends, carry history, and can be reopened. They should not be ephemeral render-once outputs inside the message stream.
- **Triggering:** offer both explicit ("show my budget") and automatic opening, as Canvas does. Automatic opening needs a high-precision trigger, because a wrong panel costs attention (see Section 2 on accuracy).
- **Latency:** Google reports a minute or more for fully generated UIs. That argues against generating panel UI from scratch for Nexus. Pre-built domain components that the agent selects and parameterises with data are better, since they also keep layouts stable and learnable (Section 2).
- **Mobile:** chat is the base layer and the domain panel is a nonmodal bottom sheet in peek or half state that expands to modal or full screen. Avoid stacking sheets. Use a full-screen card when the user drills into a panel.
- **Placement:** product reviews disagree on which side the chat goes, so neither side is a de facto standard. Pick one and keep it fixed.

### Gaps
- No peer-reviewed or vendor-published comparative study was found of split ratios, chat-left vs. chat-right placement, or inline-in-chat cards vs. side canvas.
- I recall OpenAI reporting automatic-trigger accuracy figures for Canvas (roughly 83% for writing and 94% for coding vs. a baseline). I could not verify this because openai.com was blocked. Do not cite it until it is checked against the original post.
- No published failure post-mortems were found for ChatGPT Canvas, Claude Artifacts, Copilot Pages, Notion AI or Perplexity layouts. Perplexity- and Notion-specific UX evidence was not found.

## 2. HCI research on adaptive UIs: predictability vs. adaptivity, control, explainability, learnability; NN/g on generative UI

### Takeaway
Classic adaptive-UI research has three consistent findings. Adaptation helps only when it is accurate. Spatial stability matters: add or duplicate items rather than moving them. Users prefer being in control (adaptable over adaptive). Accuracy outweighed predictability in Gajos et al. 2008, but both raised satisfaction. The Microsoft HAX guidelines turn this into concrete rules: make clear why the system did what it did, support efficient dismissal and correction, scope services when in doubt, and update and adapt cautiously.

### Cited Findings
- **Gajos, Everitt, Tan, Czerwinski & Weld, CHI 2008, "Predictability and accuracy in adaptive user interfaces":** they tested predictability and accuracy of adaptation (accuracy levels 50% and 70%). Both significantly increased satisfaction. Higher accuracy also improved performance and raised use of the adaptive part. **Contrary to the authors' expectations, accuracy had a stronger effect than predictability** on performance, utilisation and some satisfaction ratings — [Gajos et al. 2008](https://www.eecs.harvard.edu/~kgajos/papers/2008/gajos08predictability.shtml); [PDF](https://kgajos.seas.harvard.edu/papers/kgajos-chi08-predictability.pdf)
- **Gajos, Czerwinski, Tan & Weld, AVI 2006, "Exploring the design space for adaptive GUIs":** they compared three adaptive designs (Split, Moving, Visual Popout) against a non-adaptive baseline. The **Split** interface, which copies predicted items into a separate adaptive area while originals stay put, was significantly faster than baseline (p<0.003, per the slides). Users praised its stability. **Moving** items "introduce[d] spatial instability" and was only marginally faster. Visual Popout drew discoverability complaints — [AVI 2006 paper](https://www.eecs.harvard.edu/~kgajos/papers/2006/kgajos-avi06.pdf); [slides](https://www.eecs.harvard.edu/~kgajos/papers/2006/kgajos-avi06-slides.pdf) (numbers from slides)
- A later review notes that an *elective* split design (the user may use the adaptive area or ignore it) was shown to be faster and preferred over the original *mandatory* design — [Findlater & Gajos, AI Magazine 2009](https://www.eecs.harvard.edu/~kgajos/papers/2009/AIMag09-AUIs.pdf) (via search excerpt)
- **Findlater & McGrenere, CHI 2004, "A comparison of static, adaptive, and adaptable menus"** (27 participants): a static split menu was significantly faster than an adaptive one. Most users **preferred the adaptable (user-controlled) menu** overall. The authors concluded that user-driven customisation is a promising direction — [Findlater & McGrenere 2004 PDF](https://www.cs.ubc.ca/labs/edapt/papers/findlater2004.pdf)
- **Microsoft HAX, Amershi et al., CHI 2019:** 18 guidelines distilled from more than 150 recommendations and validated empirically. They are grouped into four phases: initially, during interaction, when wrong, and over time. Those most relevant to Nexus:
  - G3 Time services based on context
  - G4 Show contextually relevant information
  - G8 Support efficient dismissal ("make it easy to dismiss or ignore undesired AI system services")
  - G9 Support efficient correction
  - G10 Scope services when in doubt ("engage in disambiguation or gracefully degrade ... when uncertain about a user's goals")
  - G11 Make clear why the system did what it did (patterns: local explanations, "what if?" explanations)
  - G12 Remember recent interactions
  - G14 Update and adapt cautiously
  - G17 Provide global controls
  - G18 Notify users about changes

  The authors say the guidelines are "not intended to be used as a simple checklist" — [Amershi et al. 2019 PDF](https://research.microsoft.com/%7Ehorvitz/Guidelines_Human_AI_Interaction.pdf); [Microsoft Research blog](https://www.microsoft.com/en-us/research/blog/guidelines-for-human-ai-interaction-design/); [HAX Toolkit pattern library](https://www.microsoft.com/en-us/haxtoolkit/library/example,pattern/3,9,13,17/23/)
- **Google PAIR Guidebook, Explainability + Trust:** users should *calibrate* trust rather than trust fully. Explanations should help users "know when to trust the system's predictions and when to apply their own judgement". The chapter also covers whether, when and how to show confidence. The Errors + Graceful Failure chapter covers telling users the way forward after an error — [PAIR, Explainability + Trust](https://pair.withgoogle.com/chapter/explainability-trust/); [chapters index](https://pair.withgoogle.com/guidebook/chapters)
- **Apple HIG, Generative AI:** the first best practice is "Keep people in control ... ensure they remain in charge of decision making and the overall experience". Apps should also give "a great experience even when generative features aren't available or people opt not to use them" — [Apple HIG, Generative AI](https://developer.apple.com/design/human-interface-guidelines/generative-ai.md); see also [Machine Learning, Limitations](https://developer.apple.com/design/human-interface-guidelines/machine-learning.md)
- **NN/g, Generative UI** (Kate Moran and colleagues): generative UI is an interface "dynamically generated in real time by artificial intelligence to provide an experience customized to fit the user's needs and context". It goes with "outcome-oriented design", meaning users state the outcome they want rather than commands. NN/g frames it as part of the third UI paradigm (intent-based outcome specification) — [NN/g, Generative UI](https://www.nngroup.com/articles/generative-ui/) (excerpt; date not confirmed); definition quoted by [Capicua](https://www.capicua.com/blog/generative-ui-genui-strategy)
- **NN/g on chat behaviours:** back-and-forth prompting in text-only chat UIs produces the "accordion effect" and "apple picking" — [NN/g](https://www.nngroup.com/articles/accordion-editing-apple-picking/) (title and excerpt only). Per a secondary citation, NN/g's 2025 "Scope in Generative AI Features" found that narrower, scoped AI features were easier for new users to understand and adopt than broad, open-ended ones — cited via search summary; primary page not read
- **MeasuringU 2025 benchmark** (153 US participants, Jan-Feb 2025), UX-Lite scores: Claude 77.3, ChatGPT 81.5, Gemini 84.5 — [MeasuringU](https://measuringu.com/ai-based-chat-software-ux-2025/)

### Inferences
- **Do not rearrange stable surfaces.** In Gajos' terms, the "Split" approach maps onto Nexus as follows: the agent *adds* panels to a dedicated stage area or "for you" region, and the domain tabs keep fixed positions and content. Never reorder tabs or move existing panels unprompted.
- **Accuracy is the dominant lever.** A wrong panel is worse than no panel. When intent is ambiguous (for example "how much did I spend in Lisbon?" could be Finance or Travel), apply HAX G10: show a compact chooser or a lightweight chip, or open both with the second collapsed, rather than guessing loudly.
- **Make panels elective.** An agent's suggestion appears as a chip or collapsed card the user can expand. Auto-expansion is reserved for unambiguous, explicit requests ("show my budget").
- **Every agent-opened panel needs a "why" affordance** (HAX G11), for example the caption "Opened because you asked about March spending", linked to the message that caused it.
- **Global controls** (HAX G17): a setting for how proactive panel-opening is (off / suggest / auto). This also covers Findlater & McGrenere's preference for adaptable over adaptive.

### Gaps
- NN/g's generative-UI and 2025 chatbot articles could not be read in full (host blocked). Their dates and any NN/g usability-test findings specific to generative UI are unverified.
- I recall the Findlater et al. "ephemeral adaptation" study (CHI 2009: predicted items appear immediately while others fade in). It is a relevant low-disruption technique, but its numbers were not verified this session — [PDF located](https://www.cs.ubc.ca/labs/edapt/papers/findlater2009.pdf), contents not read.
- No 2024-2026 controlled study was found that tests predictability vs. accuracy specifically for LLM-driven panel selection.

## 3. Multiple panels at once: attention, overload, how many is too many; pinning, dismissing, history

### Takeaway
No study gives a validated maximum number of simultaneous panels. The best-supported basis is working-memory capacity (Cowan's roughly 3-5 chunks, often quoted as 4-7) together with progressive disclosure. Platform guidance (no stacked sheets) and the HAX guidelines (efficient dismissal, remember recent interactions) support explicit pin, dismiss and history controls.

### Cited Findings
- Practitioner sources give working-memory capacity as 5-7 items, 3-5 items (Miller and Cowan), or about 4-7 chunks. The figures are inconsistent, and some claims about the effects of overload are unsourced — [Nightingale/DVS](https://nightingaledvs.com/dashboards-human-brain-processing/); [Aufait UX](https://www.aufaitux.com/blog/enterprise-dashboard-design-psychology/); [Smashing Magazine, Sept 2025](https://smashingmagazine.com/2025/09/ux-strategies-real-time-dashboards/)
- An ECIS 2019 eye-tracking study found that visuospatial working-memory capacity affects how users allocate attention while exploring dashboards. The authors argue for *user-adaptive* dashboards; the study gives no panel count — [ECIS 2019](https://aisel.aisnet.org/ecis2019_rp/139)
- NN/g says not to stack bottom sheets, and eBay says nested modals from a sheet are "inaccessible and disorienting" — [NN/g](https://www.nngroup.com/articles/bottom-sheet/); [eBay](https://playbook.ebay.com/design-system/components/bottom-sheet)
- The HAX guidelines call for efficient dismissal (G8), remembering recent interactions (G12) and cautious updating (G14) — [Amershi et al. 2019](https://research.microsoft.com/%7Ehorvitz/Guidelines_Human_AI_Interaction.pdf)
- Version history was the feature most credited for the best-liked canvas UX in one product comparison — [BDM](https://www.blogdumoderateur.com/canvas-comparatif-ia/)
- Gajos 2006: moving items creates spatial instability and users dislike it — [AVI 2006](https://www.eecs.harvard.edu/~kgajos/papers/2006/kgajos-avi06.pdf)

### Inferences
- **Practical budget (heuristic):** on desktop, one primary expanded panel plus at most 2-3 secondary panels, collapsed or compact. On mobile, one panel at a time, with other domains shown as chips or tabs inside the sheet. This rests on working-memory limits, not on a validated Nexus-specific number, so it should be usability-tested.
- **Lifecycle model:** each panel is *suggested*, then *open*, then *pinned*, *dismissed* or *archived*. Pinned panels never get replaced by the agent. Unpinned panels can be swapped, but only into the same slot and never with a reshuffle. Dismissed panels go to a "recent panels" history that can be reopened from the conversation turn that produced them, like a version-history rail.
- **New-panel arrivals must be announced** (HAX G18) with a subtle highlight or message-to-panel link. They should never silently replace something the user was reading.

### Gaps
- No empirical study was found on how many AI-opened panels users can track at once, or on pin and dismiss behaviour in agentic UIs. This is a candidate for Nexus's own usability testing.

## 4. Trust and accuracy in finance/health: source data, chat-panel consistency, errors and uncertainty

### Takeaway
Citations raise trust even when they are wrong, and checking them lowers it. So "showing sources" alone does not produce well-calibrated reliance. For finance and health, the panel should be the system of record: deterministic data rendered from the user's real accounts. The chat should reference and summarise that panel and never state numbers the panel does not show. Uncertainty and errors need explicit, recoverable UI.

### Cited Findings
- **Ding et al., "Citations and Trust in LLM Generated Responses" (AAAI 2025):** trust rose significantly when citations were present, **even when the citations were random**, and fell significantly when participants actually checked them. Finding irrelevant or incorrect references eroded trust further — [AAAI 2025](https://ojs.aaai.org/index.php/AAAI/article/view/34550); [arXiv 2501.01303](https://arxiv.org/pdf/2501.01303v1.pdf); companion write-up [Facciani](https://matthewfacciani.substack.com/p/does-it-matter-if-an-ai-chatbot-cites)
- **FINRA Investor Education Foundation (2024):** distrust was 20% for financial information attributed to AI vs. 15% when attributed to a human professional. Trust in a hypothetical stock-vs-bond forecast was nearly the same regardless of source — [American Banker](https://americanbanker.com/news/ai-for-banking-faces-trust-hurdles-finra-foundation-study-says); [FINRA Foundation report](https://finrafoundation.org/sites/finrafoundation/files/the-machines-are-coming.pdf)
- **Schreibelmayr et al. 2023** (N=127, financial AI assistant): high-trust users rated the assistant more useful and competent, while low-trust users focused on its uncanniness and dangers. Changing the assistant's decision agency had no effect on trust or intention to use — [PMC10579608](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10579608/)
- Trade press (Oct 2026) reports that investors who already pay for advice are the most likely to act on a chatbot's financial answer without checking it. Methodology not verified — [InvestmentNews](https://www.investmentnews.com/transformation/clients-with-advisors-more-likely-to-act-on-unchecked-ai-answers/268628)
- PAIR: aim for calibrated trust, and note that marking a prediction as possibly wrong lowers trust in *that* prediction (the intended effect) — [PAIR](https://pair.withgoogle.com/chapter/explainability-trust/)
- Google's generative UI outputs are "sometimes inaccurate" — [Google Research](https://research.google/blog/generative-ui-a-rich-custom-visual-interactive-user-experience-for-any-prompt/)
- HAX "when wrong" guidelines G8-G11: efficient dismissal and correction, scoping when in doubt, explaining why — [Amershi et al. 2019](https://research.microsoft.com/%7Ehorvitz/Guidelines_Human_AI_Interaction.pdf)
- Apple's Machine Learning HIG covers patterns for displaying data, handling mistakes and supporting corrections — [Apple HIG ML](https://developer.apple.com/design/human-interface-guidelines/machine-learning.md)

### Inferences
- **Single source of truth.** Panels render deterministic data straight from the domain backend (accounts, transactions, bookings). The LLM picks the panel and its parameters (date range, account, filter) but never produces the figures shown in it. Chat answers that quote numbers should take them from the same query the panel uses. Show a visible link such as "see panel: Spending, Mar 2026" and highlight the referenced row or figure.
- **Show the query, not just a citation.** Because random citations still raise trust (Ding et al.), a citation badge is not enough. Show the panel's filter or provenance in plain words (for example: "Transactions, Checking, 1-31 Mar, category = Dining, 42 items, synced 2h ago") so the user can verify it at a glance.
- **Data freshness and completeness as first-class UI:** last-sync time, missing accounts, and pending transactions. In health, add stronger disclaimers and route to a professional where appropriate.
- **Disagreement handling:** if the agent's interpretation differs from the panel's data, or data is missing, the panel shows an explicit empty or partial state with an explanation. It should never look complete when it isn't.
- **Action confirmation:** for anything that moves money or changes records, use a confirm step showing the exact consequence (HAX G16 "convey the consequences of user actions").

### Gaps
- No 2024-2026 user study was found that tests chat-panel consistency directly (for example, what users do when the chat says X and the panel shows Y). No finance-specific citation study was found.
- No health-specific evidence on AI-driven dashboards was gathered in this pass.

## 5. Should classic navigation remain alongside agent-driven UI? (mental models, discoverability)

### Takeaway
Yes. The evidence favours hybrids. Chat cuts navigation effort for direct-answer questions but does not reliably improve task performance, and free-text input is weak at discoverability. Menus and visible options carry that job. Apple's HIG explicitly asks for a good experience when AI features are unavailable or declined. Adaptive-UI research favours keeping a stable, user-controllable base layer.

### Cited Findings
- An exploratory 2026 mixed-methods study (LLM chatbot vs. dashboard, industrial decision tasks) found the chatbot often reduced navigation and manual processing. However, the perceived drop in effort did not translate into a consistent performance advantage, and the authors favour hybrid systems over replacing dashboards. The sample was small — [arXiv 2605.31224](https://arxiv.org/pdf/2605.31224) (via search summary)
- An Aalto thesis (2019, 17 participants) found users preferred a menu-based chatbot over a purely conversational one, citing ease of use, fewer errors and the convenience of GUI elements — [core.ac.uk](https://core.ac.uk/download/237427409.pdf)
- Related comparative work, cited but not read: Nguyen, Sidorova & Torres 2022 (*Computers in Human Behavior*, chatbot vs. menu interface); Krüger et al. 2021 "Chat or Tap?"; Fergencs & Meier, iConference 2021 (conversational vs. graphical search) — [Fergencs & Meier PDF](https://vbn.aau.dk/files/397932014/iConf2021_Chatbot_final.pdf)
- Practitioners: traditional UIs make options visible, and chat works best paired with lightweight UI elements for discoverability and confirmation — [Chariot Solutions](https://chariotsolutions.com/blog/post/adding-conversational-ai-to-your-app-part-3-the-ux-of-chat-interfaces-what-we-gain-and-lose/); [OpenDialog](https://www.opendialog.ai/articles/the-future-of-user-interfaces-is-hybrid)
- Apple HIG: keep people in control, and ensure a great experience when generative features are unavailable or declined — [Apple HIG](https://developer.apple.com/design/human-interface-guidelines/generative-ai.md)
- NN/g (via secondary source): narrower AI features are easier for new users to understand and adopt than broad, open-ended ones — see Section 2
- Findlater & McGrenere 2004: static menus were faster than adaptive ones, and adaptable menus were preferred — [PDF](https://www.cs.ubc.ca/labs/edapt/papers/findlater2004.pdf)

### Inferences
- **Keep the Money, Invest and Travel tabs** as the stable "map" of the product. Agent-opened panels should be *the same components* as the tab content (deep links into a domain view with filters applied), not a parallel set of UIs. That way, what the agent shows teaches users where things live, which builds a mental model and helps them discover features.
- Offer an "Open in Money" action on agent panels, and an "Ask Prime about this" action on tab views, so the user can move between the two modes freely.
- Use suggestion chips or starter prompts per domain to cover the discoverability gap of free-text chat (HAX G1 and G2: make clear what the system can do, and how well).

### Gaps
- No longitudinal study was found on whether users of agent-first products stop using classic navigation over time. Nexus could instrument this itself by tracking tab vs. chat-initiated panel opens.

## 6. Mobile specifics: thumb reach, keyboard + panel interaction, small screens, native vs. web (including Telegram Mini App)

### Takeaway
Design for one-handed use, with the input and primary controls at the bottom. Use one sheet at a time, nonmodal at peek height. Treat the on-screen keyboard as a layout state that collapses panels. In a Telegram Mini App the app itself already sits in a native bottom sheet whose height changes, so nested bottom sheets and viewport math need care.

### Cited Findings
- Hoober (2013, 1,333 observations): grips were 49% one-handed, 36% cradled and 15% two-handed. About two-thirds of one-handed grips are right-handed. People change grip depending on the task — [UXmatters, Hoober 2013](https://uxmatters.com/mt/archives/2013/02/how-do-users-really-hold-mobile-devices.php)
- NN/g bottom-sheet guidance: nonmodal when minimised and modal when expanded; Back dismisses; clear close control; no stacking — [NN/g](https://www.nngroup.com/articles/bottom-sheet/) (excerpt)
- Telegram Mini Apps: on mobile they open inside a native bottom sheet, minimised by default, and `expand()` makes them full height. On other platforms they open maximised and `expand` does nothing. `isExpanded` reports the state. `viewportStableHeight` is the height in the last *stable* state and is the value to use for pinning elements to the bottom, since the live height changes during drags. A separate fullscreen mode (`requestFullscreen`) removes Telegram's bars — [Telegram Mini Apps docs, Viewport](https://docs.telegram-mini-apps.com/platform/viewport); [Telegram Bot API, Web Apps](https://core.telegram.org/bots/webapps); [pub.dev binding note](https://pub.dev/documentation/new_telegram_web_app/latest/telegram_web_app/TelegramWebApp/viewportHeight.html)
- Telegram Mini Apps 2.0 (Nov 2024) added full-screen support and home-screen shortcuts — [Neowin](https://www.neowin.net/news/telegram-revamps-mini-apps-with-full-screen-support-home-screen-shortcuts-and-a-lot-more/)

### Inferences
- **Mobile layout:** the chat composer is pinned to the bottom in the thumb zone. The domain panel is a nonmodal sheet above it, at peek height showing a one-line summary or key figure, expanding to full screen. Multiple domains appear as horizontally swipeable cards or chips inside one sheet, never as stacked sheets.
- **Keyboard state:** when the composer is focused, collapse the panel to a peek or chip so the conversation stays visible. When the keyboard dismisses, restore the previous state. Pin bottom UI to the stable viewport height (Telegram) or the visual viewport (mobile web), not the live height, to avoid jitter.
- **Telegram Mini App:** call `expand()` at launch for panel-heavy views, or request fullscreen for a dashboard mode. Avoid a custom bottom sheet that competes with Telegram's own drag-to-dismiss gesture.
- **Native app later:** use platform sheet components (UISheetPresentationController detents on iOS, Material bottom sheets on Android) so Back and swipe behaviour match user expectations.

### Gaps
- No published data was found on how the on-screen keyboard behaves inside Telegram Mini Apps (resize vs. overlay, how `viewportStableHeight` changes). This needs device testing on iOS and Android.
- No study was found on chat-plus-sheet interaction costs specifically for AI assistants on mobile.
