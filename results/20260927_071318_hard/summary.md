# Decision model vs LLMs: medical decisions

Run 20260927_071318, dataset=hard.json, workers=4

## Overall (52 cases)

| Model                      | Accuracy | Easy | Hard | Invalid | Avg latency | p50    | p95     | Cost / 1000 calls |
|----------------------------|----------|------|------|---------|-------------|--------|---------|-------------------|
| Jev 1.13                   | 90%      | -    | 90%  | 0%      | 0.62s       | 0.38s  | 3.32s   | $0.018            |
| Qwen3.8-27B 4-bit (RTX 4090)          | 92%      | -    | 92%  | 0%      | 6.99s       | 6.83s  | 11.07s  | $0 (local)        |
| Qwen3.8-27B 4-bit (RTX 4090) +think   | 90%      | -    | 90%  | 0%      | 62.60s      | 60.74s | 113.03s | $0 (local)        |
| DeepSeek V4 Pro            | 90%      | -    | 90%  | 0%      | 1.97s       | 1.75s  | 4.72s   | $0.076            |
| DeepSeek V4 Pro +reasoning | 98%      | -    | 98%  | 0%      | 11.16s      | 8.28s  | 23.38s  | $0.645            |

## Tokens and cost (this run, 52 calls per model)

| Model                      | Avg input tokens | Avg output tokens | Avg reasoning tokens | Total tokens | Total cost |
|----------------------------|------------------|-------------------|----------------------|--------------|------------|
| Jev 1.13                   | 426              | 38                | 0                    | 24,157       | $0.0009    |
| Qwen3.8-27B 4-bit (RTX 4090)          | 191              | 8                 | -                    | 10,397       | $0 (local) |
| Qwen3.8-27B 4-bit (RTX 4090) +think   | 199              | 656               | -                    | 44,496       | $0 (local) |
| DeepSeek V4 Pro            | 170              | 7                 | 0                    | 9,197        | $0.0039    |
| DeepSeek V4 Pro +reasoning | 186              | 542               | 449                  | 37,861       | $0.0336    |

Output tokens include reasoning tokens. "-" means the server did not report that number.

## Accuracy by task

| Model                      | triage | ed_referral | specialty | rx_safety | diagnosis | management | triage within 1 |
|----------------------------|--------|-------------|-----------|-----------|-----------|------------|-----------------|
| Jev 1.13                   | 62%    | 88%         | 100%      | 100%      | 90%       | 100%       | 100%            |
| Qwen3.8-27B 4-bit (RTX 4090)          | 62%    | 100%        | 100%      | 92%       | 100%      | 100%       | 100%            |
| Qwen3.8-27B 4-bit (RTX 4090) +think   | 50%    | 100%        | 100%      | 92%       | 100%      | 100%       | 100%            |
| DeepSeek V4 Pro            | 88%    | 88%         | 100%      | 75%       | 100%      | 100%       | 100%            |
| DeepSeek V4 Pro +reasoning | 88%    | 100%        | 100%      | 100%      | 100%      | 100%       | 100%            |

## Jev as a gate (confident answers kept, the rest escalate to a reasoning model)

| Confidence | Coverage | Accuracy on kept | Escalated |
|------------|----------|------------------|-----------|
| >= 0.0     | 100%     | 90%              | 0         |
| >= 0.6     | 92%      | 96%              | 4         |
| >= 0.7     | 85%      | 95%              | 8         |
| >= 0.8     | 73%      | 97%              | 14        |
| >= 0.9     | 58%      | 100%             | 22        |

## Per case

