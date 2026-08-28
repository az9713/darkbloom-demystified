# Paper vs. Repository: The Deltas

The paper (`papers/dginf-private-inference.tex`, April 2026) describes a real but earlier system. The repository moved on. Check this table before quoting the paper.

Repository state examined: 2026-08-27; latest `CHANGELOG.md` entry is release candidate v0.8.14 (2026-08-26, not shipped).

## Claims to adjust

| Paper claim | Repository state |
|---|---|
| Coordinator runs in an AMD SEV-**SNP** Confidential VM; even the operator cannot access its memory | The deploy runbook (`docs/operations/coordinator-deploy.md`) reports the production VM as AMD **SEV** with maintenance policy `MIGRATE` and states "Do not claim SEV-SNP for this VM." TLS terminates in host Caddy and crosses localhost in the clear unless the consumer's optional sealing is on — which is off by default (`threat-model.yaml`, SEC-015). The operator has IAP SSH. The paper's coordinator guarantee is design intent, not deployed fact. |
| Coordinator weight/hash policy protects model integrity | Weight-hash verification is currently fail-open (`threat-model.yaml`, SEC-007). |
| ~14,500 lines total (provider 6,000 Swift; coordinator 4,000 Go) | ~90,244 Swift lines in `provider-swift/Sources/`; ~88,118 non-test Go lines in `coordinator/`. The paper describes the validation-era build; the production system is ~12× larger. |
| "No subprocess, no local server, no IPC" | True for the coordinator-routed private path. `darkbloom start --local` runs a Hummingbird HTTP server (`provider-swift/Sources/ProviderCore/Server/StandaloneServer.swift`) for the owner's own standalone use — outside the privacy boundary by design. Scope the claim to the private path. |
| Hypervisor Stage-2 memory isolation defends RDMA | Validated experimentally (0% overhead; 60 GB pool mapped in 2.5 ms), **not enforced**. `hypervisorActive` is telemetry. `CLAUDE.md` notes current providers no longer even send the field; the coordinator keeps decoding it so older (< v0.6.31) signed payloads still verify. |
| RDMA-without-hypervisor providers are excluded | By operational policy only. No strict scheduler gate exists yet; the paper itself concedes this in its Hypervisor section, but summaries often miss it. |
| `binaryHash` in the attestation blob | Demoted since v0.6.0 to drift telemetry and transparency-log matching. The live code-identity gate is APNs attestation (Layer 5). The hash stays in the SE-signed canonical so a blessed-build policy can return as an emergency gate. |
| ACME `device-attest-01` in the enrollment profile | Shipped but inactive. The hardware-bound key lands in a platform-restricted keychain third-party apps cannot access, and the leaf lacks SIP/SecureBoot OIDs. MDA-over-MDM is the operative provenance path; ACME is retained for future transport-layer use. |
| Coordinator uses step-ca | Legacy. `coordinator/stateexport/` archives "MicroMDM (+ legacy step-ca) state" for migration; the active stack is MicroMDM + SCEP + MDA. |
| "The coordinator never sees plaintext" (in repo docs, not the paper) | The paper and `README.md` are precise: plaintext exists transiently in CVM memory, never logged or retained. `AGENTS.md` and `CLAUDE.md` still carry the loose sentence. The precise version is correct. |

## Production subsystems the paper does not cover

| Subsystem | Where |
|---|---|
| EngineV2 continuous batching — all concurrent requests merged into one batched forward pass per step; near-linear scaling (B=4/B=1 = 3.8× on Qwen, 2.9× on Gemma MoE) | `provider-swift/Sources/ProviderCore/Inference/EngineV2*.swift`, `docs/engine-v2/` |
| Encrypted KV cache — Secure-Enclave-wrapped key-encryption key, encrypted store, SSD block store with no-follow IO | `provider-swift/Sources/ProviderCore/KVCache/`, `KVCacheSSD/` |
| Prompt-prefix cache routing — cache-aware provider selection with HMAC-derived route keys and receipts | `coordinator/registry/cache_*.go` |
| Speculative decoding and multi-token prediction (MTP) — `mtp_mode = "auto" \| "on" \| "off"` as of v0.8.14 | `provider-swift/Sources/ProviderCore/SpecDec/`, `EngineV2MTPAssistant.swift` |
| Vision serving — Qwen3-VL per-image tower prefill with memory budgeting (`VisionTowerBudget`), video spans, M-RoPE | `EngineV2Vision*.swift`; v0.8.13–v0.8.14 changelog |
| Billing — Stripe deposits into a micro-USD ledger, Stripe Connect payouts, referrals, base rewards | `coordinator/payments/`, `coordinator/billing/` |
| Self-route and private-only machines | `docs/provider/self-route.md`; gates 7–8 in [../concepts/routing.md](../concepts/routing.md) |
| Speculative TTFT dispatch, pre-content failover, two-lane provider writer, single-parse frame decode | `coordinator/registry/provider_writer.go`, `coordinator/protocol/type_scan.go`, `coordinator/api/chunk_key_cache.go` |
| Trust-status UI, console, admin dashboard, landing | `console-ui/`, `admin-ui/`, `landing/` |
| Fan control service | `provider-swift/Sources/DarkbloomFan*` |
| Tool-schema normalization + template-render self-check fencing | `coordinator/api/toolschema.go`, Swift `ToolSchemaNormalization`, `TemplateRenderCheck` |

## Where paper and code agree exactly

Worth saying, because it is most of the security core: the NaCl Box construction and wire format (verified cross-language in `coordinator/internal/e2e/`); per-request ephemeral keys; the raw-bytes signature verification with the Swift `\/` escaping caveat (`coordinator/attestation/attestation.go:132`); `PT_DENY_ATTACH` + Hardened Runtime + SIP with fail-closed startup; `memset_s` buffer zeroing; `AccessRights = 1041`; the MDA freshness-nonce SE-key binding; the APNs protocol; the 5-minute challenge cadence with immediate untrust; and the routing gate list, which the paper reproduces from `providerPassesRoutingGatesLocked` nearly verbatim.

## The privacy-claim wrinkle inside the repo

`AGENTS.md` (and `CLAUDE.md`) state the loose privacy claim while `README.md` corrects it in a dedicated "Precise claim" paragraph. When writing about Darkbloom, always use the README/paper formulation: hop-by-hop encryption; transient plaintext only inside attested CVM memory; never logged or retained; provider is the final decryption endpoint, bound to an attested Secure Enclave identity.
