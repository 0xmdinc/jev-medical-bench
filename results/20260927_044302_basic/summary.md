# Decision model vs LLMs: medical decisions

Run 20260927_044302, workers=4

## Overall (50 cases)

| Model                      | Accuracy | Easy | Hard | Invalid | Avg latency | p50    | p95    | Cost / 1000 calls |
|----------------------------|----------|------|------|---------|-------------|--------|--------|-------------------|
| Jev 1.13                   | 96%      | 96%  | 96%  | 0%      | 0.65s       | 0.38s  | 3.49s  | $0.017            |
| Qwen3.8-27B 4-bit (RTX 4090)          | 96%      | 96%  | 96%  | 0%      | 2.28s       | 1.58s  | 5.17s  | $0 (local)        |
| Qwen3.8-27B 4-bit (RTX 4090) +think   | 100%     | 100% | 100% | 0%      | 33.92s      | 28.14s | 98.40s | $0 (local)        |
| DeepSeek V4 Pro            | 100%     | 100% | 100% | 0%      | 1.76s       | 1.32s  | 4.11s  | $0.074            |
| DeepSeek V4 Pro +reasoning | 100%     | 100% | 100% | 0%      | 7.53s       | 6.26s  | 18.47s | $0.593            |

## Accuracy by task

| Model                      | triage | ed_referral | specialty | rx_safety | diagnosis | triage within 1 |
|----------------------------|--------|-------------|-----------|-----------|-----------|-----------------|
| Jev 1.13                   | 80%    | 100%        | 100%      | 100%      | 100%      | 100%            |
| Qwen3.8-27B 4-bit (RTX 4090)          | 80%    | 100%        | 100%      | 100%      | 100%      | 100%            |
| Qwen3.8-27B 4-bit (RTX 4090) +think   | 100%   | 100%        | 100%      | 100%      | 100%      | 100%            |
| DeepSeek V4 Pro            | 100%   | 100%        | 100%      | 100%      | 100%      | 100%            |
| DeepSeek V4 Pro +reasoning | 100%   | 100%        | 100%      | 100%      | 100%      | 100%            |

## Jev as a gate (confident answers kept, the rest escalate to a reasoning model)

| Confidence | Coverage | Accuracy on kept | Escalated |
|------------|----------|------------------|-----------|
| >= 0.0     | 100%     | 96%              | 0         |
| >= 0.6     | 98%      | 98%              | 1         |
| >= 0.7     | 94%      | 98%              | 3         |
| >= 0.8     | 90%      | 100%             | 5         |
| >= 0.9     | 86%      | 100%             | 7         |

## Per case

