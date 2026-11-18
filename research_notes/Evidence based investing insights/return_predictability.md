# Return Predictability for Individual Stocks: What the Evidence Supports (as of Nov 2026)

Scope: academic evidence on signals that predict US stock returns; how much survives out of sample, after publication, after trading costs, and for a retail investor (Singapore-based, holding a handful of US large/mid caps). Written for the Nexus investing area (portfolio, watchlist, movers, alerts, trade plans).

Method note: about 26 searches and fetches. arxiv.org, gwern.net and etf.com could not be fetched from this session (network allowlist), so a few figures come from abstracts and search summaries rather than full text. Where a number comes from my background knowledge of a paper and was not re-checked here, it is marked **[not re-verified]**. Vendor or industry claims are marked **[vendor claim]**.

---

## 1. Factor and anomaly evidence: premia, decay after publication, replication, multiple testing

### Takeaway
Most published anomalies are real in the historical data. Chen & Zimmermann and Jensen-Kelly-Pedersen both reproduce the large majority. But the returns you can expect are much smaller than the published ones: on average about 26% lower out of sample and about 58% lower after publication (McLean & Pontiff 2016), and roughly half lower post-sample in later datasets. Many anomalies fail once microcaps are down-weighted (Hou-Xue-Zhang: 65% fail at |t|≥1.96, 82% at the multiple-testing hurdle). The survivors with the best evidence are the broad, slow, cheap-to-trade themes: value, momentum, profitability/quality, investment, low risk. Even these have long, deep drawdowns.

