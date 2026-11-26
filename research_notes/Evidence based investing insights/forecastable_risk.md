# Forecastable risk quantities for individual stocks and portfolios: volatility, events, correlation/beta, tail risk, and path probabilities

Scope note: what *is* reliably forecastable (second moments, i.e. risk) versus what is not (direction/expected return). Product context: Nexus, a Singapore retail investing app (mostly US stocks) that already estimates "chance of reaching target before stop" by replaying historical price paths. Research done 2026-11-18. Most references are peer-reviewed classics (1971-2019); vendor/practitioner sources are flagged as such. Several primary papers were seen only through abstracts/replications (noted where relevant).

---

## 1. Volatility forecasting (GARCH, HAR-RV, realized vol, EWMA, implied vol): which wins at 1-day to 3-month horizons, and how accurate?

### Takeaway
Volatility is the most forecastable quantity in finance: simple models (GARCH(1,1), EWMA, HAR-RV) track it well, and the low "R²" of the early literature was mostly because daily squared returns are a noisy yardstick. Sophisticated models beat GARCH(1,1) only modestly and mainly when you add asymmetry (leverage), intraday realized-volatility data, or option-implied volatility. For single stocks with liquid options, implied vol is usually the best single input, and combining forecasts beats any one of them.

### Cited Findings
**Is volatility forecastable at all?**
- Andersen & Bollerslev (1998, *International Economic Review* 39(4):885-905), "Answering the Skeptics: Yes, Standard Volatility Models Do Provide Accurate Forecasts". Critics had noted that GARCH explains only a small share of the variation in ex-post *squared daily returns*. The authors show this happens because squared returns are a very noisy proxy for true volatility. When forecasts are judged against realized variance (the sum of squared intraday returns), GARCH-type forecasts are "strikingly accurate" — [EconPapers abstract](https://econpapers.repec.org/RePEc:ier:iecrev:v:39:y:1998:i:4:p:885-905); [PDF copy](https://faculty.washington.edu/ezivot/econ589//////AndersenBollerslevIER1998.pdf); [NBER WP 6023](https://www.nber.org/papers/w6023). (I did not extract the exact R² figures from the full text.)
- Brownlees, Engle & Kelly (2011/2012, *Journal of Risk* 14(2):3-22), "A Practical Guide to Volatility Forecasting through Calm and Storm":
  - Compares ARCH-family models on equity indices and FX over 1990-2008.
  - Model rankings are insensitive to the forecast horizon.
  - 2008 volatility was well approximated by one-day-ahead forecasts and "should have been within risk managers' 1% confidence intervals up to one month ahead".
  - It also gives best practices on estimation window length, innovation distribution and how often to re-estimate.
  - It excludes realized-vol and stochastic-vol models.
  - Sources: [Risk.net](https://www.risk.net/journal-risk/2161026/practical-guide-volatility-forecasting-through-calm-and-storm); [online appendix](https://ctbrownlees.github.io/docs/volfor-appendix.pdf); [PDF](https://c.mql5.com/forextsd/forum/222/A%20Practical%20Guide%20to%20Volatility%20Forecasting%20through%20Calm%20and%20Storm.pdf).

**GARCH(1,1) as the benchmark**
- Hansen & Lunde (2005, *Journal of Applied Econometrics* 20(7):873-889) compared 330 ARCH-type models out-of-sample, using the Superior Predictive Ability (SPA) test and the Reality Check for data snooping. Results by asset:
  - DM/$ exchange rate: no evidence that GARCH(1,1) is beaten.
  - IBM stock (evaluated against realized variance): GARCH(1,1) is clearly beaten by models with a leverage effect (e.g. GJR/EGARCH-type asymmetry).
  - Sources: [EconPapers](https://econpapers.repec.org/RePEc:jae:japmet:v:20:y:2005:i:7:p:873-889); [replication vignette](https://ftp.fau.de/cran/web/packages/forecastdom/vignettes/hl2005-spa-garch.html).
- The ranking depends on the volatility proxy. In a replication, coarse 5-minute RV proxies give SPA p-values of about 0.07-0.08, so GARCH(1,1) is not rejected. Finer proxies do reject it in favour of competitors — [forecastdom vignette](https://ftp.fau.de/cran/web/packages/forecastdom/vignettes/hl2005-spa-garch.html).

**HAR-RV**
- Corsi (2009, *Journal of Financial Econometrics* 7(2):174-196) introduced HAR-RV. Tomorrow's realized volatility is regressed on daily, weekly (5-day) and monthly (22-day) average RV. This simple AR-type model approximates long memory, and the author reports "remarkably good forecasting performance" — [SSRN](https://papers.ssrn.com/abstract=1365738); [PDF](https://statmath.wu.ac.at/~hauser/LVs/FinEtricsQF/References/Corsi2009JFinEtrics_LMmodelRealizedVola.pdf).
- A large study of about 400 realized measures across 31 assets used HAR at horizons of 1-50 days. It found it is "difficult to significantly beat 5-minute RV" as the input — summary via [search result (Oxford ORA)](https://ora.ox.ac.uk/objects/uuid:4a291238-52f0-44d2-9002-9047482df6e8/files/sws859g09z). This is likely Liu, Patton & Sheppard (2015, *J. Econometrics*), not verified in full text.
- Extensions such as jumps (HAR-RV-CJ), semivariance (Patton & Sheppard) and measurement-error corrections (HARK; Buccheri & Corsi 2019) give incremental gains over plain HAR — [Buccheri & Corsi WP](https://openaccess.city.ac.uk/23156/1/BuccheriCorsi_HarkTheShark_wp2019.pdf); [Helsinki thesis](https://helda.helsinki.fi/server/api/core/bitstreams/d899c4e2-9861-48ca-b32b-c6b24f01df35/content).

**EWMA (RiskMetrics)**
- RiskMetrics (J.P. Morgan 1996 Technical Document) uses λ = 0.94 for daily data and λ = 0.97 for monthly data. The effective memory is about 1/(1−λ) ≈ 17 days, with a half-life of about 11 trading days. Sources: [MSCI listing of the 1996 Technical Document](https://www.msci.com/research-and-insights/paper/1996-riskmetrics-technical-document); values reported by secondary sources ([MetricGate](https://metricgate.com/docs/ewma-volatility-riskmetrics/)). Primary text not verified.
- λ = 0.97 was found "far from optimal" for monthly S&P 500 volatility over 1957-2013 — [UNE working paper](https://www.une.edu.au/__data/assets/pdf_file/0009/76464/unebsop14-1.pdf).

**Implied volatility**
- Single stocks:
  - Implied vol forecasts beat historical/GARCH forecasts at short and medium horizons for FTSE-100 stocks (Garvey; caveat: constructed IVs) — [Stirling repository](https://www.stir.ac.uk/research/hub/file/571715).
  - Implied forecasts generally outperform historical ones out-of-sample (Fradkin, Duke 2008, undergraduate thesis) — [Duke](https://sites.duke.edu/djepapers/files/2016/11/Fradkin.pdf).
- Index-level evidence is mixed:
  - Implied vol alone sometimes underperforms, and a combination of asymmetric GARCH, implied vol and realized vol is preferred (Kambouroudis, McMillan & Tsakou) — [record](https://rc.cplp.org/Record/rcaap_5f3f88df438f8001b39006497b0b60ae/Description).
  - All models degrade sharply in 2008, and no model is best across the board — [CORE](https://core.ac.uk/works/8594254).
- Implied vol is a biased-upward forecast: it contains a variance risk premium, meaning the gap between risk-neutral and statistical expected variance. That premium is "generally rather large and highly statistically significant", and more than half of it is attributed to disaster risk — [CREATES RP 2009-26](https://repec.econ.au.dk/repec/creates/rp/09/rp09_26.pdf).

**How to score forecasts**
- Patton (2011, *J. Econometrics* 160:246-256): of nine common loss functions, only MSE and QLIKE give rankings that stay correct when the volatility proxy is noisy. QLIKE has more power and is less dominated by extreme days. In his IBM application, QLIKE found significant differences between models where MSE did not — [EconPapers](https://econpapers.repec.org/RePEc:eee:econom:v:160:y:2011:i:1:p:246-256); [summary](https://www.bohrium.com/paper-details/volatility-forecast-comparison-using-imperfect-volatility-proxies/811802185691037697-10344); [Oxford ORA](https://ora.ox.ac.uk/objects/uuid:474e796d-5656-4e6b-94d3-b10125785fc5/files/mba0ba07178c0b21e3528d52e99430bd0).

### Inferences
- **Recommended stack for Nexus** (daily OHLC data, no intraday ticks):
  - (a) An EWMA or GJR-GARCH(1,1) with Student-t errors on daily returns as the always-available baseline.
  - (b) If intraday bars are affordable, a HAR-RV on 5-minute RV. Without them, a range-based proxy such as Parkinson or Garman-Klass from OHLC (my suggestion; not sourced here) can approximate RV inside HAR.
  - (c) Where listed options exist, at-the-money implied vol for the matching tenor, scaled down for the variance risk premium (e.g. regress realized on implied).
  - (d) A simple average or regression combination of the three.
  - The literature consistently shows combinations are robust.
- **Horizons:**
  - 1-day to about 1-month vol forecasts are genuinely informative, because volatility clustering is strong.
  - At about 3 months, forecasts revert toward the long-run mean and implied vol dominates where available.
  - Rankings are horizon-insensitive (Brownlees et al.), so the same model can serve several horizons via GARCH multi-step mean reversion or HAR.
- **Validation:** Nexus should evaluate its own forecasts with QLIKE against a realized proxy on a rolling out-of-sample basis. It should not use MAE against |returns|, which is non-robust.
- **Library note** (not fetched in this session): the Python `arch` package (Kevin Sheppard) implements GARCH/GJR/EGARCH, HARX mean models, Student-t/skew-t errors, multi-step and simulation-based forecasts, and bootstraps (including the stationary bootstrap) — https://arch.readthedocs.io/.

### Gaps
- No concrete percentage error numbers were retrieved, such as "QLIKE improvement of HAR over GARCH = X% for US single stocks". The Andersen-Bollerslev R² values and the Liu-Patton-Sheppard magnitudes need full-text checking.
- No 2020-2026 study was found specifically on single-stock IV versus HAR accuracy for US large caps. Recent ML vol-forecasting papers were not reviewed.

---

## 2. Event risk: earnings-announcement moves (option implied move vs. historical), ex-dividend, index events

### Takeaway
Earnings are the largest predictable volatility event for a single stock. Option markets price the announcement-day move as a separable jump, and that price is informative about the realized move. It is usually somewhat rich, with realized moves on average about 85% of implied (vendor data). Overpricing is less reliable for small-implied-move megacaps and varies by season. Historical earnings moves for the same stock are a usable fallback when no options exist.

### Cited Findings
- Dubinsky, Johannes, Kaeck & Seeger (2019, *Review of Financial Studies* 32(2):646-687), "Option Pricing of Earnings Announcement Risks":
  - Separates earnings-day uncertainty from ordinary daily volatility using option prices.
  - Anticipated earnings uncertainty is "quantitatively large, varies across time, and is informative about future return volatility".
  - Implied vol rises before announcements and collapses after, and the implied-vol term structure is typically downward-sloping before the event.
  - Sources: [IDEAS](https://ideas.repec.org/a/oup/rfinst/v32y2019i2p646-687..html); [Sussex repository](https://sussex.figshare.com/articles/journal_contribution/Option_pricing_of_earnings_announcement_risks/23454023); [NYU conference slides](https://www.stern.nyu.edu/sites/default/files/assets/documents/NYU%20conference%20Johannes%20final.pdf).
- ORATS (vendor): the actual-to-implied earnings move ratio has hovered around 85%, meaning straddles are usually priced richly — [ORATS](https://orats.com/blog/marketwatch-talks-to-orats-about-this-earnings-season). ORATS also says actual moves in the 2026 season have been "consistently larger" than implied, so the overpricing is not stable — [ORATS 2026](https://orats.com/blog/earnings-straddles-strong-season-2026).
- IVolatility (vendor) backtest of about 9,600 S&P 500 earnings events: the synthetic straddle was overpriced 59.5% of the time, with a median edge of +0.84 percentage points — [IVolatility](https://www.ivolatility.com/news/3147).
- FlashAlpha (vendor; small sample of 70 events):
  - The largest implied moves were overpriced 93% of the time.
  - Small implied moves on megacaps were breached repeatedly (seller win rate 0.43 in the smallest quintile).
  - Source: [FlashAlpha](https://flashalpha.com/articles/earnings-vrp-harvesting-systematic-backtest-short-straddles).
- Single-name dispersion: Netflix's average earnings move was roughly double its implied move in one period, while Tesla's was overpriced — [Market Rebellion](https://marketrebellion.com/news/how-to-trade-earnings-with-straddles-featuring-netflix-and-tesla). Home Depot's straddle historically overpriced the move by about 0.9% — [IBKR Campus](https://www.interactivebrokers.com/campus/traders-insight/securities/options/home-depots-earnings-a-look-at-historical-straddle-performance/).
- Methodology varies between vendors. ORATS strips residual non-event time value out of the straddle, while others use the raw at-the-money straddle. The common shortcut "implied move ≈ ATM straddle price / spot" therefore overstates the event-only move by the ordinary vol contained in the straddle — [OptionStrat](https://optionstrat.com/blog/expected-moves-vol-crush); [ORATS](https://orats.com/blog/marketwatch-talks-to-orats-about-this-earnings-season).

### Inferences
- **For Nexus trade plans:**
  - If an earnings date falls inside the plan horizon, the target/stop probability must include a jump at that date.
  - A GBM or GARCH model on ordinary days will understate the chance that the stop or target is gapped through.
  - Options to implement:
    - Add one jump draw with standard deviation equal to the implied event move. The event variance can be backed out from the implied vol term structure as σ²_event ≈ (σ²_post-event-expiry × T₂ − σ²_pre-event × T₁)-type differences, following Dubinsky et al.'s logic.
    - When no options are available, use the stock's own past earnings-day absolute moves. With about 4 per year, 8-20 observations is a small sample, so shrink toward a sector or market-cap average.
  - Gap risk also means stops fill below the stop price, which should be shown.
- **Displaying the implied move to users:** this is reasonable and robust, but label it as "the options market expects ±X%". Note that realized moves have averaged below implied, but not reliably for any single stock or season.
- **Ex-dividend and index events:** no sources were retrieved.
  - Ex-dividend drops are mechanical and known in advance (price falls by about the dividend). They should be modelled as a deterministic shift, not risk, so that stops near the price are not falsely triggered in historical replays using unadjusted prices.
  - Index inclusion/rebalance events are mostly a liquidity/volume issue for large caps.
  - (Inference; unsourced.)

### Gaps
- No peer-reviewed number was found for the average ratio of realized to implied earnings move across the US cross-section. Only vendor statistics are available.
- No sourced evidence was retrieved on ex-dividend price-drop ratios (e.g. Elton-Gruber 1970) or index-inclusion effects (Shleifer 1986; the S&P 500 inclusion effect shrinking over time).
- No source was found on how the accuracy of historical-earnings-move forecasts compares with implied-move forecasts.

---

## 3. Correlation and beta forecasting (DCC-GARCH, Ledoit-Wolf shrinkage, Blume/Vasicek beta shrinkage, crisis correlations)

### Takeaway
Raw historical betas and sample covariance matrices are noisy. Shrinkage is a cheap and reliable improvement:
- Blume/Vasicek shrinkage of beta toward 1 or toward the cross-sectional mean.
- Ledoit-Wolf shrinkage of the covariance matrix.

Correlations are time-varying and asymmetric: they rise in bear markets, which is exactly when diversification is needed. Displayed portfolio risk should therefore use stressed or conditional correlations alongside the averages.

### Cited Findings
- **Blume (1971, 1975):** betas regress toward the mean (about 1) over time, even for well-diversified extreme-beta portfolios. Blume attributes this mainly to "real non-stationarities in the underlying values of beta" rather than measurement error alone — [RBA RDP 9802](https://www.rba.gov.au/publications/rdp/1998/1998-02/is-systematic-risk-convergence-a-statistical-artefact.html).
- The widely used "Bloomberg/Blume" adjusted beta is 0.67×raw + 0.33×1 — [IESE note](https://www.iese.edu/research/pdfs/DI-0825-E.pdf); [CFI](https://corporatefinanceinstitute.com/resources/valuation/adjusted-beta/). These exact weights could not be verified against Blume's paper; treat them as a practitioner convention.
- **Vasicek (1973):** a Bayesian weighted average of the historical beta and the cross-sectional mean beta, weighted by the precision of each. Noisier betas are shrunk more — [Spoudai paper](https://spoudai.unipi.gr/index.php/spoudai/article/download/945/1024).
- Empirical comparison: Blume and Vasicek adjustments both beat unadjusted betas on mean squared forecast error, with very little difference between them. Some studies find Vasicek slightly better — [Spoudai](https://spoudai.unipi.gr/index.php/spoudai/article/download/945/1024); [UIUC working paper](https://www.ideals.illinois.edu/items/29044/bitstreams/97223/data.pdf).
- **Ledoit & Wolf (2004, *J. Multivariate Analysis*), "A Well-Conditioned Estimator for Large-Dimensional Covariance Matrices":**
  - A convex combination of the sample covariance and a scaled identity target, with a closed-form optimal shrinkage intensity clipped to [0,1].
  - It stays well-conditioned when the number of assets approaches the number of observations.
  - Implemented in scikit-learn — [sklearn docs](https://scikit-learn.org/1.4/modules/generated/sklearn.covariance.ledoit_wolf_shrinkage.html); [explanatory note](https://reasonabledeviations.com/notes/papers/ledoit_wolf_covariance).
- **Longin & Solnik (2001, *Journal of Finance* 56(2):649-676):**
  - Uses extreme value theory on monthly returns of the five largest equity markets (1959-1996).
  - Correlation increases in bear markets but not in bull markets.
  - It is linked to market trend, not to volatility per se.
  - Multivariate normality is rejected in the negative tail only.
  - Sources: [EconPapers](https://econpapers.repec.org/RePEc:bla:jfinan:v:56:y:2001:i:2:p:649-676); [ESSEC](https://faculty.essec.edu/en/research/extreme-correlation-of-international-equity-markets).

### Inferences
- **Portfolio vol for Nexus:** σ_p from per-stock vol forecasts (section 1) combined with a Ledoit-Wolf-shrunk correlation matrix estimated on about 1-2 years of daily returns, or an EWMA covariance (RiskMetrics λ=0.94).
- DCC-GARCH (Engle 2002) is the academic standard for time-varying correlation but is heavier to fit. For a small team, EWMA correlation plus shrinkage is a defensible approximation. (DCC source not retrieved in this session.)
- **Beta:** compute about 2-5 years of weekly or 1-2 years of daily betas versus the S&P 500. Apply Vasicek shrinkage toward the sector mean, or the 0.67/0.33 rule. Show beta as a range, not a point.
- **Diversification:** show a "stress" view that sets correlations to elevated crisis levels. In the spirit of Longin-Solnik, users should be told that diversification benefits shrink in sell-offs.
- **SGD investors:** USD/SGD FX adds its own volatility and correlation to US equities. This is forecastable with the same tools and should be included in SGD-denominated portfolio risk (inference).

### Gaps
- Engle (2002) DCC and the Ang & Chen (2002) asymmetric correlation papers were not retrieved.
- No quantitative out-of-sample accuracy numbers were found for Ledoit-Wolf versus sample covariance on US stock portfolios (Ledoit-Wolf 2003/2004 report tracking-error/minimum-variance improvements, not verified here).
- No numbers were found for beta forecast R² (e.g. how much of next-period beta variation the shrunk beta explains).

---

## 4. Drawdown and tail risk: VaR/ES estimation and backtesting, maximum drawdown distributions, fat tails, volatility clustering

### Takeaway
Conditional (GARCH/EWMA-scaled) VaR and Expected Shortfall with fat-tailed innovations are the robust standard. Statistical backtests (Kupiec, Christoffersen) have low power at a 1-year sample, so a single stock's 99% VaR cannot be meaningfully validated on 250 days. Maximum-drawdown distributions have closed-form or series results under Brownian motion and are useful as rough "what to expect" ranges. They understate real drawdowns because of fat tails and volatility clustering.

### Cited Findings
- **Kupiec (1995) POF test** checks only the exception frequency, not timing. **Christoffersen (1998) conditional coverage** = Kupiec LR + independence LR, distributed χ²(2), and detects clustered exceptions — [MetricGate Christoffersen](https://metricgate.com/docs/var-backtesting-christoffersen/); [MetricGate Kupiec](https://metricgate.com/docs/var-backtesting-kupiec/) (vendor documentation).
- Power is low in small samples:
  - At 99% VaR over 250 days, only about 2.5 exceptions are expected.
  - An ECB conference paper co-authored by Christoffersen reports 1%-VaR test power at n=250 of roughly 0.13-0.33 across tests, becoming "reasonable" only from about 500 observations — [ECB/Christoffersen](https://www.ecb.europa.eu/pub/conferences/shared/pdf/jcbrconf4/Paper_Christoffersen.pdf).
  - "Generally these tests have low power" in 250-500 observation samples — [arXiv 2205.02123](https://arxiv.org/pdf/2205.02123).
  - The ECB table's column labelling was not verified test by test.
- Brownlees, Engle & Kelly: well-specified GARCH-type models produced forecasts that would have kept 2008 inside 1% confidence bands at horizons up to 1 month. Conditional models adapt quickly; unconditional historical-window VaR does not — [Risk.net](https://www.risk.net/journal-risk/2161026/practical-guide-volatility-forecasting-through-calm-and-storm).
- Longin & Solnik: the negative tail of multi-market returns rejects normality — [EconPapers](https://econpapers.repec.org/RePEc:bla:jfinan:v:56:y:2001:i:2:p:649-676).
- The variance risk premium is largely attributed to disaster (jump) risk, implying tails fatter than a diffusion model gives — [CREATES](https://repec.econ.au.dk/repec/creates/rp/09/rp09_26.pdf).
- **Maximum drawdown:** Magdon-Ismail, Atiya, Pratap & Abu-Mostafa (2004, *J. Applied Probability*), "On the maximum drawdown of a Brownian motion":
  - Gives an infinite-series distribution for the maximum drawdown of Brownian motion with drift.
  - Gives an analytic expected value for zero drift and series expressions otherwise.
  - Implemented in R `fBasics::maxdd` (density, CDF, random generation, expectation; the drift-dependent density is not implemented).
  - Sources: [Cambridge](https://www.cambridge.org/core/journals/journal-of-applied-probability/article/on-the-maximum-drawdown-of-a-brownian-motion/F9E3B8A454B020DDEBF0AC3390EF7807); [fBasics docs](https://rdrr.io/cran/fBasics/man/stats-maxdd.html).
- At long horizons, suitably centred and scaled maximum drawdown converges to a Gumbel law (Bermin & Holm 2025, Lund working paper) — [Lund WP25:9](https://lup.lub.lu.se/search/files/232813145/WP25_9.pdf).

### Inferences
- **What to show:** "In a typical/bad month this holding could fall X%/Y%", from a filtered historical simulation (FHS) or GARCH-t 95% VaR and ES, at 1-day, 1-week and 1-month horizons. Use 95% rather than 99% for display, because tail exceedances at 95% are frequent enough to backtest on 1-2 years of data.
- **Self-validation:** run Kupiec and Christoffersen tests pooled across all users' holdings or many tickers, not per ticker, to gain power. Pooling across cross-correlated stocks overstates the effective sample size, so cluster by date.
- **Drawdown:** compute the expected and 90th-percentile maximum drawdown over the plan horizon from Monte Carlo paths of the chosen vol model, not from the Brownian-motion closed form. The closed form is a lower-bound sanity check because it ignores fat tails and clustering.

### Gaps
- Original Kupiec (1995) and Christoffersen (1998) papers, Jorion's *Value at Risk* and McNeil-Frey-Embrechts' *Quantitative Risk Management* were not retrieved directly. Expected Shortfall backtesting (Acerbi-Szekely 2014; Basel FRTB's move to 97.5% ES) is not sourced here.
- No source was found giving the empirical tail index of US single-stock daily returns (the commonly cited tail index is about 3-4; not verified here).

---

## 5. Probability of touching a level before another (target before stop): closed form vs. bootstrap/historical replay vs. GARCH simulation vs. option-implied; biases; calibration and validation

### Takeaway
Under driftless geometry the answer is dominated by the distances to target and stop, not by the model:
- If the price is a martingale (zero expected price drift), P(target before stop) = (S₀ − Stop)/(Target − Stop) by optional stopping.
- The main thing any model adds is an assumed drift, plus (with a time limit) volatility and gap/jump risk.

Historical replays of a single stock mainly import that stock's past drift, which is not forecastable (a winner's history makes targets look easy). Volatility clustering, earnings gaps, discrete (daily-close) monitoring and overlapping samples all bias the estimates. A robust design uses near-zero or conservative drift, a forecast-vol-scaled simulation (GARCH or filtered bootstrap), explicit event jumps, and calibration checks on out-of-sample outcomes.

### Cited Findings
- **Touch vs. finish probabilities:** under Brownian-motion assumptions, the probability of touching an out-of-the-money level before expiry is roughly 2× the probability of finishing beyond it. This follows from the reflection principle and holds only approximately in real markets — [Options Analysis Suite docs](https://www.optionsanalysissuite.com/documentation/probability-of-touch-vs-probability-itm) (vendor).
- **Discrete monitoring correction:** Broadie, Glasserman & Kou (1997, *Mathematical Finance* 7(4):325-349). A barrier checked only at discrete times (e.g. daily closes) can be priced with continuous-barrier formulas by shifting the barrier away from the spot by a factor of exp(β σ √Δt), with β = −ζ(1/2)/√(2π) ≈ 0.5826. Howison & Steinberg (2005) show the correction applies very widely, with O(1/m) error — [IDEAS](https://ideas.repec.org/a/bla/mathfi/v7y1997i4p325-349.html); [Howison paper](https://people.maths.ox.ac.uk/howison/papers/discbarrier.pdf).
- **Risk-neutral vs. real-world:**
  - Option-implied probabilities are risk-neutral. Investors pay a premium for payoffs in bad states, which inflates risk-neutral probabilities of down moves relative to real-world ones — [Options Analysis Suite](https://www.optionsanalysissuite.com/documentation/probability) (vendor).
  - The Bank of England has published methods to convert risk-neutral densities to real-world densities — [BoE WP 2012](https://www.bankofengland.co.uk/-/media/boe/files/working-paper/2012/estimating-probability-distributions-of-future-asset-prices-emperical-transformations.pdf).
  - The variance risk premium is large and significant, so option-implied vol overstates expected realized vol on average — [CREATES](https://repec.econ.au.dk/repec/creates/rp/09/rp09_26.pdf).
- **Block bootstrap for dependent data:**
  - Politis & Romano (1994) stationary bootstrap. Politis & White (2004) give automatic optimal block-length selection, corrected by Patton, Politis & White (2009, *Econometric Reviews* 28(4):372-375).
  - Implemented as `np::b.star` in R. The Python `arch` package has `optimal_block_length` (not verified in this session).
  - Sources: [Patton-Politis-White 2009 PDF](https://public.econ.duke.edu/~ap172/Patton_Politis_White_2009.pdf); [b.star docs](https://search.r-project.org/CRAN/refmans/np/html/b.star.html).
- Rankings of volatility models do not depend on horizon, and well-specified GARCH forecasts adapt quickly to crises — [Brownlees, Engle & Kelly](https://www.risk.net/journal-risk/2161026/practical-guide-volatility-forecasting-through-calm-and-storm). This supports GARCH-simulated paths over unconditional replay.

### Inferences
These are derivations and design recommendations, not sourced empirical findings.

**Closed form (no time limit)**
- Let X = ln(S/S₀) follow Brownian motion with drift ν = μ − σ²/2. Let a = ln(Target/S₀) and b = −ln(Stop/S₀). Then:
  P(target first) = (e^{kb} − 1)/(e^{kb} − e^{−ka}), with k = 2ν/σ².
- With ν → 0 this reduces to b/(a+b).
- With μ = 0 (a martingale price), it reduces exactly to (S₀−Stop)/(Target−Stop).

**Worked example (my computation): target +10%, stop −5%**

| Annual drift μ | σ = 30% | σ = 60% |
|---|---|---|
| 0% | 33.3% | 33.3% |
| 10% | 37.0% | 34.3% |
| 30% | 44.7% | 36.1% |
| 60% | 56.1% | 38.9% |

- An assumed drift of 60% (typical of a historical replay on a recent mega-winner) moves the answer from 33% to 56%.
- Drift is not reliably forecastable, so this is pure model risk. Nexus should default to a modest drift, e.g. 0 to a market-like 6-8% per year, and show sensitivity rather than inherit each stock's own past drift.

**With a time limit T (e.g. plan expires in 3 months)**
- The probability splits into target-first, stop-first and neither.
- Volatility now matters: lower vol means more "neither".
- Double-barrier closed forms exist as infinite series, but Monte Carlo is simpler and handles GARCH and jumps.

**Comparing approaches**

| Approach | Strengths | Weaknesses |
|---|---|---|
| (a) GBM closed form | Transparent | Constant vol, no fat tails or gaps, so it underestimates gap-through-stop risk |
| (b) Plain historical replay (every past start date of the same stock) | Simple, uses real paths | Imports past drift; overlapping start dates are highly dependent, so 1,000 overlapping windows from 4 years hold far fewer independent observations and confidence intervals are too narrow; ignores today's vol regime; survivorship (only stocks that still exist) |
| (c) Block or stationary bootstrap of de-meaned, vol-standardised residuals, re-scaled by today's GARCH/EWMA vol forecast (filtered historical simulation) | Keeps fat tails and short-range dependence while using the current regime and a chosen drift | Most complex of the four |
| (d) Option-implied (risk-neutral) touch probability | Uses the market's current vol and event pricing (earnings) | Biased toward larger down-moves and higher vol than real-world because of the variance and jump risk premia; best used as a vol/event input, not as the probability itself |

- Recommended default: (c), with (d) as an input.

**Daily-close vs. intraday monitoring**
- If replay uses daily closes but stops trigger intraday, touch probabilities are understated.
- Apply the Broadie-Glasserman-Kou shift (barrier moved toward the spot by e^{−0.5826σ√Δt} when converting a continuous-monitoring answer to a daily-close one, and vice versa), or simulate with daily high/low.
- Gaps through the stop mean the realized loss is larger than the stop distance. Report the expected exit price, not just the probability.

**Validation and calibration**
- Log every probability Nexus shows, together with the realized outcome when the plan resolves.
- Measure the Brier score and log-loss, plus a reliability diagram (bins of predicted probability vs. observed frequency).
- Pool across users and tickers but cluster by time, since outcomes in the same week are correlated.
- Before launch, run the same evaluation as a pseudo-out-of-sample backtest:
  - Random tickers (including delisted ones, to avoid survivorship bias).
  - Random historical dates.
  - Model fitted only on data before each date.
- If systematically miscalibrated, apply isotonic or Platt recalibration.

**Small samples**
- With fewer than about 2-3 years of history, or recent IPOs, fall back to sector or market-wide standardized residuals.
- Show the probability with an interval, e.g. a bootstrap over parameter uncertainty or a ±drift sensitivity band.

### Gaps
- No published empirical calibration study was found of retail "probability of target before stop" tools, or of historical-replay versus GARCH-simulation first-passage accuracy on equities.
- The double-barrier first-exit-time series formula was not retrieved from a primary source.
- No source was found that quantifies the effective-sample-size reduction from overlapping windows for barrier events (a Hansen-Hodrick/Newey-West-type adjustment is the standard approach; not sourced here).

---

## 6. What horizons and quantities are robust enough to show users with confidence intervals?

### Takeaway
Show:
- Volatility and expected range at 1 day to about 1 month.
- The option-implied earnings move.
- Beta (shrunk) and portfolio volatility, plus stressed correlation.
- 95% VaR/ES ranges.
- Target-before-stop probabilities only as model-dependent estimates with drift sensitivity and a calibration track record.

Do not present directional or expected-return forecasts with the same confidence.

### Cited Findings
- Volatility forecasts are accurate when judged against a proper realized measure. Andersen & Bollerslev (1998) — [EconPapers](https://econpapers.repec.org/RePEc:ier:iecrev:v:39:y:1998:i:4:p:885-905). Brownlees et al.: 2008 stayed within 1% bands up to 1 month ahead — [Risk.net](https://www.risk.net/journal-risk/2161026/practical-guide-volatility-forecasting-through-calm-and-storm).
- Earnings uncertainty priced in options is informative about future volatility — [Dubinsky et al. 2019](https://ideas.repec.org/a/oup/rfinst/v32y2019i2p646-687..html).
- Shrunk betas beat raw betas out-of-sample — [Spoudai](https://spoudai.unipi.gr/index.php/spoudai/article/download/945/1024).
- Correlations jump in bear markets — [Longin & Solnik 2001](https://econpapers.repec.org/RePEc:bla:jfinan:v:56:y:2001:i:2:p:649-676).
- VaR backtests need 500+ observations for reasonable power — [ECB/Christoffersen](https://www.ecb.europa.eu/pub/conferences/shared/pdf/jcbrconf4/Paper_Christoffersen.pdf).
- Forecast accuracy collapses for all models in crisis onsets (2008 S&P study) — [CORE](https://core.ac.uk/works/8594254).

### Inferences
Suggested robustness tiers for Nexus:

| Tier | Quantities | Display guidance |
|---|---|---|
| High confidence | 1-day/1-week/1-month vol and "typical range" (±1σ band: about 68% of outcomes if roughly normal, fewer in practice because of fat tails, so quantile bands from the simulation are better); options-implied earnings move; portfolio volatility; beta (shrunk) | Show with ranges |
| Medium confidence | 95% 1-day/1-month VaR/ES; expected max drawdown over the horizon; correlation/diversification metrics | Show with a "can be much worse in crises" caveat and a stress scenario |
| Low confidence / model-dependent | Target-before-stop probability (show a drift-sensitivity range, e.g. "33-40% depending on assumed trend", and Nexus's own historical calibration stats); 3-month+ vol (mostly mean reversion, implied vol best) | Show as estimates only |
| Not robust | Direction/expected return of individual stocks, "will it hit the target" framed as a prediction of direction, 99%+ tail quantiles for single stocks | Do not show as forecasts |

- **Confidence intervals:** for vol, use parameter-uncertainty bootstraps or the dispersion of model forecasts (GARCH vs. HAR vs. implied). For probabilities, use binomial intervals on the effective (non-overlapping) sample size plus the drift band.

### Gaps
- No user-research or regulatory guidance (e.g. MAS in Singapore) on displaying probabilistic forecasts to retail investors was researched here; this is out of scope for this strand.
- No sourced benchmark was found for the share of realized outcomes that fall inside model 68%/95% bands for US single stocks.
