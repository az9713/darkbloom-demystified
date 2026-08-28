# Routing: How the Coordinator Picks a Mac

Routing runs in two stages. First a gate function removes every ineligible provider. Then a cost function ranks the survivors and the cheapest wins.

## Stage 1 — the gates

`providerPassesRoutingGatesLockedEx` (`coordinator/registry/scheduler.go:1119`) is the single source of truth. The dispatch hot path and the capacity preflight (`QuickCapacityCheck`) both call it, so they can never disagree — a prior bug had the preflight promising capacity that routing then refused. Gates, in evaluation order:

| # | Gate | Why |
|---|---|---|
| 1 | Catalog membership | The provider advertises an allowed build of the requested model. Dedicated-family boxes (e.g. Gemma-only) accept only their family. |
| 2 | Dispatch-load cooldown | The pair recently failed a model load with "insufficient memory" — a retry would instant-503 again. |
| 3 | Inference-error cooldown, **shape-keyed** | Repeated provider-side 5xx for this request shape (e.g. a deterministic chat-template crash on tool schemas) quarantines the (provider, model, shape) triple. Shape-keying keeps a tool failure from derouting clean text traffic. Cleared by a same-shape success or TTL. |
| 4 | Capacity-reject cooldown | The pair keeps capacity-rejecting with zero interleaved accepts — the black-hole signature of an engine misreporting its token budget. A busy box that also serves never trips it. |
| 5 | Node-health breaker + health ejection | A node fault-erroring on ~all requests is derouted fleet-wide; the ejection variant keys on stable identity (serial/SE-key/account) so reconnect-loops cannot wash the record. A fail-open rescan pass exists so a bad fleet-wide rollout cannot deroute every provider at once. |
| 6 | Status | Not `offline`, not `untrusted`. |
| 7 | Private-only admission | A machine set `private_only = true` serves only its owner's self-route traffic. |
| 8 | Hardware-trust floor | Production minimum is `hardware`. Self-route to an owned machine relaxes this to `none` — a personal Mac will not be MDM-enrolled. |
| 9 | Runtime verified | Reported runtime hashes match the known-good manifest. |
| 10 | **Private-text support** | The privacy chokepoint, `coordinator/registry/registry.go:926` — see [attestation.md](attestation.md). Never relaxed, including for self-route. |
| 11 | Challenge freshness | The last attestation challenge verified within the maximum age window. |
| 12 | Trait eligibility | Vision-capable builds for media requests; version floors for tool requests (`tools` capability ≥ 0.6.3); render-broken builds fenced for every shape. |

Self-route relaxes exactly two gates (7 and 8). Every privacy-critical gate still applies.

## Stage 2 — the cost function

For each surviving provider the scheduler estimates completion time in milliseconds:

```
costMs = stateMs + queueMs + pendingMs + backlogMs + thisReqMs + healthMs
```

| Term | Meaning |
|---|---|
| `stateMs` | Slot-state penalty: 0 for `running`/`idle`, 30 s for `unknown`, 20 s for `idle_shutdown`; `crashed`/`reloading` are ineligible |
| `queueMs` | effective queue depth × 3,000 ms |
| `pendingMs` | total pending requests × 750 ms |
| `backlogMs` | tokens already committed ÷ effective decode TPS |
| `thisReqMs` | promptTokens ÷ prefillTPS + maxTokens ÷ effectiveTPS |
| `healthMs` | penalty from memory pressure, CPU, thermal state, GPU utilization (from heartbeats) |

Effective decode TPS resolves in priority order: the provider's own observed EWMA under load → the fleet median for the same model and chip family → a load-scaled benchmark fallback. Lowest cost wins; near-ties break by queue depth, then pending load, then randomly among equals to prevent hot-spotting. Capacity is reserved atomically before the provider is returned. Reputation is not a multiplicative score — health simply feeds the additive `healthMs` term.

## Admission and capacity

- **Token-budget admission.** Providers report real engine capacity in heartbeats: active tokens, max potential, queued budget, EWMA decode TPS. The coordinator admits against the engine's own numbers, not a guess.
- **Gray-box budget clamp** (`coordinator/registry/budget_clamp.go`). After a capacity-503 proved the live gate is rejecting, admission stops believing the stale-optimistic heartbeat budget until a fresh one arrives.
- **Queueing.** All providers busy → the request queues with a 120 s timeout; the fleet at capacity returns 429 with `Retry-After` (OpenRouter-compatible); exhaustion returns 503.

## Failure handling during dispatch

- **Speculative TTFT dispatch.** At 50% of the first-token deadline, the coordinator dispatches to a backup provider. First token wins; the loser is cancelled.
- **Pre-content failover.** The loop does not commit to a provider on boilerplate chunks (role-only delta, `response.created`) — only on the first content-bearing chunk. A provider that dies before content is retried invisibly on another machine.
- **A privacy consequence of both, stated plainly:** one prompt can be sealed to and decrypted by **more than one** attested provider — the speculative backup, and each failover target, decrypts and prefills the prompt before its cancel arrives. Every such machine passed the same full attestation gates, and its buffers are zeroed on cancellation like on completion — but the exposure surface per prompt is N attested processes, not always 1.
- **Cancellation.** A consumer disconnect propagates coordinator → provider → engine within 1 s, so generation stops promptly.
- **Two-lane provider writer** (`coordinator/registry/provider_writer.go`). Control frames (challenges, cancels, trust status) take strict priority over data frames on the provider WebSocket, with a per-connection write watchdog — a slow stream can never starve a security challenge.

## Trust tiers, from the consumer's seat

The consumer picks a minimum with the `trust_level` parameter: `none`, `self_signed`, or `hardware`. Production enforces `hardware`, and private text additionally requires code attestation once enforcement is on. Every response says what served it via `X-Provider-Trust-Level` and its sibling headers — see [encryption-path.md](encryption-path.md).
