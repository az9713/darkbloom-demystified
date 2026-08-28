# The Encryption Path

This document traces one prompt from your SDK to the GPU and back, and states exactly who can read it where.

## The precise claim first

Darkbloom's encryption is **hop-by-hop, not strict end-to-end**. Plaintext exists in exactly one intermediate place: transiently, inside the coordinator's memory, for routing and billing. The coordinator never logs the prompt and never stores the prompt. It immediately re-seals the body for the selected provider.

State the claim this way. The repository itself is inconsistent: `d-inference/AGENTS.md` and `d-inference/CLAUDE.md` both say "the coordinator never sees plaintext prompts" — the loose version. The `README.md` "Precise claim" block and the paper's Coordinator Trust Boundary section give the correct version, and `d-inference/docs/architecture/security/encryption.md` documents it. Use the precise version.

One more layer of precision, from the repository's own operations docs: the paper says that transient plaintext sits in an **SEV-SNP** Confidential VM. The production deploy runbook (`d-inference/docs/operations/coordinator-deploy.md`) says the VM runs AMD **SEV** with maintenance policy `MIGRATE` and instructs: "Do not claim SEV-SNP for this VM." The difference matters and is spelled out at Hop 2 below.

## The five hops

### Hop 1 — Consumer → Coordinator

Transport: TLS 1.3 over HTTPS to `https://api.darkbloom.dev/v1`.

Optional extra seal: the consumer can fetch the coordinator's long-lived X25519 public key from `GET /v1/encryption-key` and seal the request body with NaCl Box. This is not a middlebox nicety — it is the only defense against observation between TLS termination and the coordinator process (see Hop 2). The threat model registers it as **optional and off by default** (`d-inference/docs/threat-model.yaml`, SEC-015), and the console UI ships with it off in the default configuration.

### Hop 2 — Inside the coordinator: design vs. production

The design: plaintext exists only inside SEV-SNP-encrypted CVM memory, unreachable even by the operator. The production reality, from the deploy runbook:

- TLS terminates in a **host Caddy** service on the VM, which proxies plaintext over localhost to the coordinator container on `:8080` (host network) — so without Hop-1 sealing, the request body crosses the VM in the clear between Caddy and the coordinator process.
- The VM reports AMD **SEV**, not SEV-SNP: memory is encrypted against the cloud host, but there is no memory integrity and no guest attestation report — and no SEV variant protects against root **inside** the guest.
- The operator has IAP SSH into that VM. An operator at a root shell inside the guest can technically observe the localhost hop and the coordinator process. Hop-1 sealing closes the localhost exposure; process-memory access by guest root is closed by policy and audit, not hardware, today.

So the honest sentence is: **today, the operator cannot casually see prompts (nothing is logged or stored), but is technically able to — the hardware guarantee against the operator that the paper describes is not yet deployed.** The coordinator needs the plaintext to:

- resolve the model and count prompt tokens for billing,
- apply routing gates and pick a provider,
- normalize tool JSON-Schemas before encryption (`coordinator/api/toolschema.go`), so lagging providers never receive template-crashing shapes.

### Hop 3 — Coordinator → Provider (the mandatory seal)

For **every** request the coordinator:

1. Generates a fresh ephemeral X25519 key pair `(sk_e, pk_e)`.
2. Generates a random 24-byte nonce `n`.
3. Encrypts: `c = Box(body, n, pk_provider, sk_e)`, where `pk_provider` is the provider's **attested** X25519 key — the key bound to its Secure Enclave identity in the attestation blob.
4. Sends `(pk_e, n || c)` over the provider's outbound WebSocket.

Code: `coordinator/api/dispatch.go:1457` (queued path; `consumer.go:1041` for the direct path), using `coordinator/internal/e2e/e2e.go`. This seal is not optional and has no plaintext fallback.

Wire format: `24-byte nonce || Poly1305 tag || ciphertext`. Go (`nacl/box`), Swift (libsodium), and a Rust `crypto_box` (v0.9) reference implementation all produce and read the same bytes — proven by `coordinator/internal/e2e/cross_compat_test.go` and a tamper test.

### Hop 4 — Inside the provider

