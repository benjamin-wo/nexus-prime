# Regulatory line for investment predictions / personalised investment insights (Singapore-first; US and EU comparison)

> Research notes compiled 2026-11-18. NOT legal advice. Every conclusion about Nexus is marked [needs legal review] and should go to a Singapore lawyer (FAA/SFA practice) before any feature launches.
>
> Method caveat: In this session `www.mas.gov.sg`, `sso.agc.gov.sg` and `singaporelawwatch.sg` could not be fetched (network policy blocked the hosts). Every MAS and statute finding below comes from search-result snippets of primary documents plus law-firm summaries. It has not been read in full. Section numbers and exact wording must be checked against the primary texts. Items from background knowledge that I could not re-verify in this session are labelled **[unverified background]** and kept out of "Cited Findings".

Product context: Nexus (SG retail users, mostly US stocks) shows portfolio, P&L, watchlist, movers and price alerts. Users write their own "trade plans" (entry, targets, stop), and the app returns a "chance of reaching target before stop" plus a verdict. The owner wants to add predictions and insights.

---

## Q1. Singapore: what triggers the Financial Advisers Act (FAA), what exemptions exist, and where do MAS notices and guidelines draw the line?

### Takeaway
Under the FAA, two things are licensable "financial advisory services": "advising others concerning any investment product" and "issuing or promulgating analyses or reports concerning any investment product". Listed and US stocks are capital markets products. The trigger is not limited to *personalised* advice, so a stock-specific prediction or rating feed for Singapore users can be regulated even if it is generic. The available exemptions are narrow: a licensed newspaper proprietor, at most 30 accredited investors, and exempt FIs. None obviously fits an app. MAS's line in its finfluencer guidance is that general education is fine, while recommending specific products or tailoring to a person's circumstances is advice, and a "not financial advice" disclaimer does not cure it. [needs legal review]

