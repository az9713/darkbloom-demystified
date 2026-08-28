# Fleet Management: Running Inference on Thousands of Home Macs

The fleet is a swarm of consumer machines in people's homes. They sit behind home routers. They reboot, sleep, update, and disappear without warning. This document explains how the coordinator turns that swarm into a dependable inference service.

## Joining the fleet

1. The owner runs one command: `curl -fsSL https://api.darkbloom.dev/install.sh | bash`. The script downloads a signed and notarized bundle, then verifies the SHA-256 hash **and** the code signature before running anything.
2. The owner runs `darkbloom login`. The CLI uses the RFC 8628 device-code flow: it shows a short code, the owner enters the code on the web console, and the machine links to the owner's account.
3. The owner installs the combined enrollment profile (`darkbloom enroll`) for `hardware` trust — see [attestation.md](attestation.md).
4. The owner runs `darkbloom start`. Other CLI commands: `stop`, `status`, `doctor`, `models`, `benchmark`, `local`, `update`, `verify`, `logs`.

## Connectivity: the fleet dials out

Every provider opens an **outbound** WebSocket to the coordinator. Consequences:

- No port forwarding. No firewall change. No inbound exposure. A Mac behind three layers of home NAT works.
- The coordinator holds the live fleet state in memory (the registry). A restart of the coordinator loses no durable data — providers reconnect and re-register, and reconnect takes < 1 s with exponential backoff (`provider-swift/Sources/ProviderCore/Coordinator/ExponentialBackoff.swift`, `ReachabilityMonitor.swift`).
- Reconnection is a security event, not only a network event: it forces fresh registration, a fresh attestation blob, and fresh APNs code attestation.

All coordinator→provider traffic shares that one socket. A two-lane writer (`coordinator/registry/provider_writer.go`) gives control frames — attestation challenges, cancels, trust status — strict priority over data frames, with a per-connection write watchdog. A slow stream can never starve a security challenge.

## Heartbeats: how the coordinator sees the fleet

Each provider sends a periodic heartbeat (`coordinator/protocol/messages.go:234`, `HeartbeatMessage`) carrying:

| Field group | Content | Used for |
|---|---|---|
| Status + `active_model` + `warm_models` | What is loaded in memory right now | Routing to warm capacity |
| `system_metrics` | Memory pressure, CPU, GPU utilization, thermal state | The `healthMs` cost penalty in [routing.md](routing.md) |
| `backend_capacity` | Engine-reported truth: active token budget used/max, queued budget, per-slot state, observed decode/prefill TPS (EWMA), wedge suspicion | Token-budget admission — the coordinator admits against the engine's own numbers, never a guess |
| Prefix-cache fields | Which cached prompt prefixes this machine holds | Cache-aware routing |

Stale-heartbeat protection exists because heartbeats lie by omission: after a capacity rejection proves the live gate is refusing, the gray-box budget clamp (`coordinator/registry/budget_clamp.go`) stops believing the optimistic numbers until a fresh heartbeat arrives.

## Model distribution: no model bytes in the code

The model catalog is data, not code. The coordinator's registry is DB-backed and points at manifests in Cloudflare R2 under `https://models.darkbloom.ai`. A provider downloads the files a manifest lists and verifies a **per-file SHA-256 plus an aggregate SHA-256**. The `ModelScanner` discovers local models fast without hashing; `WeightHasher.computeHash(for:)` computes weight hashes on demand when attestation needs them. A scan-time self-check (`TemplateRenderCheck`) renders each model's chat template once; a model that fails is marked `template_render_ok=false` and fenced from routing.

## Elasticity: warm pool and idle timeout

Home machines cannot all hold every model. Two mechanisms move capacity to demand:

- **Idle timeout.** A loaded model unloads after 1 hour without requests, freeing the GPU memory. The next request lazy-reloads it (cold start), or the coordinator pre-warms it first.
- **Warm-pool controller** (`coordinator/registry/warm_pool*.go`). It counts pressure events per model — capacity rejects, first-token-deadline misses, cold dispatches, speculative dispatches — folds them into a spill-arrival rate (EWMA, alpha 0.3), and sizes a per-model warm target from that demand (a Little's-Law calculation). It then pushes `load_model` messages so the right number of Macs hold each model **before** the next request arrives.

## Living with churn

Home machines fail in every way at once. The defenses, layered:

| Failure | Defense |
|---|---|
| Mac unplugged or crashed mid-request, before any content | Pre-content failover: the dispatch loop commits to a provider only on the first content-bearing chunk. Earlier death retries invisibly on another machine. |
| Slow first token | Speculative dispatch: at 50% of the first-token deadline, the request also goes to a backup provider. First token wins; the loser gets a cancel. |
| Consumer closes the tab | Cancel propagates coordinator → provider → engine within 1 s, so no GPU time burns for a dead request. |
| A (provider, model) pair that keeps failing | Shape-keyed inference-error cooldown, dispatch-load cooldown, capacity-reject cooldown — see the gate table in [routing.md](routing.md). |
| A sick node that reconnects to wash its record | Health ejection keyed to stable identity (serial / SE key / account), which survives reconnects. |
| Everyone busy | Queue with a 120 s timeout; 429 with `Retry-After` at fleet capacity; 503 on exhaustion. |

## Throughput on each Mac: continuous batching

One Mac serves multiple consumers at once. EngineV2 merges all concurrent requests into **one batched forward pass per step** (continuous batching in MLX-Swift). Measured scaling: batch-of-4 over batch-of-1 gives 3.8× throughput on Qwen and 2.9× on Gemma MoE. Temperature 0 takes a vectorized greedy fast path. Each provider serves up to 4 concurrent requests (validation configuration).

## Updating a fleet you do not own

Providers update themselves; nobody SSHes into anyone's home Mac.

1. CI (`.github/workflows/release-swift.yml`) builds, signs with the Developer ID certificate, notarizes with Apple, computes SHA-256 hashes **after** signing, uploads the bundle to R2, and registers the release with the coordinator via `POST /v1/releases`.
2. Providers fetch updates through the same verified path as installation.
3. The coordinator tracks fleet versions (Datadog fleet-version metrics) and enforces version floors per capability — for example, tool-bearing requests route only to providers at `tools` capability ≥ 0.6.3.
4. Old providers degrade gracefully: protocol fields use pointer-typed omission so the coordinator can tell "old provider that cannot say" from "current provider saying an empty set".

## Why this scales

The coordinator does very little per request on the hot path: single-parse frame decode (`coordinator/protocol/type_scan.go` scans the `type` key; malformed input falls back to a full envelope decode), memoized per-request X25519 shared keys for chunk decryption (`coordinator/api/chunk_key_cache.go`, forgotten at request end), and in-memory registry state. The expensive trust work — MDM queries, MDA chains, APNs round-trips — happens at enrollment and on a 5-minute cadence, not per request. Per-request security cost is the 12 ms SIP check on the provider; see [performance-economics-limits.md](performance-economics-limits.md).