Only the hardened Darkbloom process holds the matching X25519 secret. The secret exists only in that process's memory (`provider-swift/Sources/ProviderCore/Crypto/NodeKeyPair.swift`), protected by the mechanisms in [access-path-elimination.md](access-path-elimination.md). Decryption happens at `ProviderLoop+InferenceHandler.swift:233`, and a fast-path drain check runs **before** decryption so an overloaded provider rejects without ever opening the seal. Decryption failure logs only the error type, never content.

The provider parses the OpenAI-format request from the decrypted bytes and runs generation in the same address space.

### Hop 5 — Provider → Coordinator → Consumer

Each response SSE chunk is encrypted back to the coordinator's **ephemeral** public key `pk_e` from this request. The coordinator memoizes the per-request X25519 shared key for chunk decryption and forgets it when the request terminates (`coordinator/api/chunk_key_cache.go`). It decrypts each chunk, meters usage, and relays the stream to the consumer over TLS (re-sealed if the consumer enabled Hop-1 sealing).

## Forward secrecy

Each request gets its own ephemeral coordinator key pair. Compromise of one ephemeral key decrypts one request — never past or future traffic. The provider's X25519 key is not in a file an owner can steal usefully: it lives in hardened-process memory, and its **binding** to the Secure Enclave identity is what the coordinator verifies (`encryptionPublicKey` field of the attestation blob must match the registration message).

## What each party can read

| Party | Can read |
|---|---|
| Network observer | TLS ciphertext; packet timing |
| Cloud host of the coordinator | Encrypted guest memory (AMD SEV) |
| Coordinator process | Plaintext, transiently; never logged or stored |
| Darkbloom operator (IAP SSH into the VM) | Technically reachable today: the Caddy→coordinator localhost hop (closed by Hop-1 sealing, which is off by default — SEC-015) and, as guest root, coordinator process memory. Held to "does not" by policy and audit, not yet by hardware |
| Provider's Mac owner (root) | Ciphertext on the wire; nothing in process memory (see [access-path-elimination.md](access-path-elimination.md)); packet timing |
| Hardened provider process | Plaintext — it must, to run the model |

The response carries proof headers the consumer can check: `X-Provider-Trust-Level`, `X-Provider-Attested`, `X-Provider-Encrypted`, `X-Provider-Chip`, `X-Provider-Secure-Enclave`.

## What outlives the request

The stream ends. What remains, where:

| Data | Where | Protection | Lifetime |
|---|---|---|---|
| Prompt/output buffers (provider) | Process memory | Zeroed with `memset_s` on completion | Until request end |
| KV cache (provider) | Memory, optionally SSD block store | Encrypted at rest with a Secure-Enclave-wrapped key-encryption key (`ProviderCore/KVCache/`, `KVCacheSSD/`) | Until eviction/idle unload (1 h idle unloads the model) |
| Prefix-cache coordination state (coordinator) | Registry memory | Opaque HMAC route/scope keys only — scoped per account, no prompt content on the wire (`coordinator/registry/cache_route_keys.go`) | Session state |
| Per-request chunk key (coordinator) | Memory | Forgotten at request terminal (`coordinator/api/chunk_key_cache.go`) | Until request end |
| Prompt content in logs/telemetry | Nowhere | Never logged; telemetry field allowlist is the structural backstop (`coordinator/api/telemetry_handlers.go`) | — |
| "Prompt artifacts" on the deploy disk | `/mnt/disks/userdata` | These are prompt-**contract templates** (system-prompt sidecar files), not user prompts | Deploy asset |

Two paths this table cannot fully close on the provider, stated honestly: the code takes no `mlock`-style step to pin sensitive buffers out of swap (macOS encrypts swap by default, which is the actual mitigation), and GPU memory reuse after deallocation is not separately scrubbed. The provider self-caffeinates while serving, which narrows — but does not remove — sleep/hibernation windows.

## Why not strict end-to-end?

Strict E2E (consumer seals directly to the provider) would blind the coordinator to token counts (billing), to model resolution, and to the tool-schema normalization that protects providers from malformed input. Darkbloom chooses a trusted intermediary instead. The paper's supporting claim — consumers can verify the attested coordinator image — has no consumer-facing procedure today: no public endpoint, script, or doc lets you check the image measurement yourself, and plain SEV produces no guest attestation report to check. Until that ships (and the VM moves to SEV-SNP), coordinator trust rests on the published code, the operational record, and the threat model's own candor. The trade is explicit and documented, not hidden.
