# The Five Attestation Layers

Encryption to the provider's key is only as good as the answer to one question: **is that key held by a genuine, hardened, unmodified Darkbloom process on genuine Apple hardware?** No single signal can answer it, because most signals are reported by the party under suspicion. Darkbloom layers five independent checks, each covering a hole the others leave.

| Layer | Mechanism | What it proves | What it cannot prove |
|---|---|---|---|
| 1 | Secure Enclave P-256 signature | A hardware-bound identity signed this exact self-report | That the report is true; that the key is really in the SE |
| 2 | MDM `SecurityInfo` | The **OS** — not provider software — reports SIP, Secure Boot, ARV | That the device is genuine Apple hardware |
| 3 | MDA-over-MDM | Apple's CA signs: genuine hardware, serial, UDID, SepOS, SIP, Secure Boot | Which binary is running |
| 4 | Challenge-response every 5 min | The posture is still good **now**, and the key is live | Which binary is running |
| 5 | APNs code identity (v0.6.0+) | The running binary is the genuine team-signed build | Device posture (still needs 2+3) |

## Layer 1 — Secure Enclave attestation

On first run the provider generates a P-256 ECDSA key inside the Secure Enclave via CryptoKit (`provider-swift/Sources/ProviderCore/Security/SecureEnclaveIdentity.swift`, `PersistentEnclaveKey.swift`). The private key never leaves the SE; the `dataRepresentation` stored on disk is an opaque handle that only works on the device that created it.

The provider signs an attestation blob of 15 JSON fields in alphabetical order — among them `sipEnabled`, `secureBootEnabled`, `secureEnclaveAvailable`, `serialNumber`, `binaryHash`, `encryptionPublicKey`, `systemVolumeHash`, `rdmaDisabled`, `timestamp`. Three fields do structural work:

- **`serialNumber`** bridges to Layers 2 and 3: the coordinator uses it to find the MDM enrollment record and cross-check independently.
- **`encryptionPublicKey`** binds the X25519 key from [encryption-path.md](encryption-path.md) to this SE identity. The coordinator verifies it matches the registration message — proof that the signing device and the decrypting process are the same machine.
- **`binaryHash`** (SHA-256 of the running binary) is **deliberately not a trust gate**. It is self-reported by the possibly-adversarial measurer, so a fork would just report the blessed hash. Since v0.6.0 it serves only drift telemetry and transparency-log matching; Layer 5 carries the real code-identity proof.

**The cross-language trap.** Swift signs; Go verifies; both must see byte-identical JSON. Swift escapes `/` as `\/`; Go does not. So the coordinator verifies against the **original raw bytes** (`json.RawMessage`), never a re-encode (`coordinator/attestation/attestation.go:132`; the `marshalSortedJSON` re-encode exists only as a fallback for Go-generated test blobs). Verification enforces: valid DER-encoded ECDSA signature over SHA-256 of the blob; `secureEnclaveAvailable`, `sipEnabled`, `secureBootEnabled` all true; timestamp fresh; `encryptionPublicKey` matching. `AuthenticatedRootEnabled` is logged, not enforced — multi-boot Macs and older macOS report it unreliably.

## Layer 2 — MDM independent verification

Layer 1 has two holes: the coordinator cannot tell an SE-resident key from a software key (identical ECDSA output), and the blob's SIP field comes from `csrutil status`, a software check. Layer 2 asks the OS instead. The device enrolls with MicroMDM; the coordinator sends the `SecurityInfo` command, and the OS MDM client answers with `SIPEnabled`, `SecureBootLevel`, `AuthRootVolume`, `FDE_Enabled`, `RecoveryLock`, `FirewallEnabled`. Requirements: SIP enabled, Secure Boot "full", Authenticated Root Volume enabled. Any discrepancy against the self-report is immediate rejection.

