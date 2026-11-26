# Portfolio-level and behavioural insights that improve retail investor outcomes (Singapore residents holding US stocks)

Research date: 2026-11-18. Method: about 15 web searches. Two direct page fetches failed because the session network blocks those hosts (stashaway.sg, faculty.haas.berkeley.edu), so many figures below come from search-result excerpts of primary or near-primary pages and are not full-text reads. Figures I could not confirm are listed under Gaps, with the value as I remember it from the literature marked "unverified". Anything about tax should be reviewed by a tax professional before the app shows it as a fact.

## 1. Concentration and diversification (single-stock risk, skewness, how many stocks, concentration measures)

### Takeaway
Long-run stock returns are extremely positively skewed. Most individual US stocks underperform T-bills over their lifetimes, and a few percent of stocks account for all net wealth creation. A concentrated portfolio is therefore most likely to miss those few stocks and lag the index. This is the strongest evidence-based reason for an app to flag concentration. Older work said 30-40 random stocks diversify a portfolio. Newer simulations suggest far more are needed to remove stock-specific risk, especially in a global portfolio.

### Cited Findings
- Bessembinder (2018), "Do stocks outperform Treasury bills?", *Journal of Financial Economics* 129(3):440-457. The best-performing ~4% of listed companies explain the entire net gain of the US stock market since 1926. Other stocks collectively matched T-bills. — [ASU W.P. Carey](https://wpcarey.asu.edu/index.php/department-finance/faculty-research/do-stocks-outperform-treasury-bills); [RePEc](https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:3:p:440-457)
- Precise figures (1926-2016): all of the $35 trillion of wealth created above T-bills came from 1,092 companies, 4.3% of the nearly 26,000 stocks. More than half came from just 90 companies, under one-third of 1%. — [ASU news](https://news.wpcarey.asu.edu/20181212-research-shows-most-stocks-haven%E2%80%99t-outperformed-treasury-bills)
- About 58% of stocks failed to beat one-month T-bill returns over their lifetimes. Long-horizon returns are positively skewed: a few very large winners pull up the average, while most stocks post modest or negative returns. The paper says this helps explain why poorly diversified active strategies most often underperform market averages. — [ASU news](https://news.wpcarey.asu.edu/20181212-research-shows-most-stocks-haven%E2%80%99t-outperformed-treasury-bills); [ASU summary](https://blogs.wpcarey.asu.edu/20180917-do-stocks-outperform-treasury-bills)
- Global extension (Bessembinder and co-authors): 55.2% of US stocks and 57.4% of non-US stocks underperform one-month US T-bills over the full sample. ASU's update extends the US analysis to over 29,000 stocks from 1926 through 2023. — [ASU W.P. Carey](https://wpcarey.asu.edu/index.php/department-finance/faculty-research/do-stocks-outperform-treasury-bills)
- Statman (1987), *JFQA* 22(3):353-363. A well-diversified portfolio of randomly chosen stocks needs at least 30 stocks for a borrowing investor and 40 for a lending investor, contradicting the then-common view that about 10 stocks are enough. — [IDEAS/RePEc](https://ideas.repec.org/a/cup/jfinqa/v22y1987i03p353-363_01.html); [Cambridge](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/how-many-stocks-make-a-diversified-portfolio/CE5CDF2C7225FC1E0EDE3E700A3C66A7)
- An Erasmus University paper using Monte Carlo simulation of global stocks argues that removing idiosyncratic risk takes far more than 30-40 stocks, possibly as many as 750 in a global portfolio. (The search snippet called it a 2025 study, but the repository URL is "2010-0822", so the date is uncertain.) — [Erasmus repository](https://repub.eur.nl/pub/20749/2010-0822.pdf)
- Practitioner guidance: the number of stocks is only part of diversification. Sector spread and roughly equal weighting also matter. — [Kiplinger](https://www.kiplinger.com/investing/stocks/604724/how-many-stocks-should-you-have-in-your-portfolio)

### Inferences
- **Insight the app can compute: concentration score.**
  - HHI = Σ wᵢ², using market-value weights.
  - Effective number of holdings N_eff = 1/HHI. Example: 10 stocks with one at 50% gives N_eff of about 3.4, not 10.
  - Flag thresholds based on the Statman and Bessembinder framing: largest position above ~20%, top 3 above ~50%, or N_eff below ~10 for an all-single-stock portfolio.
  - Count a broad index ETF as "many bets" by looking through to its holdings, or give it a high N_eff.
- **Insight: "odds a single stock beats cash".** Bessembinder's 58% lifetime T-bill underperformance rate gives a factual, non-predictive message: "Historically, most individual US stocks underperformed T-bills over their lifetime; a handful drove all the gains." This suits users with one or two dominant positions.
- **Sector, country and currency concentration.** A Singapore user holding only US stocks has close to 100% USD and US-country exposure. It is worth showing USD share of net worth. SGD-based investors carry USD/SGD currency risk on every holding.
- Showing look-through exposure matters for US mega-cap tech. A user holding QQQ plus AAPL, MSFT and NVDA directly is more concentrated than the holding count suggests. This is an inference; I found no study quantifying it for app users.

### Gaps
- Campbell, Lettau, Malkiel and Xu (2001, *JF*) found that idiosyncratic volatility rose and more stocks are needed to diversify, with about 50 by the late 1990s in my memory (unverified). The search did not return the paper.
- Domian, Louton and Racine (2007, *Financial Review*), "Diversification in portfolios of individual stocks: 100 stocks are not enough", was not confirmed in search. Title and conclusion are from memory and unverified.
- I found no direct evidence that showing a concentration score to retail users changes behaviour or improves returns.
- I found no source on how concentrated typical Singapore retail US-stock portfolios are.

## 2. Risk decomposition (factor exposure, risk contribution, correlation clusters)

### Takeaway
I gathered no new empirical sources on factor decomposition for retail users within the tool budget. The methods are standard and computable from holdings and price data. I found no evidence that showing users their factor exposures improves outcomes, so treat this as a plausible feature, not an evidence-backed one.

### Cited Findings
- No primary sources were retrieved this session for Fama-French factor regressions on retail portfolios or for evidence that risk displays help. See Gaps.
- Indirect support: poorly diversified active strategies tend to underperform because of return skewness (Bessembinder). — [ASU summary](https://blogs.wpcarey.asu.edu/20180917-do-stocks-outperform-treasury-bills)
- Indirect support: Morningstar finds the investor return gap is larger for more volatile funds (-2.1 pp) than for the least volatile (-0.4 pp). This suggests volatile exposures cause worse investor behaviour, which argues for making risk visible. — [Morningstar Mind the Gap 2025](https://www.morningstar.com/business/insights/research/mind-the-gap-2025) (figures from search excerpts of the report and coverage)

### Inferences
These are standard methods the app can compute; they are definitions, not empirical claims.
- **Portfolio beta.** β_p = Σ wᵢ βᵢ, where each stock's β comes from regressing its excess returns on market excess returns (for example, 2-5 years of monthly or weekly data against the S&P 500 or MSCI ACWI).
- **Factor exposures.** Regress the portfolio's excess returns on Fama-French 5 factors plus momentum (Mkt-RF, SMB, HML, RMW, CMA, UMD). Factor data is free from the Kenneth French Data Library. Use at least 36 monthly observations, or holdings-weighted per-stock loadings for a new portfolio. Report the loadings plainly, for example "Your portfolio behaves like 1.3x the market, tilted to growth/small-cap".
- **Risk contribution.** With weights w and covariance Σ, σ_p = √(wᵀΣw).
  - Marginal contribution: MCRᵢ = (Σw)ᵢ / σ_p.
  - Risk contribution: RCᵢ = wᵢ·MCRᵢ.
  - Percentage contribution: %RCᵢ = RCᵢ/σ_p, which sums to 100%.
  - Useful insight: "NVDA is 15% of your money but 35% of your risk."
- **Correlation clusters.** Run hierarchical clustering on the return correlation matrix, for example 1-year daily returns. Holdings with correlation above ~0.7 act as one bet. Feed this into an effective-number-of-bets measure, for example 1/Σ(%RCᵢ²) or a PCA-based Meucci entropy measure.
- **Volatility-scaled loss framing.** For example: "In a 2008-like drawdown, a portfolio with your beta might fall ~X%". This is an inference; I found no evidence on whether drawdown framing changes behaviour.

### Gaps
- I found no study showing that displaying factor exposure or risk contribution to retail investors improves returns or reduces bad trades.
- Fama-French factor definitions and data were not re-verified this session; the Kenneth French Data Library is the canonical source.
- I found no evidence on retail-user comprehension of beta or factor language.

## 3. Costs: fees, FX conversion, spreads, and tax drag (Singapore specifics)

### Takeaway
For a Singapore resident holding US securities, the big, verifiable cost items are:
- **30% US dividend withholding**, because there is no US-Singapore income tax treaty. Irish-domiciled UCITS ETFs reduce this to about 15%, taken at fund level.
- **US estate tax exposure** on US-situs assets (US shares and US-domiciled ETFs) above USD 60,000. The threshold is not inflation-indexed, and graduated rates reach 40%.
- **FX conversion spreads**, from about 0.002-0.15% at low-cost brokers to 0.5-1.5% at banks or typical retail FX.

Singapore does not tax capital gains, though I did not verify that this session. All of this needs tax-professional review before the app shows it.

### Cited Findings
- **US estate tax, filing threshold (IRS).** A Form 706-NA return is required when the value at death of a nonresident alien decedent's US-situated assets exceeds $60,000. — [IRS: Some nonresidents with U.S. assets must file estate tax returns](https://irs.gov/individuals/international-taxpayers/some-nonresidents-with-u-s-assets-must-file-estate-tax-returns)
- **How the $60,000 works.** It is a $13,000 unified credit, equal to the tax on the first $60,000. It is not inflation-indexed. Taxable amounts above it face graduated rates from 18% up to 40%.
- **What counts as US-situs.** US real estate, tangible property in the US, shares in US corporations, certain US debt, and US trade or business interests. Ordinary US bank accounts not connected to a US trade or business are generally not US-situs.
- **Treaties.** An estate tax treaty can change the outcome, but filing may still be required. — sources for these three points: [TaxesForExpats](https://www.taxesforexpats.com/articles/non-us-citizens/nonresident-alien-estate-tax-exemption-us-situs-assets.html); [The Tax Adviser (AICPA), Apr 2025](https://www.thetaxadviser.com/issues/2025/apr/estate-tax-considerations-for-non-us-persons-owning-us-real-estate/); [EY](https://ey.com/en_uk/tax/how-to-navigate-us-estate-tax)
- **Singapore 2026 guides on estate tax.** US-domiciled ETFs expose a non-US person's estate to up to 40% US estate tax above about USD 60,000. Irish UCITS funds are Irish legal entities, so they are generally treated as outside US-situs. Singapore abolished its own estate duty in 2008. — [StashAway 2026 guide](https://www.stashaway.sg/r/dividend-withholding-tax-estate-tax-us-equities-singapore); [FinancialHorse](https://financialhorse.com/die-holding-us-stocks-and-pay-40-tax-what-singapore-investors-need-to-know-about-us-inheritance-estate-tax/); [Endowus](https://endowus.com/insights/an-inconvenient-truth-tax-on-us-listed-etfs-04c7532c5d) (all secondary, from search excerpts)
- **Dividend withholding.** US-source dividends paid to a Singapore resident face the 30% statutory rate because there is no US-Singapore income tax treaty. Irish-domiciled funds get 15% on US dividends inside the fund under the US-Ireland treaty, and Ireland adds no further withholding on payouts to non-Irish residents. The 15% is "reduced, not eliminated". — [FSMOne: VOO vs SPYL](https://secure.fundsupermart.com/fsmone/article/rcms379324/voo-vs-spyl-what-the-etf-domicile-means-for-singapore-investors); [StashAway Ireland ETF guide](https://www.stashaway.sg/r/guide-ireland-domiciled-etfs-singapore); [Beansprout](https://growbeansprout.com/ucits-etf-singapore)
- **Treaty status.** The IRS keeps the list of US income tax treaties in force (Table 3 and the A-Z page). A 2026 commercial guide states the US has no income tax treaty with Singapore. — [IRS A-Z](https://irs.gov/businesses/international-businesses/united-states-income-tax-treaties-a-to-z); [IRS Table 3](https://www.irs.gov/pub/irs-lbi/table-3-list-of-tax-treaties.pdf); [TaxesForExpats treaty guide](https://www.taxesforexpats.com/articles/expat-tax-rules/us-tax-treaties.html)
- **Caveat on Irish funds.** UCITS ETFs "are not automatically superior". Expense ratios differ (for example VOO 0.03% vs CSPX 0.07%) and can offset part of the withholding saving. — [Saxo SG, Jul 2026](https://www.home.saxo/en-sg/content/articles/equities/ucits-etfs-24072026); [Syfe](https://syfe.com/magazine/?p=20381)
- **FX conversion costs (2026, third-party, may be out of date).**
  - Tiger Brokers: about 0.15% on SGD to USD, roughly SGD 15 per SGD 10,000. — [The Kopi Notes](https://thekopinotes.com/articles/etfs/tiger-brokers-fees-singapore-guide/)
  - Interactive Brokers: sources conflict, at about 0.002%, about 0.03% and about 0.08%. — [The Money Bees](https://themoneybees.co/blog/interactive-brokers); [SG Finance Calculators](https://sgfinancecalculators.com/blog/currency-conversion-custody-fee-wrap-fee-comparison/)
  - Syfe: 0.09-0.12%. — [Syfe](https://www.syfe.com/magazine/?p=38912)
  - Phillip Nova: as low as 0.12%. — [Phillip Nova fees](https://www.phillipnova.com.sg/fees-charges/)
  - Banks: about SGD 50-100 per SGD 10,000 (0.5-1%). Typical retail FX: 0.5-1.5%. — [SG Finance Calculators FX tool](https://sgfinancecalculators.com/invest/currency-conversion-fee-impact-tool/); [StraitsX](https://www.straitsx.com/blog-post/best-way-to-convert-sgd-to-usd)
  - I found no source for moomoo's FX spread.
- **Trading costs.** In Barber and Odean's 1990s data, the average round-trip trade above $1,000 cost about 3% in commissions and 1% in bid-ask spread. Commissions are now near zero at many brokers, but spreads remain. — [CXO Advisory summary of Barber & Odean 2000](https://www.cxoadvisory.com/?p=191); [NBER w16022](https://www.nber.org/papers/w16022.pdf)

### Inferences
- **Withholding drag calculator** (illustrative; the yield is a user input, not a sourced figure).
  - Annual drag = dividend yield × withholding rate.
  - For a US-domiciled S&P 500 ETF at about 1.3% yield: 30% × 1.3% ≈ 0.39%/yr.
  - For an Irish accumulating ETF: about 15% × 1.3% ≈ 0.20%/yr, plus a slightly higher TER.
  - Net saving is about 0.15%/yr before the TER difference. For high-dividend holdings such as REITs or value stocks, the 30% leakage matters more.
  - The app can compute this per holding: Σ (position value × trailing dividend yield × 30%).
- **US-situs estate exposure meter.** Sum of US-listed stocks, US-domiciled ETFs and other US-situs holdings, compared with USD 60,000. Mark Irish UCITS and SGX-listed funds as "generally non-US-situs (verify)". Show "estimated exposure above threshold". Do not compute an actual tax figure; recommend professional advice.
- **FX cost tracker.** For each SGD to USD conversion: implied cost = (mid-market rate − rate received) / mid. Annualise across conversions. Nudge users to convert in larger, less frequent batches, or to keep USD to avoid round-trip conversion on every trade.
- **Total cost of ownership per holding:** TER + withholding drag + estimated spread × annual turnover + FX cost × conversions.
- Because Singapore has no capital gains tax (unverified this session), tax-loss harvesting has no Singapore tax value for most individuals. US tax-loss harvesting features (for example the wealth-management:tlh skill) are not relevant to Singapore residents. Flag for review: frequent traders may be treated as trading income by IRAS.

### Gaps
- I did not retrieve an IRAS primary page confirming no capital gains tax, or the tax exemption for foreign-sourced dividends received by individuals. Both are widely stated but need verification with IRAS or a tax professional, including the risk that IRAS treats an active trader as carrying on a trade.
- I did not confirm from the IRS that capital gains on US stocks are generally not subject to US tax for nonresident aliens who are not present in the US 183+ days. This is commonly stated but unverified here.
- The Irish UCITS estate-tax treatment rests on secondary sources; I found no IRS or Treasury statement. It needs professional review.
- The current Form 706-NA instructions and the statute (IRC §2102) were not retrieved.
- FX spreads are from affiliate-style blogs and conflict, especially for IBKR. Verify on each broker's fee page.
- I found no Singapore-specific data on how much retail investors lose to FX or spreads in aggregate.
- MAS/MoneySense investor education material was not retrieved.

## 4. Behavioural biases measurable from trades

### Takeaway
The best-documented costly behaviours are:
- **Overtrading.** The most active households lagged the market by about 6.5 pp/yr in 1990s US broker data.
- **The disposition effect.** Investors sell winners and hold losers, and the winners they sell go on to outperform the losers they keep.
- **Attention-driven buying.** Stocks most bought by Robinhood users earned about -4.7% abnormal returns over the next 20 days.
- **Lottery-stock preference.** Lottery-stock investors earn about 2-3% less per year.
- **Return-chasing and timing.** Morningstar measures a 1.2 pp/yr gap between fund returns and investor returns over 2016-2025.

All of these can be computed from a user's trade log.

### Cited Findings
- **Behaviour gap (Morningstar Mind the Gap US 2025).**
  - The average dollar in US mutual funds and ETFs earned 8.7%/yr over the 10 years to 31 Dec 2025, against the funds' 9.9% total return. The gap is about 1.2 pp/yr, roughly 12% of total return.
  - Investor return is computed as a dollar-weighted (IRR-type) return.
  - The least-volatile funds had a gap of -0.4 pp and the most volatile -2.1 pp.
  - ETFs had a wider gap than open-end funds.
  - Active vs passive was not the key driver.
  - Allocation funds such as target-date funds had the narrowest gaps.
  - — [Morningstar Mind the Gap 2025](https://www.morningstar.com/business/insights/research/mind-the-gap-2025); [Advisor Perspectives, Aug 2026](https://www.advisorperspectives.com/commentaries/2026/08/21/what-advisors-can-learn-from-the-investor-return-gap). Some excerpts mix 2024 and 2025 editions; the allocation-fund point was attributed to the period ending 2024.
- **Overtrading (Barber & Odean 2000, *JF*, "Trading is hazardous to your wealth").**
  - Sample: about 66,000-78,000 households at a US discount broker, 1991-1996/97.
  - The average household earned 16.4%/yr against the market's 17.9%, with about 75% annual turnover.
  - The 20% of households that traded most earned 11.4%/yr (arithmetic). Odean's page reports their geometric mean net return as 10.0%. They averaged over 250% annual turnover.
  - Gross performance barely differed between frequent and infrequent traders, so costs drove the gap. Liquidity, rebalancing and taxes cannot plausibly explain the turnover; the authors attribute it to overconfidence.
  - — [CXO Advisory summary](https://www.cxoadvisory.com/?p=191); [Odean paper page](https://faculty.haas.berkeley.edu/odean/papers/returns/Returns.html); [HedgeFundAlpha](https://hedgefundalpha.com/strategies/common-stock-investment-performance-individual-investors/); review in [Barber & Odean NBER w16022](https://www.nber.org/papers/w16022.pdf)
  - Sources gave slightly different figures; the 11.4% vs 10.0% difference looks like arithmetic vs geometric means.
  - A later critique (Bonaparte & Cooper) argues that how hazardous trading really is remains open. — [CXO Advisory](https://www.cxoadvisory.com/?p=191)
- **Disposition effect (Odean 1998, *JF* 53(5):1775-1798, 10,000 discount-broker accounts).**
  - Investors show a strong preference for realising winners over losers.
  - This is not justified by later performance: the winners sold continue to outperform the losers held.
  - For taxable investors it lowers after-tax returns.
  - Method: compare the Proportion of Gains Realised (PGR) with the Proportion of Losses Realised (PLR), computed on days the investor sells.
  - — [CFA Institute digest](https://rpc.cfainstitute.org/research/cfa-digest/1999/05/are-investors-reluctant-to-realize-their-losses-digest-summary); [Odean paper page](https://faculty.haas.berkeley.edu/odean/papers/disposition/disposition.html); [Evidence Investor](https://www.evidenceinvestor.com/?p=22941)
- **Attention-induced trading on Robinhood (Barber, Huang, Odean & Schwarz 2022, *JF* 77(6):3141-3190, DOI 10.1111/jofi.13183).**
  - Robinhood users trade on attention more than other retail investors.
  - Robinhood outages disproportionately reduce trading in high-attention stocks, which shows the app's features drive part of the effect.
  - Intense buying by Robinhood users predicts negative returns: the top stocks bought each day average -4.7% abnormal returns over 20 days.
  - — [RePEc](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:6:p:3141-3190); [WUSTL profile](https://profiles.wustl.edu/en/publications/attention-induced-trading-and-returns-evidence-from-robinhood-use/)
- **Lottery-stock preference (Kumar 2009, *JF* 64(4):1889-1933, "Who gambles in the stock market?").**
  - Lottery-type stocks are defined as low-priced (under $5), with high idiosyncratic volatility and high idiosyncratic skewness.
  - Investors who favour them typically earned 2-3% less per year. Underperformance is larger among low-income investors who heavily overweight these stocks.
  - Demand for them rises during economic downturns.
  - — [UT Austin news, 2009](https://news.utexas.edu/2009/02/26/investors-who-gamble-in-the-stock-market-have-same-characteristics-as-lottery-players-study-shows); [RePEc](https://econpapers.repec.org/RePEc:bla:jfinan:v:64:y:2009:i:4:p:1889-1933)
- **Gamified apps (UK FCA research, test app with over 9,000 participants).** Gamification and push notifications increased trading and risk-taking (details under Q5). — [Investment Executive](https://www.investmentexecutive.com/news/trading-games-drive-heavier-riskier-activity-fca/)

### Inferences
Each insight below can be computed from the user's trade log.
- **Personal behaviour gap.** Compare the user's money-weighted return (XIRR on actual cash flows) with the time-weighted return of their holdings, or with a buy-and-hold of their starting portfolio. The difference is their own "Mind the Gap" number. This is the most directly evidence-backed "edge" metric.
- **Turnover and cost-of-trading score.** Annual turnover = min(buys, sells) / average portfolio value. Compare against a benchmark band: the average 1990s household was about 75%/yr and the top quintile above 250%. Estimate spread and FX costs paid.
- **Counterfactual "if you hadn't traded".** Value the portfolio as held 12 months ago, unchanged, against the actual portfolio. This mirrors the gross-vs-net logic in Barber & Odean.
- **Disposition ratio.** On each sell day, count realised gains, realised losses, paper gains and paper losses.
  - PGR = realised gains / (realised gains + paper gains); PLR is defined the same way for losses.
  - PGR/PLR well above 1 indicates the disposition effect.
  - Also track how sold winners and held losers perform over the next 3-12 months.
- **Attention-buy flag.** Flag a buy when the stock appeared in the daily top movers, had extreme volume, or the user was alerted shortly before buying. The Robinhood evidence supports a gentle warning such as "stocks bought during attention spikes have historically underperformed over the next month".
- **Lottery-stock exposure.** Share of portfolio in stocks under $5, with top-decile idiosyncratic volatility or skewness, or meme stocks.
- **Return chasing.** Correlation between buys and trailing 1-3 month returns of the purchased stock.
- For a Singapore investor the "home bias" question is reversed: the user is concentrated in a foreign market (US) and in USD. Home-bias research is less directly relevant than concentration and currency exposure.

### Gaps
- Exact Odean (1998) figures could not be confirmed against the full text. From memory, unverified: PGR about 0.148 vs PLR about 0.098, and winners sold beat losers held by about 3.4 pp over the following year.
- Barber & Odean (2008, *RFS*), "All that glitters": individual investors are net buyers of attention-grabbing stocks (news, high volume, extreme one-day returns). This paper was not retrieved; the claim is from memory.
- Morningstar's "Mind the Gap" covers fund flows, not individual stock traders; I found no equivalent study for retail single-stock investors.
- Retail options trading (for example Bryzgalova, Pavlova & Sikorskaya 2023; de Silva, Smith & So on retail options losses) was not retrieved within budget. It is a gap to fill if the app supports options.
- Evidence on chasing past returns (fund flows following performance) and home bias was not retrieved this session.
- I found no studies specific to Singapore retail investors' trading behaviour.

## 5. Interventions and nudges: what helps, what backfires

### Takeaway
The best evidence concerns what backfires:
- **Frequent feedback** increases myopic loss aversion. In lab studies, people who see results less often invest more in the risky asset, though replication is mixed.
- **Push notifications and gamification** raise trading and risk-taking. In the FCA experiment, push notifications raised trading by 11% and the share of risky trades by 8%.
- **App design itself** (Robinhood features) drives attention trading that predicts losses.

For positive nudges (cooling-off periods, risk displays), I found little causal evidence within budget.

### Cited Findings
- **Myopic loss aversion (theory).** Benartzi & Thaler (1995) show the equity premium fits investors who evaluate portfolios about annually and weigh losses about twice as heavily as gains. This was a simulation, not an experiment. — [summary via Gneezy & Potters materials, UCSD](https://Rady.ucsd.edu/_files/faculty-research/uri-gneezy/evaluation-periods.pdf)
- **Myopic loss aversion (lab test).** Gneezy & Potters (1997, *QJE* 112(2):631-645) ran the first direct test. Subjects given less frequent feedback invested more in the risky asset, consistent with myopic loss aversion. Thaler, Tversky, Kahneman & Schwartz (1997) independently found similar results. — [RePEc](https://econpapers.repec.org/RePEc:oup:qjecon:v:112:y:1997:i:2:p:631-645.); [UCSD PDF](https://Rady.ucsd.edu/_files/faculty-research/uri-gneezy/evaluation-periods.pdf)
- **Mixed replications.** Bellemare et al. (2005) argue feedback frequency alone is not the full story. Fellner & Sutter find investment flexibility matters at least as much as feedback frequency. Beshears et al. (2017) find no evidence of myopic loss aversion in a field-like retirement-portfolio setting. — [Economics Letters 2005 PDF](https://www.fss.ulaval.ca/sites/fss.ulaval.ca/files/fss/economique/professeurs/economic-letters-2005.pdf); [NBER w16868](https://nber.org/system/files/working_papers/w16868/revisions/w16868.rev1.pdf)
- **Push notifications (FCA experiment).** In a regulator-built test trading app with over 9,000 participants, push notifications increased trading by 11% and the share of trades in risky investments by 8%. Gamification features also increased trading and risk. The FCA said more research is needed. — [Investment Executive](https://www.investmentexecutive.com/news/trading-games-drive-heavier-riskier-activity-fca/); [Investment News NZ](https://investmentnews.co.nz/investment-news/game-off-uk-regulator-finds-retail-trading-platform-tricks-are-traps)
- **Attention triggers (Arnold, Pelster & Subrahmanyam, UK CFD broker data, difference-in-differences).** Attention triggers such as push messages increase risk-taking, especially among male, younger and less experienced investors. — [Paderborn TAF working paper](https://en.wiwi.uni-paderborn.de/fileadmin-wiwi/cetar/TAF_Working_Paper_Series/TAF_WP_055_ArnoldPelsterSubrahmanyam2021_rev.pdf); [Cambridge JBS conference version](https://www.jbs.cam.ac.uk/wp-content/uploads/2020/08/2020-06-conference-paper-arnold-pelster-subrahmanyam.pdf)
- **Counterpoint (unpublished).** A University of Iowa dissertation finds Robinhood's 5%-move alerts raise trading by at least 25%, but argues retail investors appear to benefit from notifications and data visualisation. This is preliminary. — [U. Iowa dissertation](https://iro.uiowa.edu/esploro/outputs/doctoral/How-do-brokerages-digital-engagement-practices/9984362557402771)
- **App features cause attention trading.** Robinhood outages reduced trading in high-attention stocks disproportionately, so the app's features drive part of the attention-induced trading that predicts -4.7% 20-day abnormal returns. — [RePEc](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:6:p:3141-3190)
- **Survey (Traders Union, 1,350 investors; low quality, not causal).** 41% usually or sometimes open their app soon after a market notification. — [Traders Union](https://tradersunion.com/interesting-articles/trading-apps-and-overtrading-tu-research/)
- **Diversified products narrow the gap.** Allocation and target-date funds had the narrowest investor return gaps, which suggests automation and pre-commitment reduce harmful timing. — [Morningstar Mind the Gap 2025](https://www.morningstar.com/business/insights/research/mind-the-gap-2025)

### Inferences
Design implications for Nexus:
- Nexus already has daily movers, price alerts and a watchlist. The evidence (FCA, Arnold et al., Robinhood) suggests these features increase trading and risk-taking, and attention-driven buys underperform. Recommended defaults:
  - Alerts are opt-in, not on by default.
  - Thresholds are user-set.
  - Alerts link to the user's own written trade plan rather than a "Buy" button.
  - No streaks, confetti or other gamified rewards for trading.
- **Use the trade-plan feature as pre-commitment.** Before a trade on an alerted or top-mover stock, show the user's own plan: entry thesis, exit rule and max position size. This is a cooling-off nudge. It is evidence-informed (from the backfire evidence and the narrow gaps of pre-committed products), not directly tested.
- **Lower the salience of short-term P&L.** Make the default portfolio view longer-horizon (since purchase or 1 year) rather than daily change. Batch summaries weekly or monthly. Myopic loss aversion evidence supports this, but replication is mixed, so frame it as moderate evidence.
- **Show users their own costs and behaviour gap**: turnover, FX spend, disposition ratio, and the "if you hadn't traded" counterfactual. This makes the cost of overtrading concrete. I found no causal study of this specific intervention.

### Gaps
- I found no randomised evidence that cooling-off periods, trade-confirmation friction or risk displays improve retail investing outcomes. Candidate literature to check: FCA/ESMA behavioural studies on risk warnings, and SEC "digital engagement practices" materials from 2021-2023.
- The FCA report's primary document (title, date, URL on fca.org.uk) was not retrieved. Figures come from trade-press coverage.
- Looney & Hardin (2009) and other field evidence on checking frequency were not retrieved.
- I found no evidence on MAS rules about gamification or push notifications in Singapore.

## 6. Rebalancing evidence; dollar-cost averaging vs lump sum

### Takeaway
Vanguard finds no single optimal rebalancing rule. Annual or semi-annual monitoring with about 5-percentage-point drift thresholds balances risk control against cost, and its main benefit is risk control, not higher return. Lump-sum investing beat dollar-cost averaging about 68% of the time over 1-year horizons in Vanguard's 1976-2022 data. DCA mainly reduces regret and worst-case drawdown, so it is a behavioural tool rather than a return enhancer.

### Cited Findings
- **Vanguard (2010), "Best Practices for Portfolio Rebalancing" (US stocks and bonds, 1926-2009).**
  - No optimal frequency or threshold exists.
  - For most diversified stock/bond portfolios, annual or semi-annual monitoring with rebalancing at 5% thresholds likely gives a reasonable balance of risk control and cost.
  - — [Vanguard PDF (mirror)](https://indexacapital.com/bundles/unaiadvisor/docs/papers/2010-Vanguard-Best-practices-for-portfolio-rebalancing.pdf?v=241); [AAII](https://aaii.com/journal/article/best-practices-for-portfolio-rebalancing)
- **Vanguard follow-up (1926-2014 data).**
  - Annual monitoring with a 5% threshold gave 9.8% annualised volatility, the lowest of the strategies tested.
  - That rule had 1.6% annual turnover and 36 rebalancing events.
  - Some secondary sites call this "the most optimal", which overstates Vanguard's own "no optimal" conclusion.
  - — [Vanguard ISGPORE (mirror)](https://www.financieelonafhankelijkblog.nl/wp-content/uploads/2021/11/Vanguard-ISGPORE.pdf); [Vanguard Canada](https://www.vanguard.ca/en/investor/insights/when_and_how_to_rebalance)
- **Lump sum vs DCA (Vanguard, 1976-2022, $100,000, 1-year horizon).**
  - Lump sum outperformed DCA about 68% of the time.
  - Win rates were about 62-74% across the US, UK and Australia.
  - Lump sum produced roughly 1.2-2.2% more wealth on average depending on the asset mix, with a larger gap at higher equity allocations.
  - The advantage did not hold in the worst ~25% of periods, and lump sum had deeper drawdowns in bad markets.
  - An earlier Vanguard version dates from 2012.
  - — [SmartAsset](https://smartasset.com/investing/lump-sum-investing-research); [Motley Fool](https://www.fool.com/money/buying-stocks/articles/should-you-invest-your-money-all-at-once-or-over-time); [Prudent Plastic Surgeon](https://prudentplasticsurgeon.com/dollar-cost-averaging-lump-sum/) (secondary; Vanguard PDF not opened)
- **Morningstar.** Allocation funds, which rebalance automatically, had the narrowest investor return gaps. This is indirect evidence that automatic rebalancing helps behaviour. — [Morningstar Mind the Gap 2025](https://www.morningstar.com/business/insights/research/mind-the-gap-2025)

### Inferences
- **Drift alert.** For users who set target weights in Nexus (by asset, sector or "core ETF vs satellite stocks"), check monthly or quarterly. Alert only when a weight drifts more than 5 pp from target, or 25% relative for small sleeves.
  - This matches Vanguard's low-turnover rule.
  - It avoids encouraging frequent trading, which the overtrading evidence warns against.
- **Single-stock rebalancing.** For users of single stocks, a "trim when a position exceeds X% of portfolio" rule follows from the concentration evidence (Q1). It also counters the disposition effect, because selling is rule-based rather than gain/loss-based.
- **Singapore tax.** If there is no capital gains tax (verify), rebalancing has no Singapore tax cost. Costs are spreads, commissions and FX, so the app can be less tax-constrained than US robo-advisors. Wash-sale or tax-loss-harvesting logic is not needed for Singapore tax.
- **DCA framing.** Present DCA honestly: lump sum historically wins about two-thirds of the time, but DCA limits regret and worst-case outcomes. Regular automated investing from salary is a separate case and is not a timing decision.

### Gaps
- The original Vanguard lump-sum PDF (title and 2023 date) was not opened, and secondary sources disagree on details such as horizon and dates.
- I found no evidence on rebalancing for portfolios of individual stocks, as opposed to stock/bond mixes, or on rebalancing frequency for SGD-based investors who face FX costs.
- I found no randomised evidence that rebalancing reminders improve retail outcomes. The evidence is from simulations of the rule, not from tests of the nudge.