### Cited Findings
- **The regulated activity.** MAS lists "issuing or promulgating analyses or reports concerning any investment product" as a regulated financial advisory service under the FAA. A company conducting it must be licensed as a financial adviser unless an exemption applies. — [MAS: Financial advisers (entity types page)](https://www.mas.gov.sg/regulation/capital-markets/understand-the-types-of-capital-market-entities/financial-advisers); [MAS FAA FAQs (24 Nov 2017)](https://www.mas.gov.sg/-/media/mas/regulations-and-financial-stability/regulations-guidance-and-licensing/financial-advisers/faq/faa_faqs_24nov2017.pdf)
- **Who may do it.** Per the MAS FAQ, only licensed financial advisers, and exempt financial advisers who are exempt under (old) s.23(1) of the FAA, may conduct financial advisory services under the FAA. — [MAS FAA FAQs (8 Oct 2018)](https://www.mas.gov.sg/-/media/MAS/Regulations-and-Financial-Stability/Regulations-Guidance-and-Licensing/Financial-Advisers/FAQ/FAA_FAQs-on-Financial-Advisers-Act-Financial-Advisers-Regulations-Notices-and-Guidelines_8-Oct-2018.pdf?la=en&amp=&hash=00BBBE4A5646E0361532CB29D091B2013F6810EA)
- **Section renumbering.** The 2018 MAS FAQ cites the exemption as **s.23(1)(f)**. The later MAS FAQ (file dated 24 Jan 2025, "240125") cites the analyses/reports exemption as **s.20(1)(g)**. This is consistent with renumbering in the FAA 2001 (2020 Revised Edition). Practitioners should use the current SSO consolidation. — [MAS FAA FAQs 2018](https://www.mas.gov.sg/-/media/MAS/Regulations-and-Financial-Stability/Regulations-Guidance-and-Licensing/Financial-Advisers/FAQ/FAA_FAQs-on-Financial-Advisers-Act-Financial-Advisers-Regulations-Notices-and-Guidelines_8-Oct-2018.pdf?la=en&amp=&hash=00BBBE4A5646E0361532CB29D091B2013F6810EA); [MAS FAA FAQs (240125)](https://www.mas.gov.sg/-/media/mas/regulations-and-financial-stability/regulations-guidance-and-licensing/financial-advisers/faq/faqs-on-financial-advisers-act-financial-advisers-regulations-notices-and-guidelines-240125.pdf); [SSO: FAA 2001](https://sso.agc.gov.sg/Act/FAA2001?ProvIds=Sc1-.)
- **Accredited-investor exemption.** A Singapore-resident person who advises, or issues or promulgates analyses or reports, on investment products (other than life policies) to **not more than 30 accredited investors** on any occasion is exempt from holding a financial adviser's licence. The source is FAA s.23(1)(f) (old numbering) read with Financial Advisers Regulations reg 27(1)(d). This does not help a retail app. — [MAS FAA FAQs 2017](https://www.mas.gov.sg/-/media/mas/regulations-and-financial-stability/regulations-guidance-and-licensing/financial-advisers/faq/faa_faqs_24nov2017.pdf)
- **Newspaper exemption.** The FAA exempts a **proprietor of a newspaper holding a permit under the Newspaper and Printing Presses Act 1974**, on four conditions:
  - the paper is distributed generally to the Singapore public;
  - advice and analyses are published only through that newspaper;
  - the proprietor earns no commission or fee beyond subscription and sales;
  - the advice is incidental to the newspaper business.

  The exact current section and Schedule location could not be confirmed. The provision dates back to the 2001 consultation, which listed it among retained exclusions. — [SSO: FAA 2001, Schedule 1 view](https://sso.agc.gov.sg/Act/FAA2001?ProvIds=Sc1-.); [MAS 2001 consultation document on the FAA](https://www.mas.gov.sg/-/media/MAS/resource/publications/consult_papers/2001/Consultation-Document-The-Financial-Advisers-Act-2001.pdf)
- **Research-only firms.** MAS Notice FAA-N06 carves out from its scope firms that "only provide advice by issuing or promulgating research analyses or research reports, whether in electronic, print or other form, concerning any investment product". That is a carve-out from the notice's requirements, not from licensing. — [MAS Notice FAA-N06 (last revised 1 Mar 2022)](https://www.mas.gov.sg/-/media/mas-media-library/regulation/notices/cmg/notice-faa-n06/notice-faa-n06-last-revised-on-1-march-2022.pdf)
- **Publications and writings.** The Financial Advisers Regulations refer to advice given "through publications or writings or by issuing or promulgating research analyses or research reports". The electronic or online medium does not take content outside the FAA. — [Financial Advisers Regulations (MAS PDF)](https://www.mas.gov.sg/~/media/MAS/Regulations%20and%20Financial%20Stability/Regulations%20Guidance%20and%20Licensing/Financial%20Advisers/Regulations/FINANCIAL%20ADVISERS%20REGULATIONS.pdf)
- **Notice on Recommendations (FAA-N16).** FAA-N16 governs how licensed and exempt advisers make recommendations, including fact-finding and suitability. Paragraph 11 lists the client information an adviser must collect. **Paragraph 11A** is the "FAA-N16 Exception" for digital advisers: if the conditions in paras 11A(a)–(e) are met, the adviser need not collect the para 11(c)–(i) information. The latest amendment found is **FAA-N16 (Amendment) 2025, issued 29 Dec 2025**. It provides that paras 10A–10D do not apply to recommendations made through a digital advisory platform that meets all para 11A(a)–(e) conditions. — [FAA-N16 (Amendment) 2025, tracked](https://www.mas.gov.sg/-/media/mas/regulations-and-financial-stability/regulations-guidance-and-licensing/financial-advisers/notices/faa-n16---tracked.pdf); [FAA-N16 consolidated](https://www.mas.gov.sg/-/media/mas/regulations-and-financial-stability/regulations-guidance-and-licensing/financial-advisers/notices/notice-on-recommendations-on-investment-products.pdf)
- **Digital advisory (robo) regime.** MAS's response to feedback on digital advisory services sets these conditions for the exception:
  - the advice must be **fully automated, with no human adviser intervention**;
  - there must be built-in **"knock-out" or threshold questions** that screen out unsuitable clients;
  - the exemption is **restricted in product scope**, with Rajah & Tann's summary of the consultation noting it was for traditional ETFs;
  - MAS declined to extend it to hybrid (human plus digital) models.

  The guideline is **MAS Guidelines on Provision of Digital Advisory Services (CMG-G02)**. Its issue date is **[unverified background]** 8 Oct 2018. The exception does not remove licensing: a digital adviser still needs a CMS licence for fund management or an FA licence, or must be an exempt FI. — [MAS CMG-G02 PDF](https://www.mas.gov.sg/-/media/mas/regulations-and-financial-stability/regulations-guidance-and-licensing/securities-futures-and-fund-management/guidelines-on-provision-of-digital-advisory-services--cmgg02.pdf); [MAS Response to Feedback on Digital Advisory CP](https://www.mas.gov.sg/-/media/MAS/News-and-Publications/Consultation-Papers/Response-to-Feedback-on-Consultation-Paper-on-Provision-of-Digital-Advisory-Services.pdf); [Rajah & Tann summary of CP](https://www.rajahtannasia.com/media/pdf/MAS_CP%20Provision%20on%20Digital%20Advisory%20Services.pdf)
- **Finfluencer advisory letters (Sept 2025).** MAS said it would issue advisory letters to **five content creators** suspected of giving financial advice without a licence, and warned that persistent offenders face enforcement. — [Bird & Bird (2025)](https://www.twobirds.com/en/insights/2025/singapore/mas-introduces-initiatives-to-promote-responsible-online-financial-content-and-issues-advisory-lette); [Bloomberg Law](https://news.bloomberglaw.com/insurance/singapore-warns-content-creators-about-giving-financial-advice); [Lexology](https://www.lexology.com/library/detail.aspx?g=be9b826b-da78-4d21-b01d-43fbda6c34bc)
- **Regularity, not payment, is the test.** In Parliament, MAS said finfluencers who give financial advice must be licensed under the FAA. A person who is **not remunerated** is still considered to have provided financial advice if they make such recommendations **regularly**. Posting general educational content is not financial advice. — [MAS Parliamentary reply 2025](https://www.mas.gov.sg/news/parliamentary-replies/2025/oral-reply-to-parliamentary-questions-on-financial-services-platform-safeguards-and-complaints); [MAS Parliamentary reply 2024 on finfluencer complaints](https://www.mas.gov.sg/news/parliamentary-replies/2024/pq-on-complaints-against-online-finfluencers); [Marketing-Interactive](https://www.marketing-interactive.com/financial-influencers-licensed-regulated-alvin-tan)
- **Disclaimers do not cure advice.** MAS's guidance for content creators states that simply disclaiming "this is not financial advice" "does not absolve you from legal liabilities". Its fundamentals include avoiding specific product endorsements. Law-firm summaries describe the licensing triggers as recommending "specific investment products" or tailoring to an individual's circumstances. (This is secondary paraphrase; the primary MAS "7 Must-Knows" guide was not read.) — [Yuen Law](https://yuenlaw.com.sg/singapore-law/mas-measures-digital-financial-content/); [Chambers](https://chambers.com/articles/tighter-mas-measures-on-digital-financial-content-in-singapore); [Marketech APAC](https://marketech-apac.com/singapore-tightens-grip-on-online-financial-content-with-new-mas-guidelines-warns-against-finfluencer-economy/)
- **False or misleading statements (SFA).** Even when not giving advice, a person must not make false or misleading statements about capital markets products, including on social media. Doing so can be an offence under the Securities and Futures Act. — [CMS (2025)](https://cms.law/en/sgp/legal-updates/singapore-regulator-introduces-conduct-requirements-for-digital-advertising-activities-of-fis-and-warns-finfluencers); [Charltons Quantum](https://charltonsquantum.com/?p=19802)
- **Digital advertising guidelines (FSG-03).** MAS issued **Guidelines on Digital Advertising Activities (FSG-03)** on **25 Sept 2025**, effective **25 Mar 2026**. They apply to FIs and to employees, agencies and finfluencers those FIs engage. — [Chambers](https://chambers.com/articles/tighter-mas-measures-on-digital-financial-content-in-singapore); [CMS](https://cms.law/en/sgp/legal-updates/singapore-regulator-introduces-conduct-requirements-for-digital-advertising-activities-of-fis-and-warns-finfluencers)
- **Enforcement record.** MAS has received fewer than five complaints a year about finfluencers over five years. It has taken enforcement action against six individuals for unlicensed advice in three years, none of them finfluencers. — [Charltons Quantum, summarising Parliament](https://charltonsquantum.com/?p=19802)
- **MAS AI Risk Management Guidelines (final).** MAS issued the final **Guidelines on Artificial Intelligence Risk Management** on **7 Oct 2026**, following Consultation Paper P017-2025 (13 Nov 2025; closed 31 Jan 2026).
  - Scope: all FIs and all forms of AI, including generative AI and AI agents, applied in proportion to risk.
  - Four pillars: board and senior-management oversight; AI identification, inventory and materiality assessment; lifecycle controls (data governance, transparency, fairness, human oversight, testing, pre-deployment review, monitoring, incident and change management); capability and capacity.
  - Effective **7 Oct 2027**, with Sections 5–6 by 7 Oct 2028.
  - Several secondary sources agree on these points. The primary text was not read. — [Bloomberg Professional Oct 2026 brief](https://www.bloomberg.com/professional/insights/regulation/october-2026-global-regulatory-brief-digital-finance/); [PwC Singapore](https://www.pwc.com/sg/en/services/risk/straightaways/mas-ai-risk-management-guidelines.html); [LeapRate](https://www.leaprate.com/regulation/mas-finalises-ai-risk-guidelines-for-financial-firms/); [Allen & Gledhill on the CP](https://www.allenandgledhill.com/sg/publication/articles/31741/mas-consults-on-proposed-guidelines-for-artificial-intelligence-risk-management); [Baker McKenzie on the CP](https://www.bakermckenzie.com/en/insight/publications/alerts/2025/11/singapore-mas-consults-on-ai-risk); [MAS CP page](https://www.mas.gov.sg/publications/consultations/2025/consultation-paper-on-guidelines-on-artificial-intelligence-risk-management)

### Inferences
- **"Generic" is not a safe harbour in Singapore.** The FAA covers issuing analyses or reports on investment products, not only personalised advice. So a feed of stock-specific predictions, ratings or "buy-zone" signals distributed to SG retail users is likely a licensable activity whether or not it is tailored. The US publisher's exclusion has no equivalent here, beyond the narrow newspaper-permit exemption. Personalisation increases the risk; it does not create it. [needs legal review]
- **Nexus does not fit the newspaper exemption.** That exemption requires an NPPA permit and that advice be incidental to the newspaper business. [needs legal review]
- **FAA-N16 and CMG-G02 only matter if Nexus becomes licensed or partners with a licensed FI.** They are the path for doing "real" robo-advice, not a way to avoid licensing. The para 11A exception is product-restricted, historically to plain ETFs. That suggests personalised single-US-stock picking would not even fit the lighter robo pathway. [needs legal review]
- **SFA fund management.** A CMS licence for fund management would be triggered only if Nexus managed portfolios with discretion or auto-traded on users' behalf. A read-only analytics app that executes nothing does not obviously touch it. If any "auto-execute my trade plan" or broker-API execution feature is added, re-assess, including dealing in capital markets products. [needs legal review]
- **AI Risk Management Guidelines apply to FIs, not to Nexus.** They would become directly relevant if Nexus becomes licensed or supplies AI to a licensed FI. They are still a sensible voluntary design benchmark for the AI chat agent: inventory of AI use cases, materiality rating, human oversight, testing, monitoring and incident logs.
- **Where today's features probably sit.** Portfolio display, gains and losses, watchlist, daily movers and user-set price alerts are factual data and tools, and probably lower risk. The trade-plan "verdict" is the existing feature closest to the line because it is product-specific and evaluative (see Q2). [needs legal review]

### Gaps
- **Exact statutory text.** I could not retrieve the current text of FAA 2001 (2020 Rev Ed): the s.2 / First Schedule definition of "financial advisory service", the exemption section (s.20?), and where the newspaper exemption now sits. SSO and MAS were blocked.
- **Current MAS FAA FAQs.** I could not read the FAQ wording on (a) "general" vs "specific" advice, (b) websites, software tools and calculators, (c) research reports. A lawyer should pull the latest MAS FAQs (2025 version, "240125" file) for any FAQ on online tools, calculators or analytics.
- **Recommendation and conduct duties.** The current location and text of the duty to have a reasonable basis for recommendations (old FAA s.27) and the anti-misrepresentation provisions (old s.26/s.28) were not verified.
- **CMG-G02.** Issue date (believed 8 Oct 2018) and current product scope not verified.
- **MAS FEAT Principles (Fairness, Ethics, Accountability, Transparency, Nov 2018) and Veritas toolkit.** Not researched due to the tool budget **[unverified background]**.
- **The "7 Must-Knows" creator guide and FSG-03.** Primary texts not read; the quotations above are via secondary sources.
- **Portfolio analytics.** I found no MAS statement or FAQ specifically on whether personalised analytics on a user's own portfolio count as "advising" when no product is recommended. These are risk metrics, concentration and diversification stats, and factual tax information such as US 30% dividend withholding and US estate-tax exposure for non-residents. Priority question for counsel.

---

## Q2. Are probabilities, ratings, scores or "verdicts" on specific stocks recommendations? What can disclaimers do?

### Takeaway
No Singapore source found addresses "probability of hitting target before stop" scores directly. Every regulator's framing converges on the same point: specific-product evaluation that implies an action (buy, sell, hold, "good trade", "favourable") is the hallmark of a recommendation, while impartial statistical tools and education are not. Disclaimers are expressly *not* a cure in Singapore (MAS) and are weak in the EU (academic analysis). The verdict label is the riskiest element. A neutral probability distribution, computed on the user's own plan, with method disclosed, is the safest presentation. [needs legal review]

### Cited Findings
- **Disclaimers in Singapore.** MAS: "this is not financial advice" disclaimers do not absolve legal liability. — [Yuen Law](https://yuenlaw.com.sg/singapore-law/mas-measures-digital-financial-content/); [Marketech APAC](https://marketech-apac.com/singapore-tightens-grip-on-online-financial-content-with-new-mas-guidelines-warns-against-finfluencer-economy/)
- **MAS's education line.** General educational content is not advice. Specific product endorsements should be avoided. — [MAS Parliamentary reply 2025](https://www.mas.gov.sg/news/parliamentary-replies/2025/oral-reply-to-parliamentary-questions-on-financial-services-platform-safeguards-and-complaints); [Chambers](https://chambers.com/articles/tighter-mas-measures-on-digital-financial-content-in-singapore)
- **US analogue for probability tools.** FINRA Rule 2214 defines an "investment analysis tool" as an interactive technological tool that produces simulations and statistical analyses presenting the likelihood of various investment outcomes. Such tools are an express exception to Rule 2210's general ban on performance projections, subject to Rule 2214's conditions (disclosures on methodology, limitations, and that results are hypothetical). — [FINRA Rule 2210](https://www.finra.org/rules-guidance/rulebooks/finra-rules/2210); [SEC filing SR-FINRA-2026-004](https://www.sec.gov/files/rules/sro/finra/2026/34-106675.pdf); [FinancialRegulationCourses: Rule 2214](https://www.financialregulationcourses.com/dictionary/f/finra-rule-2214)
- **US quant ratings.** In *Lingley v. Seeking Alpha* (SDNY, Aug 2024), the court held that Seeking Alpha's premium service, including its "Quant Rating System" stock ratings, fell within the publisher's exclusion. It distinguished "auto-trading" programs that involved personalised advice and direct execution. — [Katten](https://katten.com/insights/advisories/judge-dismisses-case-against-seeking-alpha-implications-for-publishers-of-financial-information); [Greenberg Traurig (Aug 2024)](https://www.gtlaw.com/en/insights/2024/8/no-need-for-seeking-alpha-to-seek-registration); [Bloomberg Law](https://news.bloomberglaw.com/securities-law/seeking-alpha-wins-dismissal-of-investment-adviser-claims)
- **EU "investment recommendation".** MAR Art. 20 and Delegated Regulation (EU) 2016/958 apply to public communications that recommend or suggest an investment strategy about one or more financial instruments. This captures ratings and price views, which carry methodology and conflict-of-interest disclosure duties. A recent EU finfluencer warning was grounded in MAR and targeted informal opinions on the value or price of an instrument. — [Skadden (Oct 2026)](https://www.skadden.com/insights/publications/2026/10/social-media-meets-financial-regulation); [Regulation Tomorrow (Nov 2026)](https://www.regulationtomorrow.com/2026/11/from-posts-to-penalties-finfluencers-jurisdiction-summary/)
- **EU research on disclaimers.** An academic paper from Ghent University's Financial Law Institute (2023-15) examines the legal implications of finfluencer disclaimers. Its general thrust in the literature is that disclaimers do not override the substance of a personal recommendation. (Title and topic confirmed; detailed conclusions not read.) — [Ghent FLI working paper 2023-15](https://financiallawinstitute.ugent.be/wp-content/uploads/2024/01/2023-15.pdf)

### Inferences
- **The "verdict" output** (for example "favourable", "take it", or a letter grade on a specific stock trade) reads as an evaluative opinion on a specific investment product. In Singapore it is likely to be treated as advising, or as issuing an analysis, concerning that product. The user's ownership of the plan reduces the risk but probably does not eliminate it. Recommended design: remove or neutralise verdict language; show the probability, its distribution and its assumptions; let the user set their own acceptance threshold ("your rule: only take plans ≥ X%"). [needs legal review]
- **The "chance of reaching target before stop" number** is closest to a FINRA-2214-style investment analysis tool. That is a regulated-but-permitted category in the US, with methodology and limitations disclosure. In Singapore no comparable safe harbour was found. Present it as a hypothetical statistical simulation of the user's own parameters (for example a random-walk or volatility model), not as a forecast. Show the model, inputs, historical calibration and limitations. Avoid ranking stocks by it or proactively surfacing "high-probability" setups. [needs legal review]
- **System-generated ratings, scores or "AI predictions" on stocks the user did not ask about** (screeners that rank, "top picks", "likely to rise") cross from tool to analysis or recommendation in every jurisdiction reviewed. In Singapore there is no general publisher's exclusion to fall back on. [needs legal review]
- **Disclaimers** should still be used, to frame content, disclose methodology and limitations, and set expectations. They should not be relied on as the compliance mechanism.

### Gaps
- No MAS FAQ, enforcement case or guidance was found on statistical probability outputs, quant scores or AI-generated stock ratings in apps.
- No Singapore case law on what makes "analyses or reports" regulated in a software context.

---

## Q3. US comparison: Advisers Act, publisher's exclusion, robo-advisers, predictive data analytics, FINRA communications

### Takeaway
The US gives Nexus-type products more room than Singapore. The Advisers Act s.202(a)(11)(D) publisher's exclusion, as read in *Lowe v. SEC* (1985), protects bona fide publications of general and regular circulation that are impersonal, and a 2024 SDNY decision extended it to Seeking Alpha's quant ratings. Personalised, individually tailored advice, or execution, falls outside it. The SEC's 2023 Predictive Data Analytics (PDA) proposal was **withdrawn on 12 June 2025**. AI-driven conflicts remain an exam and enforcement theme. FINRA rules bind broker-dealers, not unaffiliated apps, but Rules 2210 and 2214 are a good template for probability tools.

### Cited Findings
- ***Lowe v. SEC*, 472 U.S. 181 (1985).**
  - The publisher's exclusion covers bona fide publications of general and regular circulation. "Bona fide" means genuine, containing disinterested commentary and analysis rather than promotional material.
  - The exclusion separates genuine publishers from "hit and run tipsters" and "touts".
  - The Lowe newsletters qualified because they were offered to the general public on a regular schedule and did not give individualised advice.
  - "The mere fact that a publication contains advice and comment about specific securities does not give it the personalized character that identifies a professional investment adviser."

  — [Justia: Lowe v. SEC](https://supreme.justia.com/cases/federal/us/472/181/); [govinfo US Reports 472/181](https://www.govinfo.gov/content/pkg/USREPORTS-472/pdf/USREPORTS-472-181.pdf); [MTSU First Amendment Encyclopedia](https://firstamendment.mtsu.edu/article/lowe-v-securities-and-exchange-commission/)
- ***Lingley v. Seeking Alpha* (SDNY, Aug 2024).** The court read "regular" to include publications updated in response to breaking news. "General and regular circulation" was met where content is advertised and sold in an open market and updated regularly. The decision distinguished auto-trading or personalised services. Commentators warn that model-portfolio and quant providers should stay vigilant. — [Katten](https://katten.com/insights/advisories/judge-dismisses-case-against-seeking-alpha-implications-for-publishers-of-financial-information); [GT Law](https://www.gtlaw.com/en/insights/2024/8/no-need-for-seeking-alpha-to-seek-registration); [Law360](https://law360.com/articles/1870458)
- **SEC PDA proposal withdrawn.** On **12 June 2025** the SEC withdrew 14 pending proposals, including the Aug 2023 proposal on conflicts of interest from broker-dealers' and advisers' use of predictive data analytics. Any future rule would need a fresh proposal and comment period. Staff may still raise these issues in exams. — [Vedder Price](https://vedderprice.com/sec-withdraws-numerous-proposed-rules); [Paul Hastings](https://www.paulhastings.com/insights/client-alerts/sec-withdraws-14-pending-rule-proposals); [Haynes Boone](https://www.haynesboone.com/news/alerts/impact-of-the-secs-withdrawal-of-proposed-rules-on-investment-management-clients.pdf); [Sewkis](https://www.sewkis.com/publications/sec-withdraws-14-proposed-rules-impacting-investment-advisers-investment-companies-and-broker-dealers)
- **FINRA Rule 2210.** The rule generally prohibits projections of performance, with exceptions including investment analysis tools compliant with Rule 2214. FINRA filed **SR-FINRA-2026-004** (Federal Register, 25 Feb 2026) to permit projections and targeted returns under conditions. One vendor source claims SEC approval on 15 Oct (2026); I could not confirm this from a primary source. — [FINRA Rule 2210](https://www.finra.org/rules-guidance/rulebooks/finra-rules/2210); [Federal Register 25 Feb 2026](https://www.federalregister.gov/documents/2026/02/25/2026-03705/self-regulatory-organizations-financial-industry-regulatory-authority-inc-notice-of-filing-of-a); [K&L Gates (23 Feb 2026)](https://www.klgates.com/thought-leadership/FINRA-Meets-the-Marketing-RuleMostly-Performance-Projections-and-Targeted-Returns-Under-Proposed-Amendments-to-Rule-2210-2-23-2026); [Botminds (vendor, unverified approval claim)](https://www.botminds.ai/solutions/sec-marketing-rule-compliance/finra-rule-2210-changes-projections)

### Inferences
- **A US-style publisher model** (same content to all subscribers, regular, disinterested) would probably work for a US audience. It does not transfer to Singapore, where Nexus's users are. The SG FAA has no equivalent general exclusion. [needs legal review]
- **US securities law reach.** It is likely engaged only if Nexus targets US persons. For SG-resident users holding US stocks, the governing licensing regime is Singapore's. [needs legal review]

### Gaps
- Not researched within budget: SEC 2017 IM Guidance Update on robo-advisers **[unverified background: IM Guidance Update No. 2017-02, Feb 2017]**; Reg BI's definition of "recommendation" for broker apps; the SEC 2021 digital engagement practices request; post-withdrawal SEC AI statements and enforcement ("AI-washing" cases, 2024).

---

## Q4. EU comparison (brief): MiFID II investment advice vs MAR investment recommendations; ESMA on finfluencers and AI

### Takeaway
The EU splits the analysis in two:
- **MiFID II "investment advice"** requires authorisation. It means a *personal* recommendation, presented as suitable for the person or based on their circumstances.
- **MAR Art. 20 "investment recommendations"** are public recommendations, such as ratings and price views. They need no licence but carry disclosure duties.

ESMA's 2023 supervisory briefing warns that apps, websites and influencer content can amount to personal recommendations when personalised.

### Cited Findings
- **Personal recommendation (MiFID II).** A recommendation must be presented as suitable for the person or based on a consideration of their circumstances. Information in newspapers or on TV is treated as issued exclusively to the public, so it is not a personal recommendation. — [ESMA35-43-3861 Supervisory briefing on the definition of advice under MiFID II (July 2023)](https://www.esma.europa.eu/sites/default/files/2023-07/ESMA35-43-3861_Supervisory_briefing_on_understanding_the_definition_of_advice_under_MiFID_II.pdf); [PwC Legal](https://legal.pwc.de/content/services/regcore-client-alert/esma-expands-on-how-to-interpret-the-definition-of-investment-advice.pdf)
- **Online channels.** ESMA (2023): websites, apps and social media, including influencer content, can in certain instances be personal recommendations. Content created for a specific target audience that includes personalised information may also qualify. — [Freshfields](https://www.freshfields.com/en/our-thinking/blogs/risk-and-compliance/understanding-the-definition-of-investment-advice-under-mifid-esma-revises-13-y-102ik46); [Dillon Eustace](https://www.dilloneustace.com/insights/legal-insights/the-definition-of-advice-under-mifid/)
- **MAR Art. 20 and finfluencers.** Art. 20 and Delegated Regulation 2016/958 impose methodology and conflict disclosures on public recommendations. Paid coaching, portfolio reviews or personalised model portfolios can convert public recommendations into MiFID investment advice. — [Skadden (Oct 2026)](https://www.skadden.com/insights/publications/2026/10/social-media-meets-financial-regulation); [Regulation Tomorrow (Nov 2026)](https://www.regulationtomorrow.com/2026/11/from-posts-to-penalties-finfluencers-jurisdiction-summary/)

### Inferences
- **EU mapping of Nexus.** A Nexus prediction on a stock, pushed because the user holds it or because it suits their profile, would look like a MiFID personal recommendation. A non-personalised public rating would be a MAR recommendation with disclosure duties.
- **Personalisation is the key variable in both the EU and the US.** In Singapore the analyses-or-reports limb means it is only an aggravating factor. [needs legal review]

### Gaps
- Not researched: ESMA statements on AI in investment services (ESMA public statement on AI, May 2024 **[unverified background]**); EU AI Act classification of investment-advice AI; ESMA/NCA 2024–2025 finfluencer guidance beyond the summaries above.

---

## Q5. Practical design patterns that keep an app on the safe side

### Takeaway
Across all three regimes, five patterns keep an app on the safe side:
1. Factual data and analytics about the user's own holdings, without product recommendations.
2. User-authored rules, executed and evaluated neutrally.
3. Education framed generically, not product-specific.
4. Transparent methodology and limitations for any statistical output.
5. No proactive, system-originated "buy, sell or hold X" signals or rankings for retail SG users.

Anything beyond that, such as AI-generated stock predictions, "edge" signals or personalised picks, realistically needs either an FA or CMS licence or delivery through a licensed partner (or the partner's representative arrangement) in Singapore. [needs legal review]

### Cited Findings
- **Licensing triggers.** MAS's line for creators is that education is fine and avoiding specific endorsements and tailoring is needed. Regularity triggers advice even without pay, and disclaimers do not cure it. — [MAS Parliamentary reply 2025](https://www.mas.gov.sg/news/parliamentary-replies/2025/oral-reply-to-parliamentary-questions-on-financial-services-platform-safeguards-and-complaints); [Chambers](https://chambers.com/articles/tighter-mas-measures-on-digital-financial-content-in-singapore)
- **Probability tools must disclose method and limitations.** Under FINRA 2210/2214, probability tools are acceptable when they are interactive, user-driven and accompanied by disclosure of methodology and limitations. — [FINRA Rule 2210](https://www.finra.org/rules-guidance/rulebooks/finra-rules/2210); [SR-FINRA-2026-004 filing](https://www.sec.gov/files/rules/sro/finra/2026/34-106675.pdf)
- **Personalised, executable advice loses the publisher protection** in the US (Lowe; Seeking Alpha distinguished from auto-trading). — [Katten](https://katten.com/insights/advisories/judge-dismisses-case-against-seeking-alpha-implications-for-publishers-of-financial-information)
- **Licensed robo pathway.** Singapore's robo pathway is fully automated, has knock-out suitability questions and is product-limited. It requires a licence. — [MAS response to digital advisory CP](https://www.mas.gov.sg/-/media/MAS/News-and-Publications/Consultation-Papers/Response-to-Feedback-on-Consultation-Paper-on-Provision-of-Digital-Advisory-Services.pdf)
- **AI governance benchmark.** MAS AI RM Guidelines (7 Oct 2026): AI inventory, materiality assessment, human oversight, testing, monitoring and incident management. — [PwC Singapore](https://www.pwc.com/sg/en/services/risk/straightaways/mas-ai-risk-management-guidelines.html)
- **No false or misleading statements (SFA).** This applies whether or not content is advice. — [CMS](https://cms.law/en/sgp/legal-updates/singapore-regulator-introduces-conduct-requirements-for-digital-advertising-activities-of-fis-and-warns-finfluencers)

### Inferences (proposed feature triage for Nexus; all [needs legal review])
- **Lower risk (factual or user-directed):**
  - Portfolio value, P&L, allocation by sector, country and currency.
  - Concentration and diversification metrics. Historical volatility, drawdown and beta of the *user's own* portfolio.
  - Price alerts and movers.
  - Factual tax facts, such as US dividend withholding and US estate-tax thresholds for non-resident aliens, stated as facts with no product steer.
  - Earnings calendars and news.
  - Backtests of *user-defined* rules.
- **Medium risk (needs careful framing):**
  - The trade-plan probability. Keep it, reframed as a "statistical simulation of your plan": show the model and assumptions, a calibration record and "hypothetical, not a forecast" text, with no colour-coded verdict.
  - "What-if" scenario tools, such as rebalancing to user-chosen weights.
  - Generic educational explainers in the AI chat, for example "how stop-losses work" or "what beta means".
  - Statements of fact about a stock (P/E, analyst consensus *as reported by third parties*, with attribution).
- **High risk (likely regulated advice or analysis in SG without a licence):**
  - System-generated predictions of price direction for named stocks; "buy, sell or hold" or "take this trade" verdicts.
  - Rankings or "top picks"; "stocks likely to rise" feeds.
  - The AI agent answering "should I buy X?" or "which of my holdings should I sell?" with a product-specific answer.
  - Personalised rebalancing suggestions naming specific securities.
  - Anything that auto-executes.
- **AI chat agent guardrails:**
  - Refuse or redirect product-specific buy/sell questions toward criteria-based education ("here are the factors people consider…") and the user's own rules.
  - Never output price targets.
  - Log prompts and outputs for audit.
  - Monitor for drift, so the agent does not start to "recommend".
  - Keep an AI-use inventory and incident process, mirroring the MAS AI RM Guidelines voluntarily.
  - Ensure statements are not false or misleading (SFA exposure).
- **Record-keeping.** Keep versioned model documentation for any probability or score, the calibration and backtest evidence, disclaimer and terms versions, and chat transcripts. These support defence against misleading-statement claims and any future licensing application.
- **Path to "edge" features.** If the owner wants true prediction or insight features, consider:
  - (a) partnering with a licensed SG financial adviser or CMS holder who issues the content under its licence, with Nexus as technology provider;
  - (b) applying for an FA licence, which brings FAA-N16 suitability and the CMG-G02 pathway;
  - (c) restricting the content to accredited investors, using the ≤30 AI exemption or a licence.

### Gaps
- No primary MAS source was found on whether *third-party* aggregated content (analyst consensus ratings, news sentiment) re-presented in an app constitutes "promulgating" analyses. Ask counsel.
- No source checked on whether a Singapore-incorporated unlicensed app serving SG users from offshore servers changes the analysis (FAA territorial scope). Likely not, but confirm.
- Record-keeping obligations for unlicensed entities: none identified. PDPA (personal data) obligations apply regardless but were not researched.

---

### Questions to put to Singapore counsel (consolidated)
1. Is the trade-plan "probability + verdict" feature a financial advisory service under the FAA (advising or analyses limb)? Would removing the verdict change the answer?
2. Does a quantitative score or rating on specific US stocks shown to SG retail users require an FA licence even if it is identical for all users?
3. What are the current FAA 2001 (2020 Rev Ed) section numbers and wording for the definitions, exemptions (s.20?) and newspaper exemption? Are there exemptions for "software tools" or "calculators" in the latest MAS FAQs?
4. Where do personalised portfolio analytics (risk metrics, concentration, tax facts) fall?
5. Can an AI chat agent's answers to "should I buy X" be made safe by refusal design? What residual SFA misleading-statement risk remains?
6. What structure would let Nexus offer prediction features via a licensed partner (licensed FA, CMS holder, or representative arrangement), and what obligations would flow down (FAA-N16, FSG-03, AI RM Guidelines)?
