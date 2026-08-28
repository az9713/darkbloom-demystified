# Accounting and Payments: Why the Numbers Are Fair

Money flows: consumers deposit, requests debit, providers earn, providers withdraw. This document traces one micro-dollar through that pipeline and names every control that keeps the accounting honest.

## The unit: micro-USD

Every amount in the system is an integer count of micro-USD: 1 USD = 1,000,000 micro-USD (`coordinator/payments/payments.go`). Integer arithmetic means no floating-point rounding drift, ever. The store (Postgres in production) owns balance atomicity and writes a ledger entry for every mutation — deposits, charges, refunds, payouts, rewards. `GET` history endpoints expose the full ledger per account.

## Prices

Price resolution for a request, in order (`coordinator/payments/pricing.go`):

1. The serving provider's custom price (`store.GetModelPrice(providerAccountID, model)`).
2. The platform admin price from the DB (`model_prices` table, `account_id="platform"`, set via `PUT /v1/admin/pricing`).
3. Hardcoded fallbacks: $0.05 per 1M input tokens (50,000 micro-USD), $0.20 per 1M output tokens (200,000 micro-USD).

All prices are micro-USD per 1M tokens. Live pricing is public at `GET /v1/pricing`. Two floors exist:

- **Direct consumers**: a minimum charge of 100 micro-USD ($0.0001) per request.
- **Service/wholesale channels** (e.g. OpenRouter, `Role == service`): no per-request minimum — the debit must match the published per-token feed exactly — but a request with nonzero usage never rounds to $0; integer flooring is caught and charged at least 1 micro-USD. Wholesale traffic is always billed at the platform price, never a provider's higher custom price.

## The life of one charge

The settlement design is **reserve first, settle exact, refund the difference**. Code: reservation in `coordinator/api/consumer.go`; settlement in `handleCompleteAt`, `coordinator/api/provider.go:1785`.

1. **Reserve.** Before dispatch, the coordinator estimates the cost (estimated prompt tokens + `max_tokens` at the resolved rates) and reserves that amount against the consumer's balance. No balance, no dispatch — a provider can never serve an unfunded request.
2. **Serve.** The provider streams the answer and reports final usage (`prompt_tokens`, `completion_tokens`) in its completion message.
3. **Settle.** The coordinator computes the exact cost from the reported usage and the resolved prices, inside a finalization gate (`FinalizeReservation` / `MarkReservationFinalized`) so a concurrent timeout-refund path can never race the settlement into a double charge or double refund.
   - Cost below the reservation → the difference is **refunded**. A failed refund credit is never swallowed: it logs an error and emits `billing.credit_failed` — over-charging a consumer silently is treated as a bug class of its own.
   - Cost above the reservation → the coordinator charges the overage, **capped at 2× the reservation** (`totalCost ≤ 2 × ReservedMicroUSD`). The cap is an explicit fraud circuit-breaker: a provider reporting absurd token counts cannot bill more than twice the pre-flight estimate, and the clamp emits `billing.cost_clamped`.
   - Consumer balance insufficient at settlement → the uncollected charge zeroes, **and the provider payout zeroes with it** (`billing.uncollected_zeroed`). The platform never pays a provider money it could not collect.
4. **Credit the provider.** `providerPayout = totalCost − platform fee`. The request appears in the provider's earnings (`GET /v1/provider/account-earnings`) and in the leaderboard, which separates `work_earnings_micro_usd` (inference) from `reward_earnings_micro_usd` (referral + admin rewards).

Failed requests settle at $0: an error, a timeout, or a pre-content failover refunds the reservation (`refundProviderExtra` is idempotent — it resets to the base reservation so a retry path cannot double-refund).

## Who counts the tokens — the honest answer

The **provider** reports the billable token counts, and the provider is the adversary of the threat model. The coordinator cannot recount exactly (by design, it does not retain the plaintext). The controls, named plainly:

