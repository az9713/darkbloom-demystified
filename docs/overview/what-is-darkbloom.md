# What Is Darkbloom?

Darkbloom is a network that turns idle Apple Silicon Macs into a private, OpenAI-compatible inference cloud. The person who owns a Mac in the network cannot read the prompts or the replies that the Mac processes.

## The problem

When you send a prompt to a cloud AI service, your privacy rests on a contract, not on hardware. Hardware Trusted Execution Environments (Intel TDX, AMD SEV-SNP, NVIDIA Confidential Computing) encrypt server memory, but the server hardware costs $14,000 or more.

Apple sold over 100 million Apple Silicon Macs since 2020. Each Mac has 64–256 GB of unified memory and 273–819 GB/s of memory bandwidth. A Mac can run models with up to 235 billion parameters at interactive speed. These Macs sit idle most of the day.

One obstacle stops the obvious plan. Apple Silicon gives no hardware TEE to a third-party application:

| Apple feature | Limit |
|---|---|
| Secure Enclave | Signs with a hardware-bound P-256 key. Cannot encrypt main memory. Cannot run arbitrary code in isolation. |
| App Attest (`DCAppAttestService`) | `isSupported` returns `false` on macOS. The API works only on iOS and iPadOS. |
| Boot measurement | No public API exposes boot measurements or PCR-style remote attestation. |

## The core idea

Darkbloom does not encrypt the memory. Darkbloom **removes every software path** to the memory. Apple uses the same design in Private Cloud Compute (PCC). Darkbloom applies the design to a harder case: in PCC, Apple owns the hardware; in Darkbloom, the hardware owner is the assumed attacker.

The threat model states this plainly. The provider (the Mac owner) can run code as root, install software, reboot the machine, and touch the ports. The system must keep the prompt private against all of that. The residual attack — the one attack the system accepts — is physical probing of the LPDDR5x memory chips, which are soldered into Apple's System-on-Chip package. Desoldering destroys them. Apple accepts the same residual attack for PCC.

## The three parts

| Part | Language | Where it runs | Job |
|---|---|---|---|
| Coordinator | Go (~88,118 non-test lines) | GCP VM with AMD SEV memory encryption (the paper targets SEV-SNP; production is not there yet — see [../reference/paper-vs-repo.md](../reference/paper-vs-repo.md)) | Auth, routing, billing, attestation, encrypted relay |
| Provider | Swift CLI `darkbloom` (~90,244 lines) | The owner's Mac, one hardened process | Decrypt, run inference in-process on the GPU via MLX, encrypt the reply |
| Consumer | Any OpenAI or Anthropic SDK | Your machine | Send requests to `https://api.darkbloom.dev/v1` |

Two design facts carry most of the weight:

1. **The provider connects outbound.** The Mac opens a WebSocket to the coordinator. The owner opens no port and changes no firewall rule.
2. **Inference runs in-process.** The model runs inside the same hardened Swift process that holds the decryption key. There is no subprocess, no local server, and no pipe to tap on the coordinator-routed path.

## How it fits together

1. You send an OpenAI-format request over TLS to the coordinator.
2. The coordinator checks your key, picks a Mac, and bills your account. It reads the plaintext for this step. The design puts that plaintext inside hardware-encrypted Confidential-VM memory; production today delivers AMD SEV, one step short of the SEV-SNP the paper claims (see [../concepts/encryption-path.md](../concepts/encryption-path.md)). The coordinator never logs or stores the prompt.
3. The coordinator seals the request with a fresh per-request key to the chosen Mac's attested encryption key.
4. Only the hardened process on that Mac can open the seal. It runs the model on the GPU and encrypts each response chunk back.
5. The coordinator relays the stream to you.

Five independent attestation layers prove that the Mac is genuine Apple hardware, that its protections (SIP, Secure Boot) are on, and that the process holding the key is the genuine, team-signed Darkbloom binary. See [../concepts/attestation.md](../concepts/attestation.md).

## Who you are trusting, in one table

"Distributed" describes the compute supply, not the trust. The full list of parties a consumer relies on:

| Party | Trusted for | If it fails or defects |
|---|---|---|
| Apple | Secure Enclave, SIP, Hardened Runtime, KIP, AMFI, APNs delivery, the MDA attestation CA, kernel patching | The attestation architecture collapses; revoking one Developer ID certificate ends code attestation fleet-wide |
| The Darkbloom operator | One coordinator VM does all routing, billing, and verification; the operator has IAP SSH into that VM | Routing/billing stop; an operator inside the VM can technically reach transient plaintext today — see [../concepts/encryption-path.md](../concepts/encryption-path.md) |
| AMD + GCP | SEV memory encryption of the coordinator VM against the cloud host | Cloud-host-level memory access to the coordinator |
| The Mac owner | Nothing. This is the point — see [../concepts/access-path-elimination.md](../concepts/access-path-elimination.md) | Already the threat model |
| The provider *process* | Correct separation between concurrent consumers in one batch | Cross-request leakage would be a software bug, not a broken hardware boundary |

## Why anyone runs a provider

Providers earn per token served. During the public alpha, providers keep 100% of revenue (0% platform fee). Consumer prices target roughly half of comparable hosted APIs. A provider who is also a consumer can add `X-Darkbloom-Route: self` to route a request only to a machine their own account owns — free of charge, with the same encryption. The economics favor Mixture-of-Experts models, where the local cost advantage over cloud APIs reaches 6–32×. See [../concepts/performance-economics-limits.md](../concepts/performance-economics-limits.md).

The honest flip side: an owner hosts computation they **cannot inspect** — by design. Content responsibility, abuse handling, and provider obligations live in the original repository's legal documents (`d-inference/docs/legal/privacy-policy.md`, `d-inference/docs/legal/terms-of-service.md`), which any prospective provider should read before enrolling.
