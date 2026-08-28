# Key Concepts

Every term that the other documents use without explanation. One term, one meaning.

**Consumer** — the party that sends an inference request. Trusted; it is their own data.

**Coordinator** — the Go control plane at `api.darkbloom.dev`. It authenticates, routes, bills, verifies attestations, and relays encrypted payloads. The design places it in a Confidential VM; production today runs AMD SEV (see **Confidential VM** below).

**Provider** — an Apple Silicon Mac that serves inference, run by an independent owner. The threat model assumes the owner is adversarial: root access, physical custody, active attempts to read the data.

**Confidential VM (CVM)** — a virtual machine whose memory is encrypted by the CPU. The paper specifies AMD SEV-SNP (memory encryption + integrity + guest attestation reports). Production reality: the deploy runbook (`d-inference/docs/operations/coordinator-deploy.md`) reports the VM as AMD **SEV** with maintenance policy `MIGRATE`, and states "Do not claim SEV-SNP for this VM." SEV encrypts guest memory against the cloud host but, unlike SEV-SNP, gives no memory integrity and no guest attestation report — and it never protects against root **inside** the guest.

**NaCl Box** — the encryption construction used on every hop: X25519 key agreement + XSalsa20-Poly1305 authenticated encryption. Wire format: `24-byte nonce || 16-byte Poly1305 tag || ciphertext`. Go uses `golang.org/x/crypto/nacl/box`; Swift uses libsodium (swift-sodium); a Rust `crypto_box` reference implementation verifies cross-language interop in `coordinator/internal/e2e/cross_compat_test.go`.

**Hop-by-hop encryption** — Darkbloom's actual model, as opposed to strict end-to-end. Plaintext exists transiently inside the coordinator's CVM memory for routing and billing, then is re-sealed to the provider. See [../concepts/encryption-path.md](../concepts/encryption-path.md).

**Ephemeral key** — a fresh X25519 key pair the coordinator generates for every single request. This gives forward secrecy: compromise of one key opens one request.

**MLX / mlx-swift-lm** — Apple's array framework for Apple Silicon and the Swift LLM library built on it (fork maintained at `d-inference/libs/mlx-swift-lm`). Darkbloom runs it inside the provider process, on the GPU via Metal.

**In-process inference** — the model, tokenizer, weights (up to 76 GB for a 122B-parameter model at 4-bit), and the decryption key all live in one process address space. No subprocess, no localhost server, no IPC — so `tcpdump` and binary swapping find nothing to attack.

**SIP (System Integrity Protection)** — the macOS mechanism that stops root from modifying `/System`, loading unsigned kernel extensions, or bypassing Hardened Runtime. Its state lives in NVRAM and can change only from Recovery Mode, which requires a reboot.

**Hardened Runtime** — a code-signing mode. Signed without the `com.apple.security.get-task-allow` entitlement, the kernel denies `task_for_pid()` and `mach_vm_read()` against the process from any other process.

**`PT_DENY_ATTACH`** — `ptrace` request constant 31. Called at startup, it makes the kernel permanently deny debugger attachment to the process, including from root. Implemented in `provider-swift/Sources/ProviderCore/Security/AntiDebug.swift`.

**KIP (Kernel Integrity Protection)** — Apple Silicon hardware that denies writes to kernel code pages after boot.

**ARV (Authenticated Root Volume)** — the sealed system volume: a Merkle tree of SHA-256 hashes over every system file. Any modification breaks the seal.

**Secure Enclave (SE)** — Apple's isolated security coprocessor. Darkbloom uses it to generate a P-256 ECDSA signing key that never leaves the hardware. This key signs the attestation blob, challenge responses, and code-identity nonces.

**Attestation blob** — a JSON document of 15 fields (alphabetical order, deterministic encoding) that the SE key signs: `sipEnabled`, `secureBootEnabled`, `serialNumber`, `binaryHash`, `encryptionPublicKey`, `systemVolumeHash`, and others. Verified in `coordinator/attestation/attestation.go:132`.