| Control | What it stops |
|---|---|
| 2× overage clamp | Unbounded over-billing by inflated counts |
| Reservation gate | Billing beyond what the consumer's request shape justified, beyond 2× |
| `billing.zero_usage_complete` metric + provider-side content-frame floor | The opposite fraud/bug — completed work reported as zero tokens (billed $0, refunded) |
| `reconcileOutputAdmission` | Reported completion tokens feed back against the admitted token budget |
| Consumer-visible usage | Every response carries usage; a consumer comparing text length to billed tokens exposes systematic inflation |

Within the 2× envelope, moderate over- or under-reporting is detectable by monitoring, not prevented by cryptography. See [../reference/unknown-unknowns.md](../reference/unknown-unknowns.md), entry 2.

## The platform fee — currently zero

`platformFeePercent = 0` (`coordinator/payments/pricing.go:44`) for the public alpha: providers keep 100% of revenue, matching the README and the landing page. Per-account overrides exist (`PUT /v1/admin/users/platform-fee`) and the referral program pays referrers a share of the platform fee — so with a 0% default fee, referrals are dormant. One wrinkle for code readers: the package comment in `payments.go` still says "minus 10% platform fee" — that comment is stale; the constant is authoritative.

## Self-route settles free — with a closed loophole

A request with `X-Darkbloom-Route: self` (or `prefer` that landed on an owned machine) settles at $0. The rule is checked at **settlement**, against the machine that actually served: free **iff** the serving provider's `AccountID` equals the requesting account. Exclusive self-route served by a non-owned provider — which should be impossible — settles as **paid** and logs an error (defense-in-depth against a "mark it free, serve it elsewhere" hole). `prefer` falling back to a public provider settles paid; that is the normal, expected path.

## Money in, money out

- **In**: Stripe Checkout deposits; the webhook credits the internal balance.
- **Out**: provider withdrawals via Stripe Connect Express (bank/card), with region handling in `coordinator/billing/stripe_regions.go`. A provider without a payout destination is skipped for paid public traffic at dispatch time — work that could not be paid is never assigned.

## Base rewards: paid even when the network is quiet

Design: `d-inference/docs/base-rewards.md` (2026-06-06); implementation in `coordinator/payments/baserewards/` (`engine.go`, `epoch.go`, `floor.go`, `alloc.go`). The promise: *"Run a 64GB+ Mac on Darkbloom and even when the network is quiet, you earn at least a Netflix subscription."*

- **Additive, not a backstop**: `payout = earned + floor`. Organic earnings are never clawed back against the floor (a reduction knob `k` exists; shipped value 0).
- **Tiers by verified memory**: $10/month at 24 GB, **$18 at 64 GB (the anchor — Netflix Standard is $17.99)**, $26 at 128 GB, $40 at 512 GB.
- **Verified, not self-reported**: the tier is capped by the serial-number→model maximum-memory lookup cross-checked against reported `MemoryGB`. A small Mac claiming 512 GB banks nothing extra.
- **Gated**: only attested, account-linked machines that are online, healthy, and holding a loaded routable model accrue the floor.
- **Pool-bounded**: a fixed monthly pool (`FLOOR_POOL_B`) is prorated into 5-minute settlement periods and water-filled across eligible machines **smallest-tier-first** (the 48–96 GB workhorse tier fills before idle 512 GB boxes can drain the pool). Total program cost is capped at the fleet level; no individual promise is cut because the machine earned.

The stated trade-off: additive floors do not self-liquidate — the program runs near the pool cap while switched on. The design document says so explicitly.

## Why trust any of this

Three structural reasons, beyond reading the code:

1. **Every mutation is a ledger entry** on an atomic store — balances are reconstructible from history.
2. **The E2E test framework asserts accounting integrity** (`e2e/testbed/assert/` — latency thresholds *and* accounting integrity assertions run against a real coordinator, real Postgres, real provider binary).
3. **Failure paths are metered**: `billing.cost_clamped`, `billing.overage_charged`, `billing.uncollected_zeroed`, `billing.credit_failed`, `billing.zero_usage_complete` all emit to Datadog dashboards — a systematic billing anomaly is a visible graph, not a silent drift.