| Case  | Task        | Level | Gold             | Jev 1.13 | Qwen3.8-27B 4-bit (RTX 4090) | Qwen3.8-27B 4-bit (RTX 4090) +think | DeepSeek V4 Pro | DeepSeek V4 Pro +reasoning |
|-------|-------------|-------|------------------|----------|-------------------|--------------------------|-----------------|----------------------------|
| h_d01 | diagnosis   | hard  | B                | ok       | ok                | ok                       | ok              | ok                         |
| h_d02 | diagnosis   | hard  | C                | ok       | ok                | ok                       | ok              | ok                         |
| h_d03 | diagnosis   | hard  | B                | x A      | ok                | ok                       | ok              | ok                         |
| h_d04 | diagnosis   | hard  | A                | ok       | ok                | ok                       | ok              | ok                         |
| h_d05 | diagnosis   | hard  | D                | ok       | ok                | ok                       | ok              | ok                         |
| h_d06 | diagnosis   | hard  | A                | ok       | ok                | ok                       | ok              | ok                         |
| h_d07 | diagnosis   | hard  | B                | ok       | ok                | ok                       | ok              | ok                         |
| h_d08 | diagnosis   | hard  | C                | ok       | ok                | ok                       | ok              | ok                         |
| h_d09 | diagnosis   | hard  | A                | ok       | ok                | ok                       | ok              | ok                         |
| h_d10 | diagnosis   | hard  | C                | ok       | ok                | ok                       | ok              | ok                         |
| h_e01 | ed_referral | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| h_e02 | ed_referral | hard  | false            | ok       | ok                | ok                       | ok              | ok                         |
| h_e03 | ed_referral | hard  | false            | ok       | ok                | ok                       | x true          | ok                         |
| h_e04 | ed_referral | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| h_e05 | ed_referral | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| h_e06 | ed_referral | hard  | false            | x true   | ok                | ok                       | ok              | ok                         |
| h_e07 | ed_referral | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| h_e08 | ed_referral | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| h_m01 | management  | hard  | B                | ok       | ok                | ok                       | ok              | ok                         |
| h_m02 | management  | hard  | B                | ok       | ok                | ok                       | ok              | ok                         |
| h_m03 | management  | hard  | A                | ok       | ok                | ok                       | ok              | ok                         |
| h_m04 | management  | hard  | C                | ok       | ok                | ok                       | ok              | ok                         |
| h_m05 | management  | hard  | B                | ok       | ok                | ok                       | ok              | ok                         |
| h_m06 | management  | hard  | C                | ok       | ok                | ok                       | ok              | ok                         |
| h_m07 | management  | hard  | B                | ok       | ok                | ok                       | ok              | ok                         |
| h_m08 | management  | hard  | B                | ok       | ok                | ok                       | ok              | ok                         |
| h_r01 | rx_safety   | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| h_r02 | rx_safety   | hard  | false            | ok       | x true            | ok                       | x true          | ok                         |
| h_r03 | rx_safety   | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| h_r04 | rx_safety   | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| h_r05 | rx_safety   | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| h_r06 | rx_safety   | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| h_r07 | rx_safety   | hard  | false            | ok       | ok                | ok                       | x true          | ok                         |
| h_r08 | rx_safety   | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| h_r09 | rx_safety   | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| h_r10 | rx_safety   | hard  | false            | ok       | ok                | ok                       | ok              | ok                         |
| h_r11 | rx_safety   | hard  | false            | ok       | ok                | x true                   | ok              | ok                         |
| h_r12 | rx_safety   | hard  | false            | ok       | ok                | ok                       | x true          | ok                         |
| h_s01 | specialty   | hard  | gastroenterology | ok       | ok                | ok                       | ok              | ok                         |
| h_s02 | specialty   | hard  | psychiatry       | ok       | ok                | ok                       | ok              | ok                         |
| h_s03 | specialty   | hard  | endocrinology    | ok       | ok                | ok                       | ok              | ok                         |
| h_s04 | specialty   | hard  | rheumatology     | ok       | ok                | ok                       | ok              | ok                         |
| h_s05 | specialty   | hard  | neurology        | ok       | ok                | ok                       | ok              | ok                         |
| h_s06 | specialty   | hard  | gastroenterology | ok       | ok                | ok                       | ok              | ok                         |
| h_t01 | triage      | hard  | 3                | ok       | ok                | ok                       | ok              | ok                         |
| h_t02 | triage      | hard  | 3                | x 2      | x 2               | x 2                      | ok              | ok                         |
| h_t03 | triage      | hard  | 4                | x 3      | ok                | x 3                      | ok              | ok                         |
| h_t04 | triage      | hard  | 3                | ok       | ok                | ok                       | ok              | ok                         |
| h_t05 | triage      | hard  | 3                | ok       | ok                | ok                       | ok              | ok                         |
| h_t06 | triage      | hard  | 3                | ok       | ok                | ok                       | ok              | ok                         |
| h_t07 | triage      | hard  | 1                | x 2      | x 2               | x 2                      | x 2             | x 2                        |
| h_t08 | triage      | hard  | 3                | ok       | x 2               | x 2                      | ok              | ok                         |