**MDM (Mobile Device Management)** — Apple's device-management framework. Darkbloom runs MicroMDM and uses exactly three permissions (`AccessRights = 1041`: bits 0, 4, 10) to query — never to control — the device.

**MDA (Managed Device Attestation)** — an Apple service that returns an Apple-signed X.509 certificate chain proving the device is genuine hardware, with device properties encoded as OIDs under prefix `1.2.840.113635`.

**APNs code-identity attestation** — Darkbloom's replacement for the missing App Attest on macOS (v0.6.0+). Apple's push infrastructure only delivers to a process whose signature, App ID (`io.darkbloom.provider`), and provisioning profile check out — enforced by AMFI (`AppleMobileFileIntegrity.kext`). The coordinator pushes an encrypted nonce; only the genuine binary can receive and decrypt it. See [../concepts/attestation.md](../concepts/attestation.md).

**Trust tier** — the consumer-selectable minimum verification level per request: `none`, `self_signed`, `hardware`. Production enforces `hardware`. Private text traffic additionally requires code attestation once enforcement is on.

**Self-route** — the header `X-Darkbloom-Route: self` restricts routing to machines the caller's account owns. Free, encrypted, no fallback to the paid fleet. `X-Darkbloom-Route: prefer` tries owned machines first, then falls back.

**Routing gates** — the eligibility checks in `coordinator/registry/scheduler.go:1119` (`providerPassesRoutingGatesLockedEx`) that a provider must clear before the cost scheduler considers it.

**Privacy chokepoint** — `providerSupportsPrivateTextLocked` at `coordinator/registry/registry.go:926`: the single function through which every private-text routing decision passes. No self-route exemption exists at this gate.

**Challenge-response** — every 5 minutes the coordinator sends a random 32-byte nonce; the provider re-checks SIP, Secure Boot, and RDMA status, signs `nonce || timestamp || publicKey` with the SE key, and must answer within 30 seconds. A report of disabled SIP or Secure Boot causes immediate untrust with no grace period.

**RDMA over Thunderbolt 5** — a macOS 26.2+ feature that lets a physically connected Mac read host memory at 80 Gb/s via DMA, bypassing all software protections. Off by default; enabling it requires a Recovery OS boot. Today Darkbloom records RDMA status as telemetry; a hard hypervisor gate is planned, not shipped.

**MoE (Mixture-of-Experts)** — a model architecture where only a small "active" subset of parameters (e.g. 3B of 35B) computes each token. On bandwidth-bound consumer hardware only active weights cross the memory bus, which is why MoE models dominate Darkbloom's economics.

**Heartbeat** — the periodic provider→coordinator message carrying status, loaded models, live system metrics, and engine-reported token-budget capacity (`coordinator/protocol/messages.go:234`). The coordinator's whole live view of the fleet is built from heartbeats plus challenge results.

**Warm pool** — the controller (`coordinator/registry/warm_pool*.go`) that watches per-model demand pressure and pushes `load_model` messages so enough Macs hold each model before the next request needs it.

**Continuous batching** — one Mac merges all concurrent requests into a single batched forward pass per step. Measured scaling: batch-of-4 gives 3.8× the throughput of batch-of-1 on Qwen, 2.9× on Gemma MoE.

**Micro-USD** — the ledger unit: 1 USD = 1,000,000 micro-USD, integer arithmetic only. Every deposit, charge, refund, payout, and reward is a ledger entry in this unit.

**Reservation** — the pre-flight hold on a consumer's balance (estimated cost) before dispatch. Settlement charges the exact reported usage, refunds the difference, and caps any overage at 2× the reservation.

**Base rewards** — pool-bounded additive income for eligible providers, tiered by verified memory ($10/24 GB up to $40/512 GB per month, $18/64 GB as the anchor), settled in 5-minute periods even when the network is quiet. Design: `d-inference/docs/base-rewards.md`.
