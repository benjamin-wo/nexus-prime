# payer2 branch eval (head d8744cc)

Run 31 October 2026:

```
uv run python -m nexus.evals --model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks \
  --vision-model qwen/qwen3.8-flash --reasoning low \
  --case plan-pay --case mem-employer --case mem-changed-job --case voice-default-no-stock \
  --repeat 5 --out eval-results/payer2-branch
```

`--case` matches by prefix, so `plan-pay` selected four cases (`plan-pay-phrasing`, `-aircon`, `-rule`, `-payer`): 7 cases x 5 rounds = 35 runs.

| Case | Passed |
|---|---|
| plan-pay-phrasing | 5/5 |
| plan-pay-aircon | 5/5 |
| plan-pay-rule | 5/5 |
| plan-pay-payer | 5/5 |
| mem-employer | 5/5 |
| mem-changed-job | 5/5 |
| voice-default-no-stock | 5/5 |

**7.0/7 a round (min 7, max 7).** No failed rounds, so no failure reasons; no flaky or always-failing cases. Errors 0, model failures 0.

Median reply 2.2s (p90 2.9s); cost $0.0249 total ($0.00071 a case). Full report and JSON: `eval-results/payer2-branch/`.
