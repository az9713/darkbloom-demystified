# Performance, Economics, and Limits

The measured numbers, why the economics work, and what the system honestly does not protect.

## Measured results

End-to-end validation ran on two machines at once: an AWS `mac2-m2.metal` instance (Apple M2, 24 GB unified memory, macOS 14.8.4) and a local M4 Max (48 GB, macOS 26.3). Both passed all five attestation layers, then served live traffic.

| Measurement | Value |
|---|---|
| Decode, Qwen3.5 9B Q4, M4 Max | 92 tok/s |
| Decode, Qwen3.5 9B Q4, M2 | 22 tok/s |
| Time to first token | 1.4 s |
| SIP check per request | 12 ms — the largest per-request security cost, dominated by the `csrutil status` subprocess; one startup check would suffice by the SIP theorem, so this is defense-in-depth |
| 8 concurrent requests, 2 providers | 100% success; 6,517 tokens in 76.2 s |
| Cancel propagation on consumer disconnect | < 1 s, coordinator → provider → engine |
| Reconnect after disconnect | < 1 s |
| `lldb` attach against the provider | Denied |
| Hypervisor overhead, Qwen3.5-27B BF16 (50.1 GB), M4 Max 128 GB | 0% — 8.2 tok/s baseline vs 8.0 tok/s with 100% of memory VM-mapped (within noise) |
| Map a 60 GB hypervisor pool | 2.5 ms (3,840 × 16 MB chunks) |
| AES-256 encrypt+decrypt, 16 MB tensor | 0.37 ms (42.5 GB/s — fast enough to overlap GPU compute at 2.9% effective overhead with double buffering) |

Security overhead is negligible: about 12 ms per request.

## Why the economics work: active parameters vs. total parameters

A provider's marginal cost is electricity only:

```
C_local = P_elec / (R_tok × 3,600) × 10^6   dollars per million output tokens
```

At the U.S. average $0.15/kWh, an Apple Silicon workstation draws ~100 W under inference load ($0.015/hr) and 5 W idle.

Cloud APIs price by **total** parameter count. Local decode cost follows only the **active** parameters per token, because decode is memory-bandwidth-bound and only active expert weights cross the bus. Mixture-of-Experts models therefore break the comparison open:

| Model | Architecture | M4 Max (546 GB/s) | M3 Ultra (819 GB/s) |
|---|---|---|---|
| Qwen3.5 9B | Dense | 92 (measured) | 94 |
| Qwen3.5 27B | Dense | 21 | 32 |
| Qwen3.5 35B-A3B | MoE, 3B active | 101 | 152 |
| Llama 3.1 70B | Dense | 8 | 13 |
| Qwen3.5 122B-A10B | MoE, 10B active | 25 | 35 |
| MiniMax M2.5 230B | MoE, 10B active | does not fit | 40 |

Unmeasured entries are bandwidth-scaled at 65% efficiency. Note the headline: the 35B MoE (101 tok/s) beats the 27B dense (21 tok/s) despite more total parameters.

| Model | Cloud $/M | Local $/M (electricity) | Advantage |
|---|---|---|---|
| Qwen3.5 35B-A3B | $1.30 | $0.04 | 32× |
| Qwen3.5 122B-A10B | $2.08 | $0.09 | 23× |
| Qwen3.5 27B | $1.56 | $0.20 | 7.8× |
| MiniMax M2.5 230B | $0.95 | $0.16 | 6× |
| Llama 3.1 70B | $0.30 | $0.49 | 0.6× — the cloud wins |

Dense models above ~32B favor H100 clusters (3.35 TB/s bandwidth, ~6× an M4 Max). The sweet spot for Darkbloom is MoE models with small active counts on large unified memory. Pricing is live at `GET /v1/pricing`; alpha providers keep 100% of revenue; self-route to your own machine is free.

## What the system does not protect

State these as plainly as the guarantees.

**Token timing.** Content is protected; timing is not. The owner sees packets leave their machine. Prefill duration reveals approximate prompt length; packet count reveals response length; inter-token delays reveal generation difficulty. Darkbloom does not implement constant-time inference. Possible mitigations (buffering, jitter) are not deployed. Apple PCC and every non-TEE system share this gap.

**A macOS kernel zero-day.** The entire model rests on Assumption 1: no unpatched kernel bug bypasses SIP, Hardened Runtime, or KIP. Software-enforced boundaries cannot survive kernel compromise; only hardware TEEs can. The defense is Apple's patch record (known SIP-bypass CVEs fixed within weeks), which is a track record, not a proof.

**RDMA over Thunderbolt 5, today.** macOS 26.2+ RDMA lets a physically connected Mac read host memory at 80 Gb/s, bypassing every software protection. It is off by default and needs a Recovery OS boot to enable. Current status, precisely: providers report `rdmaDisabled` in every challenge response, and the coordinator records it as **telemetry**. `hypervisorActive` is retired — current providers no longer send it; the coordinator only keeps decoding it so signed payloads from older (< v0.6.31) providers still verify. RDMA-enabled providers are kept off private text by operational policy, but no strict scheduler gate is enforced yet. The validated future fix — Hypervisor.framework Stage-2 page tables that hide inference memory from host physical addressing, measured at 0% overhead — is not production-enforced. Single-node inference with RDMA disabled is the supported boundary.

**Headless Macs.** APNs needs a logged-in GUI Aqua session. A headless or login-screen Mac cannot become code-attested and fails closed for private traffic once enforcement is on.

**Binary version pinning.** APNs proves App ID and Team ID, not the exact release. Downgrade control awaits reproducible builds plus a public transparency log of blessed `cdhash` values.

**Enrollment reach.** Hardware attestation requires MDM enrollment with Apple attestation authority (MicroMDM + an Apple push certificate). Arbitrary consumer devices need an Apple Business Manager–class pathway.

**The residual physical attack.** Probing LPDDR5x soldered into the SoC package. Desoldering is destructive. Darkbloom accepts it; Apple PCC accepts the same.

## Future work in the paper

OHTTP (RFC 9458) relays plus RSA blind signatures for non-targetability (so the coordinator cannot link identity to content); promoting `hypervisorActive` to a hard gate; multi-device sharding over Thunderbolt 5 RDMA (< 50 µs latency) toward 400B+ parameter models — single-machine components validated, two-machine RDMA-visibility validation outstanding; encrypted model weights released only against a full attestation chain; and generalizing access-path elimination beyond inference to any confidential computation on consumer hardware.