### Cited Findings
**Post-publication decay**
- McLean & Pontiff (Journal of Finance, 2016) study 97 published cross-sectional predictors. Portfolio returns are **26% lower out of sample** (outside the original sample but before publication) and **58% lower post-publication**. They treat the out-of-sample drop as an upper bound on data mining and the further ~32 points (58−26) as publication-informed trading. They conclude that "investors learn about mispricing from academic publications." — [Counterpoint Funds copy of paper](https://counterpointfunds.com/wp-content/uploads/2017/07/PredictabilityMcleanPontiff.pdf); [typeset.io listing](https://typeset.io/papers/does-academic-research-destroy-stock-return-predictability-3rinmhqstl); DOI 10.1111/jofi.12365
- Earlier working-paper versions (82 characteristics, 2012–2013) reported about a 35% post-publication decline, so the 26%/58% figures belong to the published 97-predictor version. — [Fortune 2012](https://fortune.com/2012/11/02/academics-academia-destroys-stock-picking-strategies/); [MoneySense](https://moneysense.ca/?p=36813)
- Chen & Zimmermann (publication bias paper): post-publication returns are **about 50% smaller** than original-sample returns. Estimated publication bias is only about 12–13%, too small to explain the drop, "suggesting an important role for mispricing" that gets arbitraged away. — [Federal Reserve FEDS 2018-033](https://www.federalreserve.gov/econres/feds/files/2018033pap.pdf)
- Chen, Lopez-Lira & Zimmermann, 199 predictors: "predictability decays by 50% post-sample". Predictors labelled as risk-based by theory decay just as much, so theory does not help pick out the survivors. — [ar5iv 2212.10317](https://ar5iv.labs.arxiv.org/html/2212.10317)
- Ilmanen, Israel, Moskowitz, Thapar & Wang ("Factor Premia and Factor Timing: A Century of Evidence"): out-of-sample factor premia are **about 30% lower** than in-sample, attributed more to overfitting than to informed trading. Premia vary a lot over time. — [Alpha Architect summary](https://alphaarchitect.com/factor-investing-research-on-steroids/)

**Replication**
- Hou, Xue & Zhang (RFS 2020, "Replicating Anomalies"), 452 anomalies with microcaps controlled (NYSE breakpoints, value-weighted returns): **65% fail |t|≥1.96**, including 96% of the "trading frictions" category. At a multiple-testing hurdle of |t|≥2.78, **82% fail**. Microcaps are about 3.2% of market cap but 60.7% of stock count. With equal weights and all-stock breakpoints, 43% fail. — [IDEAS/RePEc](https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html); [CXO Advisory summary](https://www.cxoadvisory.com/big-ideas/most-stock-anomalies-fake-news/)
- Chen & Zimmermann ("Open Source Cross-Sectional Asset Pricing", Critical Finance Review 2022) contest that "fail" framing. For the 161 characteristics that were clearly significant in the original papers, **98% of reproduced long-short portfolios have t>1.96**. They argue that a single t>1.96 rule is the wrong test of reproducibility. Data and code are public and updated each year. — [CFR published PDF](https://cfr.ivo-welch.info/published/papers/chen2021open.pdf); [FEDS 2021-037](https://www.federalreserve.gov/econres/feds/files/2021-037pap.pdf)
- Jensen, Kelly & Pedersen ("Is There a Replication Crisis in Finance?", Journal of Finance 78(5), 2023), Bayesian framework with 153 factors in 93 countries: **~85% of factors replicate**. Replication exceeds 75% in 10 of 13 themes; the exceptions are Seasonality, Leverage and Size. They treat post-publication decline as expected from Bayesian shrinkage, not as proof of data mining. — [CBS publisher's version PDF](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf); [NBER w28432](https://nber.org/system/files/working_papers/w28432/w28432.pdf); the 84.9% and 10-of-13 figures are from secondary summaries: [CXO Advisory](https://www.cxoadvisory.com/?p=35142), [Alpha Architect](https://alphaarchitect.com/is-there-a-replication-crisis-in-finance/)

**Multiple testing**
- Harvey, Liu & Zhu (RFS 29(1), 2016) count 316 factors from 313 published papers and working papers (mid-1960s to 2012). They argue a new factor needs **t>3.0**, not 2.0, and that roughly **a third to a half** of the 296 published "significant" factors are likely false discoveries, depending on the correction. They call 316 a floor, so the right hurdle is probably higher. — [NBER w20592](https://www.nber.org/papers/w20592.pdf); [CXO Advisory](https://www.cxoadvisory.com/big-ideas/taming-the-factor-zoo/)

**Individual themes**
- **Value:** HML underperformed growth from 2007, with a **~55% drawdown by mid-2020**, the largest and longest since 1963. Arnott, Harvey, Kalesnik & Linnainmaa (FAJ 2021) attribute the whole drawdown to a widening valuation spread. Relative valuation fell from the top quartile in 2007 to the bottom percentile in June 2020. Book-to-price misses intangibles; capitalizing them would have added about 2.2 pp/yr to HML since 2008. — [Research Affiliates](https://www.researchaffiliates.com/insights/journal-papers/reports-of-values-death-may-be-greatly-exaggerated); [IDEAS](https://ideas.repec.org/a/taf/ufajxx/v77y2021i1p44-67.html)
- **Momentum and momentum crashes:** Daniel & Moskowitz (JFE 122(2), 2016): momentum earns strong average returns but suffers "infrequent and persistent strings of negative returns." Crashes happen in "panic" states, after market declines and in high volatility, and coincide with market rebounds. Crashes are partly forecastable. A dynamic volatility/mean-scaled version **approximately doubles alpha and Sharpe** of static momentum. — [NBER w20439](https://www.nber.org/papers/w20439); [RePEc](https://econpapers.repec.org/RePEc:eee:jfinec:v:122:y:2016:i:2:p:221-247). The paper reports crash magnitudes of roughly −91% (Jul–Aug 1932) and −73% (Mar–May 2009) for the long-short decile portfolio **[not re-verified]**. The extreme crash returns come mainly from the short (loser) side, so long-only investors bear less of it. — [AQR "Fact, Fiction and Momentum Investing"](https://www.Aqr.Com/-/media/AQR/Documents/Journal-Articles/JPM-Fact-Fiction-and-Momentum-Investing.pdf?sc_lang=en)
- **Insider buying:** Cohen, Malloy & Pomorski (Journal of Finance 67(3), 2012) split insiders into "routine" traders (same calendar month for several years; about 55% of insider trades) and "opportunistic" traders. A strategy following only opportunistic insiders earns **~82 bp/month value-weighted abnormal return**; routine trades earn about zero. Opportunistic trades predict firm news and earnings, analyst and management forecast announcement returns. The most informative are local, non-executive insiders at poorly governed, geographically concentrated firms. — [NBER digest](https://www.nber.org/digest/apr11/w16454.html); [HBS Working Knowledge](https://hbswk.hbs.edu/item/decoding-inside-information); [RePEc](https://econpapers.repec.org/RePEc:bla:jfinan:v:67:y:2012:i:3:p:1009-1043)
- **PEAD:** Martineau ("Rest in Peace Post-Earnings Announcement Drift", Critical Finance Review 2022): drift began disappearing from non-microcap stocks in 2001 and was **gone by 2006 for large stocks**. In microcaps it weakened from 2016. Prices now absorb surprises on announcement day. — [CFR PDF](https://cfr.ivo-welch.info/published/papers/martineau2021rest.pdf); [Now Publishers](https://nowpublishers.com/article/Details/CFR-0122). This is contested: two papers accepted in 2025 report that PEAD is "alive and well," and Subrahmanyam attributes the disagreement to research design (surprise measure, sample, weighting). — [UCLA Anderson Review](https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again)
- **Short interest, market level:** Rapach, Ringgenberg & Zhou (JFE 121(1), 2016): detrended aggregate short interest is "arguably the strongest known predictor of aggregate stock returns," with **annual R² of 12.89% in sample and 13.24% out of sample**. High short interest predicts lower market returns, mainly through a cash-flow channel. Later work disputes the "strongest" claim. The international evidence is mostly supportive (24 of 32 countries). — [RePEc](https://econpapers.repec.org/RePEc:eee:jfinec:v:121:y:2016:i:1:p:46-65); [WashU Source](https://source.washu.edu/2015/05/why-investors-should-listen-to-short-sellers-yes-short-sellers/); [Erasmus thesis citing Priestley 2019](https://thesis.eur.nl/pub/73709/Thesis_Final_Draft.pdf)

### Inferences
- A reasonable planning prior: any published long-short anomaly premium should be cut by about half before treating it as a forward-looking expectation. That is the consensus of McLean-Pontiff, Chen-Zimmermann and Chen-Lopez-Lira-Zimmermann. Then subtract costs (see section 2).
- "Replication crisis" is the wrong framing. The data is largely reproducible. The real problem is that expected premia are small and noisy compared with single-stock volatility, and many anomalies sit in microcaps a Nexus user will not hold.
- Momentum crashes, value's 13-year drawdown and the fading of PEAD in large caps show that even "robust" factors can go a decade or longer without paying. Present any tilt as long-horizon and diversified, never as a short-term call.
- Opportunistic insider buying is one of the more decision-relevant single-stock signals because it is event-based, public (SEC Form 4) and cheap to compute. Its premium is larger in poorly governed, smaller firms than in mega caps, and the 82 bp/month figure is a pre-2012-publication estimate that the decay evidence above says to discount.

### Gaps
- No standard per-factor long-short premium table (for example, from the Jensen-Kelly-Pedersen factor dataset or Ken French's library) was fetched in this session. Profitability (Novy-Marx 2013), investment (Fama-French 2015), low-beta/BAB (Frazzini-Pedersen 2014) and size were not individually sourced here. Their US premia since about 1963 are typically cited at 2–5%/yr long-short before costs **[not re-verified]**.
- Analyst forecast revision and earnings-surprise signals were not separately sourced. PEAD and Cohen-Malloy-Pomorski cover the related news-around-earnings channel.
- Cross-sectional short interest (heavily shorted stocks underperform) was not sourced. Only the aggregate market-timing result is cited.
- International: only Jensen-Kelly-Pedersen (93 countries) and the short-interest 24/32-country result. No deeper non-US analysis.

---

## 2. Long-only, large-cap, net of costs; single-stock signal-to-noise; R² of prediction models

### Takeaway
Costs kill high-turnover anomalies. Only low-turnover strategies (value, size, profitability, investment, and momentum if traded carefully) survive costs at scale. Long-only large-cap implementations capture a meaningful but smaller share of factor premia. At the single-stock level, predictability is tiny: the best ML models reach a **monthly out-of-sample R² of about 0.4%**. Any one stock's month-ahead return is roughly 99.6% noise relative to what these signals can predict. Value comes only from aggregating across many stocks and many periods.

### Cited Findings
- Novy-Marx & Velikov ("A Taxonomy of Anomalies and Their Trading Costs", RFS 2016; NBER w20721), 23 anomalies: strategies with **monthly one-sided turnover <50%** mostly keep significant net spreads when traded with cost-mitigation rules. "Few" higher-turnover strategies survive. The most effective cost-reduction technique is a **buy/hold spread** (enter on a stricter rule than you exit on). Capacity falls with turnover; size, value and profitability have the most capacity. — [NBER](https://www.nber.org/papers/w20721); [paper PDF](https://mysimon.rochester.edu/novy-marx/research/ToAatTC.pdf)
- Average trading costs 1963–2013: size ~5.7 bp/month, value ~5.5 bp/month, momentum ~48.4 bp/month. — [Alpha Architect summary](https://alphaarchitect.com/trading-costs-destroy-factor-investing/)
- Patton & Weller (mutual-fund implementation costs): the difficulty of trading the smallest stocks cuts realizable value and momentum compensation by about **1%/yr**. Real-world fund implementation sharply reduces returns to the value factor. — [Patton & Weller PDF](https://public.econ.duke.edu/~ap172/Patton_Weller_MF_28nov18.pdf)
- Long-only vs long-short: Blitz, Huij, Lansdorp & van Vliet find that costs and decay "may completely offset" the added value of the short leg. A long-minus-market approach has historically been nearly as powerful for individual factors. — [Advisor Perspectives](https://www.advisorperspectives.com/articles/2019/12/09/do-long-only-portfolios-effectively-capture-factor-returns); [Erasmus repository](https://repub.eur.nl/pub/77074)
- Asness, Frazzini, Israel & Moskowitz ("Fact, Fiction and Momentum Investing") rebut the claims that momentum "only works in small stocks" and "doesn't survive trading costs" for long-only investors. **[practitioner (AQR) source]** — [AQR PDF](https://www.Aqr.Com/-/media/AQR/Documents/Journal-Articles/JPM-Fact-Fiction-and-Momentum-Investing.pdf?sc_lang=en)
- Retail vs institutional factor capture (Review of Finance): using tradable mutual-fund and ETF factors, institutions capture the size premium better, while retail investors capture the momentum premium better. — [Review of Finance](https://academic.oup.com/rof/article/29/1/103/7755053)
- Gu, Kelly & Xiu ("Empirical Asset Pricing via Machine Learning", RFS 2020), roughly 30,000 US stocks, 1957–2016, 94 characteristics plus macro interactions: neural networks and trees reach a **monthly out-of-sample stock-level R² of about 0.33–0.40%** (reported as a percent, i.e. 0.004). A value-weighted NN long-short decile spread has an **out-of-sample Sharpe ~1.35**. The abstract claims some ML portfolio strategies exceed Sharpe 2.0. Timing the S&P 500 with NN forecasts gives Sharpe 0.77 vs 0.51 for buy-and-hold. — [NBER w25398](https://www.nber.org/papers/w25398.pdf); [AQR copy](https://www.aqr.com/Insights/Research/Journal-Article/Empirical-Asset-Pricing-via-Machine-Learning?from=learning)
- Individual investor outcomes: Barber & Odean (Journal of Finance 2000), about 66,000 discount-brokerage households, 1991–96. Average turnover was about 75–80%/yr. The most active traders earned about **11.4%/yr net (another cut: 10.0%) vs a 17.9% market return**; infrequent traders earned about 18.5%. — [Odean faculty page](https://faculty.haas.berkeley.edu/odean/papers/returns/returns.html); [CXO Advisory](https://www.cxoadvisory.com/individual-investing/the-lure-of-trading/)

### Inferences
- **Signal-to-noise for one stock.** A typical large cap has annualized volatility of about 25–35%, so about 7–10% monthly standard deviation. An excellent factor signal shifting expected return by 0.3–0.5% per month is about 1/20 of one month's noise. Over a 3-month trade-plan horizon, a strong signal would barely move a "probability of hitting target before stop." This is arithmetic from the R² figures, not a sourced estimate.
- Gu-Kelly-Xiu Sharpe ratios come from **diversified decile portfolios of thousands of stocks, including small and illiquid names, before costs**. They do not carry over to a 5–10 stock retail portfolio. With R² ≈ 0.4%, a single-stock "prediction" is mostly noise.
- For Nexus users in US large/mid caps: (a) costs per trade are low (commission-free or cheap brokers), but FX spreads, SG-specific frictions and the 30% US dividend withholding tax on non-treaty residents add drag; (b) the main cost is behavioural (over-trading, per Barber-Odean). Low-turnover tilts fit; high-frequency signals do not.
- Long-only tilts (for example, preferring profitable, reasonably valued, positive-momentum names) capture part of the premium. The literature backs that as a portfolio-level tilt, not as stock-level forecasting.

### Gaps
- No direct study found of a retail-sized portfolio (5–15 large caps) using factor tilts net of costs and tracking error. Concentration risk would dominate, but no paper was found that quantifies it.
- Effect sizes for long-only large-cap-only factor portfolios (for example, S&P 500-universe quintiles) were not fetched. MSCI and other vendor factor-index histories exist, but those are vendor sources.
- Frazzini, Israel & Moskowitz ("Trading Costs", AQR live execution data) was not fetched.

---

## 3. Machine learning and LLM-based prediction; news and social sentiment

### Takeaway
ML improves on linear models, but the gains come with low R², concentrate in small and illiquid stocks, and are gross of costs. LLM news-sentiment results (Lopez-Lira & Tang) are real in published form, but several papers show LLM backtests are inflated by look-ahead and memorization. Even Lopez-Lira & Tang report that returns fall as LLM adoption rises. Social-media sentiment (StockTwits, Twitter, Reddit WallStreetBets) has weak predictive power at daily and longer horizons. Where it worked (WSB before GameStop), the effect decayed after the platform became famous.

### Cited Findings
- **Gu-Kelly-Xiu:** see section 2. Monthly R² ≈ 0.4%; NN long-short value-weighted Sharpe ≈ 1.35 gross. — [NBER w25398](https://www.nber.org/papers/w25398.pdf)
- **Lopez-Lira & Tang ("Can ChatGPT Forecast Stock Price Movements?", arXiv 2304.07619, revised through Oct 2025):** the sample is chosen to start after ChatGPT's September 2021 training cutoff to avoid look-ahead. GPT headline-sentiment scores predict next-day returns. The authors report that **predictability declines as LLM adoption rises**, consistent with improving price efficiency. — [arXiv listing via econpapers](https://econpapers.repec.org/paper/arxpapers/2304.07619.htm); [arXiv v6](https://arxiv.org/html/2304.07619v6). From the paper and **[not re-verified]**: the effect is concentrated in small stocks and after negative news, and is largest for larger models.
- **Glasserman & Lin (2023), "Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment Analysis":** separate (i) look-ahead bias, where the model knows what happened after a headline, from (ii) a "distraction effect," where general company knowledge contaminates sentiment. Using anonymized headlines, anonymized versions **outperformed in sample**, so distraction mattered more than look-ahead in their test. Both biases mean LLM backtests on in-training periods are unreliable. — [Papers with Code](https://paperswithcode.com/paper/assessing-look-ahead-bias-in-stock-return); [Columbia poster](https://datascience.columbia.edu/wp-content/uploads/2024/01/P021_FB_PosterSession_Fall2023.pdf); [arXiv 2309.17322](https://pdf.arxiv.org/pdf/2309.17322)
- **Gao, Jiang & Yan (2025/26):** propose a statistical test for look-ahead bias in LLM forecasts. Re-running the Lopez-Lira-Tang setup, they find that **memorization substantially amplifies apparent predictive power**. — [arXiv 2512.23847](https://arxiv.org/pdf/2512.23847v1)
- **Lopez-Lira, Tang & Zhu, "The Memorization Problem":** LLMs reproduce past economic and financial values from memory. "The lookahead bias sits in the function rather than the data": the model's weights can encode future information even when inputs are pre-cutoff, so a date split may not remove contamination. — [arXiv 2504.14765](https://arxiv.org/html/2504.14765v2)
- **Social media, StockTwits/Twitter:** a StockTwits study found microblog sentiment **did not predict returns at the daily level**, consistent with most prior work. Negative sentiment predicted returns only within about one hour. — [LSE Business Review](https://blogs.lse.ac.uk/businessreview/?p=22489). Other studies find some predictability (a Cardiff PhD finds StockTwits sentiment predicts returns), and predictability weakens as coverage widens. — [Cardiff thesis](https://orca.cardiff.ac.uk/150474/1/2022wonggkkphd.pdf); [Institutional Investor](https://www.institutionalinvestor.com/article/2bsx05fv46nw5bkj7bu2o/portfolio/the-power-of-social-media-in-predicting-stock-returns). A daily polarity measure "cannot predict next-day returns." — [Springer, Digital Finance](https://link.springer.com/article/10.1007/s42521-023-00102-z)
- **Seeking Alpha crowd:** Chen, De, Hu & Hwang (RFS 27(5), 2014), 2005–2012, more than 7,000 firms. The share of negative words in SA articles and comments predicts future returns and earnings surprises, measured from 48 hours after publication. The "~40% multi-year long-short" figure comes from a press quote, not the paper. Not sponsored by SA. This is a pre-2012 sample. — [RePEc](https://econpapers.repec.org/RePEc:oup:rfinst:v:27:y:2014:i:5:p:1367-1403.); [Alpha Architect](https://alphaarchitect.com/2018/01/academic-research-insight-surprise-seeking-alpha-opinions-have-investment-value/); [Integrity Research](https://www.integrity-research.com/crowd-sourced-stock-ideas-beat-wall-street-analysts/)
- **Reddit WallStreetBets:** Bradley, Hanousek, Jame & Xiao ("Place Your Bets?", RFS 37(5), 2024). **Before the GameStop squeeze**, WSB "due diligence" buy recommendations predicted returns and cash-flow news. The working paper reports about 1.12% two-day abnormal returns for buys and nothing for sells, gross of costs. **After GameStop**, reports shifted toward price-pressure and attention stocks and informativeness declined. — [IDEAS/RePEc](https://ideas.repec.org/a/oup/rfinst/v37y2024i5p1409-1459..html); [CXO Advisory](https://www.cxoadvisory.com/investing-expertise/wallstreetbets-contributors-and-users-skilled); [Such Science](https://suchscience.net/?p=33659)

### Inferences
- Nexus should not show an LLM-generated "buy/sell" or "price direction" forecast as a prediction. Published LLM alpha is next-day, concentrated in small caps, decaying as adoption grows, and its backtests are open to memorization bias. A Nexus user cannot act on it at that speed or capture it at that size.
- LLMs are better used for explanation and context: summarizing why a stock moved, extracting the earnings surprise, flagging guidance changes or insider filings. That is information access, not alpha.
- Any in-house backtest of an LLM signal must use only data after the model's training cutoff. Per Lopez-Lira-Tang-Zhu, even that may not be enough; anonymize entities (Glasserman-Lin) to test for contamination.
- Social sentiment is better used as an attention or risk flag (crowding, meme-stock dynamics, unusual volatility) than as a directional signal.

### Gaps
- Exact Lopez-Lira & Tang effect sizes (Sharpe, daily return spreads, the adoption-decay slope) could not be fetched because arxiv.org was blocked. Sarkar & Vafa (2024) on LLM look-ahead was not located.
- No out-of-sample evidence found on proprietary "AI stock picker" retail products.

---

## 4. Retail-facing prediction products: analyst targets and ratings, Zacks, Seeking Alpha Quant, Morningstar

### Takeaway
Independent evidence that 12-month analyst price targets are accurate is poor. Targets imply returns that are about 15 points too optimistic on average, with average absolute errors around 45%. Only 38% are met at the 12-month horizon, and analysts show no economically meaningful persistent skill. Morningstar fund star ratings have modest predictive value, mainly for avoiding low-rated funds. No credible independent out-of-sample studies were found for Zacks Rank or Seeking Alpha Quant ratings; their performance figures are vendor claims.

### Cited Findings
- Bradshaw, Brown & Huang (Review of Accounting Studies 18(4), 2013), 12-month targets over 2000–2009: target-implied returns **exceed realized returns by 15% on average**; **mean absolute forecast error is 45%**; **38% of targets are met at the end of 12 months**, 64% at some point during the year. Evidence of persistent analyst skill at target prices is "statistically significant but economically weak," and the market does not react more to analysts with better target track records. — [IDEAS/RePEc](https://ideas.repec.org/a/spr/reaccs/v18y2013i4d10.1007_s11142-012-9216-5.html); [FIU listing](https://discovery.fiu.edu/display/pub56754)
- An earlier version (1997–2002, ~100,000 targets) found prices at or above target at the end of 12 months only **26%** of the time. — [CXO Advisory](https://www.cxoadvisory.com/investing-expertise/do-stocks-ever-hit-analyst-target-prices)
- Morningstar fund star ratings: a 2000 JFQA paper studies the stars as predictors of out-of-sample fund performance. Gottesman & Morey find "widespread support" that the post-2002 rating predicts performance "at least within the first three years out of sample". The ratings drive large retail flows (Del Guercio & Tkac). Morningstar's own claims of predictive power over seven years are **[vendor claim]**, and critics note they are implausibly long. Evidence from other markets is mixed (Norway: effects only significant at 2-star downgrades). — [ThinkAdvisor](https://thinkadvisor.com/2010/01/05/when-you-wish-upon-a-star); [Evidence Investor](https://www.evidenceinvestor.com/?p=4118); [ISCTE (Norway)](https://ciencia.iscte-iul.pt/publications/star-rating-fund-flows-and-performance-predictability---evidence-from-norway/66556?lang=en); [Morningstar](https://www.morningstar.com/funds/when-morningstar-downgrades-fund-investors-take-note) **[vendor]**
- Seeking Alpha *crowd text* (not the SA Quant rating) predicted returns in 2005–2012 (Chen-De-Hu-Hwang, section 3). — [RePEc](https://econpapers.repec.org/RePEc:oup:rfinst:v:27:y:2014:i:5:p:1367-1403.)
- A search for independent studies of Zacks Rank returned none. — [search returned only SA results; see section 3 sources]

### Inferences
- Showing "analyst consensus target" or an implied upside without context systematically misleads, because of the ~15-point optimism bias. If Nexus shows targets, pair them with the historical hit rate (about 4 in 10 at 12 months) and the dispersion of targets.
- Zacks Rank is built mainly on earnings estimate revisions, and SA Quant on factor grades (value, growth, profitability, momentum, revisions). Both are repackaged academic signals (revisions, factors) with the same decay and cost issues, and their published track records are vendor-computed.
- Morningstar *stock* fair-value estimates and star ratings for individual equities were not evaluated by any independent source found here. Do not generalize from the fund-rating evidence.

### Gaps
- No peer-reviewed independent evaluations found for Zacks Rank, Seeking Alpha Quant Ratings, or Morningstar equity star ratings and fair values. This needs a targeted follow-up (SSRN search on "Zacks rank" and "Morningstar fair value") before making claims.
- Classic evidence on analyst *recommendation changes* (for example, Womack 1996; Barber, Lehavy, McNichols & Trueman 2001: buy-rated stocks outperform gross, but gains vanish after costs) was not re-sourced in this session **[not re-verified]**.

---

## 5. Market timing and regime prediction (CAPE, Goyal-Welch)

### Takeaway
Most published equity-premium predictors fail out of sample. Goyal-Welch-Zafirov (2024) find that more than a third of post-2008 predictors are no longer significant even in sample, and about half of the rest fail out of sample. Valuation ratios like CAPE are informative about **long-horizon (10-year) average returns** but are poor short-term timing tools. Aggregate short interest is one of the few stronger out-of-sample market predictors.

### Cited Findings
- Goyal, Welch & Zafirov ("A Comprehensive 2022 Look at the Empirical Performance of Equity Premium Prediction", RFS 37(11), 2024) re-examine 29 variables from 26 post-2008 papers plus the original 17 Goyal-Welch variables, to end-2021. **More than one-third no longer significant even in sample**; of the remainder, **about half perform poorly out of sample**; "a small number" do reasonably well in both. The working-paper version said "much of the extant literature seems obsolete." — [SFI](https://sfi.ch/en/publications/a-comprehensive-2022-look-at-the-empirical-performance-of-equity-premium-prediction); [RePEc](https://econpapers.repec.org/RePEc:oup:rfinst:v:37:y:2024:i:11:p:3490-3557.)
- Rapach-Ringgenberg-Zhou: aggregate short interest annual out-of-sample R² about 13% (section 1). — [RePEc](https://econpapers.repec.org/RePEc:eee:jfinec:v:121:y:2016:i:1:p:46-65)
- Gu-Kelly-Xiu NN S&P 500 timing: Sharpe 0.77 vs 0.51 buy-and-hold, gross. — [NBER w25398](https://www.nber.org/papers/w25398.pdf)
- Ilmanen et al.: factor timing over a century adds little reliably. — [Alpha Architect](https://alphaarchitect.com/factor-investing-research-on-steroids/)

### Inferences
- CAPE and other valuation context can fairly be shown as "starting valuations have historically been associated with lower or higher 10-year average returns, with wide uncertainty." It should never drive "sell now" or "buy now" prompts.
- Short-horizon market-regime predictions (next month or quarter) have weak, unstable out-of-sample support. Nexus should not present them.

### Gaps
- Specific CAPE-vs-10-year-return R² figures (often cited at roughly 0.4 in-sample for US 10-year returns, with overlapping-observation problems) and Goyal-Welch 2008's original out-of-sample R² values were not fetched **[not re-verified]**.
- Which specific variables survive in Goyal-Welch-Zafirov was not retrieved (paywalled).

---

## 6. Bottom line: robust enough for "tilts and context" vs never present as predictions

### Takeaway
The evidence supports **portfolio-level, long-horizon, low-turnover context**, not single-stock return forecasts. Nexus can credibly show factor characteristics (valuation, profitability/quality, momentum, beta/volatility, insider buying, estimate revisions) as descriptive context with honest base rates. It should never present point forecasts, "likely to go up" labels, analyst targets as expectations, LLM or sentiment directional calls, or short-term market timing as predictions.

### Cited Findings
- Survivors of replication across methods: value, momentum, profitability/quality, investment and low risk replicate at high rates. Size, leverage and seasonality are weakest. — [Jensen-Kelly-Pedersen via Alpha Architect](https://alphaarchitect.com/is-there-a-replication-crisis-in-finance/); [Hou-Xue-Zhang](https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html)
- Cost survivors: low-turnover anomalies (value, size, profitability, investment) survive costs; high-turnover ones mostly do not. — [Novy-Marx & Velikov](https://www.nber.org/papers/w20721)
- Expected decay: about 26% out of sample, about 58% post-publication, about 50% post-sample in larger datasets. — [McLean-Pontiff](https://counterpointfunds.com/wp-content/uploads/2017/07/PredictabilityMcleanPontiff.pdf); [Chen-Lopez-Lira-Zimmermann](https://ar5iv.labs.arxiv.org/html/2212.10317)
- Stock-level predictability ceiling: monthly R² ≈ 0.4% even with ML. — [Gu-Kelly-Xiu](https://www.nber.org/papers/w25398.pdf)
- Analyst targets are biased upward by about 15 points, with a 45% average absolute error. — [Bradshaw-Brown-Huang](https://ideas.repec.org/a/spr/reaccs/v18y2013i4d10.1007_s11142-012-9216-5.html)
- Retail over-trading costs about 6–7 pp/yr for the most active traders. — [Barber-Odean](https://faculty.haas.berkeley.edu/odean/papers/returns/returns.html)

### Inferences
**Tier A: OK as descriptive tilts or context (with base rates and caveats)**
- Valuation percentile vs history and sector; profitability/quality; 12-1 month momentum; beta/volatility; opportunistic insider *buying* (Form 4); direction of analyst estimate revisions. Frame these as "characteristics historically associated with modestly higher or lower long-run average returns across many stocks," not as forecasts for this stock.
- Portfolio-level factor exposure ("your portfolio leans growth/high-beta/momentum") plus concentration and volatility. This is where the evidence is strongest and most useful.
- Behavioural nudges backed by evidence: turnover and cost awareness (Barber-Odean), and the momentum-crash risk after market selloffs, as risk context.

**Tier B: show only with explicit uncertainty**
- Analyst consensus targets and ratings, only alongside the historical hit rate and dispersion.
- Earnings-event context (surprise, guidance). PEAD in large caps is contested and may be dead, so present it as news, not drift.
- Long-horizon valuation context for the market (CAPE): 10-year bands, not timing.

**Tier C: never present as predictions**
- Stock-level point or direction forecasts ("NVDA likely +8% next month"), ML or LLM "AI score" buy/sell signals, social-sentiment direction calls, short-term market timing, or probabilities of a price outcome that imply skill beyond the base rate. The existing trade-plan "chance of target before stop" from historical replays is a volatility and drift calculation. Label it as such, since factor signals would barely change it.

### Gaps
- No evidence found specific to Singapore retail investors holding US stocks (tax drag from 30% dividend withholding, FX costs) and their interaction with factor tilts.
- Disclosure and regulatory constraints in Singapore (MAS rules on financial advice for app-delivered "insights") were not researched; they are outside this strand but relevant to how Tier A/B content is framed.