| Case | Task        | Level | Gold             | Jev 1.13 | Qwen3.8-27B 4-bit (RTX 4090) | Qwen3.8-27B 4-bit (RTX 4090) +think | DeepSeek V4 Pro | DeepSeek V4 Pro +reasoning |
|------|-------------|-------|------------------|----------|-------------------|--------------------------|-----------------|----------------------------|
| d01  | diagnosis   | easy  | C                | ok       | ok                | ok                       | ok              | ok                         |
| d02  | diagnosis   | easy  | A                | ok       | ok                | ok                       | ok              | ok                         |
| d03  | diagnosis   | easy  | D                | ok       | ok                | ok                       | ok              | ok                         |
| d04  | diagnosis   | easy  | B                | ok       | ok                | ok                       | ok              | ok                         |
| d05  | diagnosis   | easy  | B                | ok       | ok                | ok                       | ok              | ok                         |
| d06  | diagnosis   | hard  | C                | ok       | ok                | ok                       | ok              | ok                         |
| d07  | diagnosis   | hard  | A                | ok       | ok                | ok                       | ok              | ok                         |
| d08  | diagnosis   | hard  | D                | ok       | ok                | ok                       | ok              | ok                         |
| d09  | diagnosis   | hard  | B                | ok       | ok                | ok                       | ok              | ok                         |
| d10  | diagnosis   | hard  | A                | ok       | ok                | ok                       | ok              | ok                         |
| e01  | ed_referral | easy  | true             | ok       | ok                | ok                       | ok              | ok                         |
| e02  | ed_referral | easy  | false            | ok       | ok                | ok                       | ok              | ok                         |
| e03  | ed_referral | easy  | true             | ok       | ok                | ok                       | ok              | ok                         |
| e04  | ed_referral | easy  | false            | ok       | ok                | ok                       | ok              | ok                         |
| e05  | ed_referral | easy  | false            | ok       | ok                | ok                       | ok              | ok                         |
| e06  | ed_referral | easy  | true             | ok       | ok                | ok                       | ok              | ok                         |
| e07  | ed_referral | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| e08  | ed_referral | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| e09  | ed_referral | hard  | false            | ok       | ok                | ok                       | ok              | ok                         |
| e10  | ed_referral | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| r01  | rx_safety   | easy  | true             | ok       | ok                | ok                       | ok              | ok                         |
| r02  | rx_safety   | easy  | false            | ok       | ok                | ok                       | ok              | ok                         |
| r03  | rx_safety   | easy  | true             | ok       | ok                | ok                       | ok              | ok                         |
| r04  | rx_safety   | easy  | false            | ok       | ok                | ok                       | ok              | ok                         |
| r05  | rx_safety   | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| r06  | rx_safety   | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| r07  | rx_safety   | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| r08  | rx_safety   | hard  | true             | ok       | ok                | ok                       | ok              | ok                         |
| r09  | rx_safety   | hard  | false            | ok       | ok                | ok                       | ok              | ok                         |
| r10  | rx_safety   | hard  | false            | ok       | ok                | ok                       | ok              | ok                         |
| s01  | specialty   | easy  | cardiology       | ok       | ok                | ok                       | ok              | ok                         |
| s02  | specialty   | easy  | dermatology      | ok       | ok                | ok                       | ok              | ok                         |
| s03  | specialty   | easy  | endocrinology    | ok       | ok                | ok                       | ok              | ok                         |
| s04  | specialty   | easy  | psychiatry       | ok       | ok                | ok                       | ok              | ok                         |
| s05  | specialty   | easy  | gastroenterology | ok       | ok                | ok                       | ok              | ok                         |
| s06  | specialty   | easy  | neurology        | ok       | ok                | ok                       | ok              | ok                         |
| s07  | specialty   | hard  | rheumatology     | ok       | ok                | ok                       | ok              | ok                         |
| s08  | specialty   | hard  | pulmonology      | ok       | ok                | ok                       | ok              | ok                         |
| s09  | specialty   | hard  | endocrinology    | ok       | ok                | ok                       | ok              | ok                         |
| s10  | specialty   | hard  | nephrology       | ok       | ok                | ok                       | ok              | ok                         |
| t01  | triage      | easy  | 4                | ok       | ok                | ok                       | ok              | ok                         |
| t02  | triage      | easy  | 1                | ok       | ok                | ok                       | ok              | ok                         |
| t03  | triage      | easy  | 0                | x 1      | x 1               | ok                       | ok              | ok                         |
| t04  | triage      | easy  | 3                | ok       | ok                | ok                       | ok              | ok                         |
| t05  | triage      | easy  | 1                | ok       | ok                | ok                       | ok              | ok                         |
| t06  | triage      | easy  | 2                | ok       | ok                | ok                       | ok              | ok                         |
| t07  | triage      | hard  | 3                | ok       | ok                | ok                       | ok              | ok                         |
| t08  | triage      | hard  | 3                | ok       | ok                | ok                       | ok              | ok                         |
| t09  | triage      | hard  | 3                | x 2      | x 2               | ok                       | ok              | ok                         |
| t10  | triage      | hard  | 3                | ok       | ok                | ok                       | ok              | ok                         |