**The helpful circularity** (paper Proposition 1): to make MDM report a false "SIP enabled", the owner would have to modify system frameworks in `/System/Library/` — which requires SIP to be disabled, which ARV would also expose (the sealed system volume's Merkle root would change). The lie requires the very state it denies.

**Minimal permissions.** The enrollment profile sets `AccessRights = 1041` = 2^0 + 2^4 + 2^10: inspect device, query device information, query security information. The other 10 bits — including erase (bit 3), lock, profile/app install, settings changes — are unset. The coordinator can only ask questions. Owners can unenroll any time in System Settings, which removes profile and certificates completely.

Enrollment is one signed `.mobileconfig` combining three payloads — SCEP (RSA-2048 device identity), MDM, and an ACME `device-attest-01` payload. The ACME payload is **inactive**: its hardware-bound key lands in a platform-restricted keychain third-party apps cannot use, and its leaf certificate lacks the SIP/SecureBoot OIDs. It is retained for future transport-layer use only.

## Layer 3 — MDA: Apple signs the hardware

Layers 1–2 verify posture, not provenance. Layer 3 asks Apple. The coordinator sends the MDM `DeviceInformation` command with `DevicePropertiesAttestation`; the device contacts Apple's attestation servers and returns a DER X.509 chain: leaf → Apple Enterprise Attestation Sub CA 1 (P-384) → Apple Enterprise Attestation Root CA (P-384, valid until 2047). The leaf encodes properties as OIDs under `1.2.840.113635`: serial (`100.8.9.1`), UDID (`100.8.9.2`), OS version, SepOS version, LLB version, SIP status (`100.8.13.1`), Secure Boot (`100.8.13.2`), kext policy, and a freshness code (`100.8.11.1`).

**The binding trick.** The coordinator sets `DeviceAttestationNonce = SHA-256(SE public key)`. Apple embeds that hash in the leaf's `FreshnessCode` OID. When the returned code matches the hash of the key the coordinator already accepted, the Layer-1 signing key is cryptographically chained to Apple-attested genuine hardware. Verification lives in `coordinator/attestation/mda.go`. Forging Layer 3 requires compromising Apple's CA; forging Layer 2 "only" requires a SIP bypass.

## Layer 4 — continuous challenge-response

Enrollment-time trust decays. Every 5 minutes (and immediately at registration) the coordinator sends a random 32-byte nonce. The provider re-checks SIP (`csrutil status`), Secure Boot, and RDMA (`rdma_ctl status`), signs `nonce || timestamp || publicKey` with the SE key, and must respond within 30 seconds (`provider-swift/Sources/ProviderCore/ProviderLoop+AttestationChallenge.swift`).

Policy: SIP or Secure Boot reported disabled → **immediate untrust, no grace period** — by Theorem 1 that state proves a deliberate weakened-security reboot. Three consecutive signature failures → untrust (distinguishes flaky networks from replaced machines). RDMA status is recorded as telemetry, not yet enforced (hypervisor reporting is retired in current providers; the coordinator still decodes it so older < v0.6.31 signed payloads verify). Challenge freshness is itself a routing gate: a provider whose last verified challenge is too old receives no traffic.

## Layer 5 — APNs code identity

The remaining gap after Layers 1–4: a fork of the provider that logs prompts could still present a valid SE key and a valid MDA chain — those attest the *device*, not the *code*. macOS offers no App Attest (`DCAppAttestService.isSupported` is `false`), and `binaryHash` is self-reported. Darkbloom's answer repurposes Apple's push infrastructure as a non-self-reportable code-identity oracle.

Only a process meeting three conditions can receive a push for topic `io.darkbloom.provider`: signed with Darkbloom's Developer ID team certificate; carrying App ID `io.darkbloom.provider`; authorized by an Apple-signed provisioning profile with the `aps-environment` entitlement. AMFI (`AppleMobileFileIntegrity.kext` + `amfid`) enforces all three at launch, before the process may register for push at all. A patched binary, a re-signed binary, or a different Team ID cannot obtain a device token for the topic.

Protocol (`coordinator/apns/attestor.go`; payload built at `attestor.go:307`; provider side `ProviderCore/Apns/APNsBridge.swift`):

1. At registration the provider sends its APNs device token `T` with its X25519 key `K` and SE key.
2. The coordinator generates a fresh 32-byte nonce, encrypts it to `K` with NaCl Box, and pushes the ciphertext to `T` over Apple's HTTP/2 push service.
3. Only the genuine binary receives the push; it decrypts with `K`, signs the nonce with the SE key, and returns both over the WebSocket.
4. On verification the connection is marked `CodeAttested` — per-connection, in-memory. Reconnecting forces re-attestation; a SIP-downgrade reboot necessarily drops the WebSocket.

Limits: background push is best-effort and budget-throttled (the coordinator can switch to alert mode); APNs requires a logged-in macOS GUI Aqua session, so headless Macs fail closed for private traffic; APNs proves App ID/Team ID, not the exact version — version pinning awaits reproducible builds plus a public transparency log of blessed `cdhash` values.

## What attests the model, not just the machine

The five layers prove the machine and the binary. The **model weights** have their own, weaker chain: the provider verifies per-file and aggregate SHA-256 hashes when downloading from the registry (`https://models.darkbloom.ai`), and reports weight hashes upward — but the reporter is the provider, made trustworthy only by Layer 5, and the coordinator's weight-hash verification is **currently fail-open** (`d-inference/docs/threat-model.yaml`, SEC-007: a substituted model may be served without detection). Runtime-manifest verification (`RuntimeVerified` at the chokepoint below) covers the runtime, not the weights. Consumers get download-integrity plus code-attested reporting — not an independent cryptographic proof of which weights ran. See [../reference/unknown-unknowns.md](../reference/unknown-unknowns.md), entry 1.

## Where it all converges: the routing chokepoint

`providerSupportsPrivateTextLocked` (`coordinator/registry/registry.go:926`) is the single function every private-text routing decision passes. It requires **all** of: an attested X25519 key; backend `mlx-swift` (the legacy Python backend is unroutable); encrypted response chunks; a verified runtime manifest (reported hashes match the known-good manifest); `ChallengeVerifiedSIP` — the coordinator-verified value, explicitly not the self-reported field; `CodeAttested` once the enforcement deadline passes (a live-policy check, so the grace→enforce flip needs no reconnects); and the capability flags `TextBackendInprocess`, `TextProxyDisabled`, `AntiDebugEnabled`, `CoreDumpsDisabled`, `EnvScrubbed`.

There is no self-route exemption at this gate. The owner's own machine clears the same bar.

Consumers can audit the result: `GET /v1/providers/attestation` exposes privacy-redacted trust status including the Apple MDA chains, verifiable against Apple's public root CA. Serials, UDIDs, and raw certificates stay private.
