# Access Path Elimination

The provider's Mac owner has root. This document explains why root is not enough to read the plaintext, and where the guarantee's edges are.

## The design move: remove paths, don't encrypt memory

Apple Silicon cannot encrypt main memory for third-party code. So Darkbloom enumerates every software mechanism through which the owner could observe the inference data, and closes each one. Apple used the same philosophy for Private Cloud Compute — remove the shell, the debugger, the persistent storage — but Apple owns those servers. Darkbloom applies it against the machine's own owner.

## Step 1: put everything in one process

Traditional serving stacks (vLLM, Ollama, llama.cpp) run the engine as a separate server process. That creates two attack surfaces:

1. Localhost TCP between the front end and the engine — capturable with `tcpdump`, which works even with SIP enabled.
2. The engine binary — replaceable with a version that logs requests.

Darkbloom removes both by running `mlx-swift-lm` **inside** the hardened Swift process. Model weights (up to 76 GB for a 122B-parameter model at 4-bit quantization), tokenizer, all intermediate activations, the WebSocket client, and the X25519 decryption key share one address space. There is no subprocess, no local server, no socket, and no pipe **on the data path** — the only subprocesses the provider spawns are security checks like `csrutil status`, which never touch request data. The engine runs on the GPU through Metal, still in-process.

**Scope note.** This claim holds for the coordinator-routed private path. `darkbloom start --local` (standalone mode) deliberately runs a local Hummingbird HTTP server (`provider-swift/Sources/ProviderCore/Server/StandaloneServer.swift`) serving `/v1/chat/completions` on the owner's own machine for the owner's own traffic. That mode is outside the privacy boundary by design — the owner is the user there.

## Step 2: make the process memory unreadable

Three kernel-enforced mechanisms close the remaining software paths:

| Mechanism | What it blocks | Where |
|---|---|---|
| `ptrace(PT_DENY_ATTACH)` — constant 31, called at startup before any sensitive data loads | `lldb`, `dtrace`, Instruments; permanent for process lifetime; applies to root too | `provider-swift/Sources/ProviderCore/Security/AntiDebug.swift`. The process **refuses to start** if the call fails. |
| Hardened Runtime, signed without `com.apple.security.get-task-allow` | `task_for_pid()` and `mach_vm_read()` from any external process | Code signature; entitlements in `scripts/entitlements.plist` |
| SIP | Root bypass of the two above; unsigned kernel extensions; modification of protected system binaries | macOS kernel |

Supporting hardening in the same module:

- **Core dumps off**: `RLIMIT_CORE = 0` (`AntiDebug.swift`, `disableCoreDumps()`). A crash writes no file containing prompts, weights, or keys.
- **Debugger detection**: a `sysctl` check for the `P_TRACED` flag, as a second net in case `PT_DENY_ATTACH` were ever bypassed.
- **Environment scrubbing**: `Security/EnvironmentScrubber.swift`.
- **Buffer zeroing**: after each request, buffers holding prompts and outputs are cleared with `memset_s` (`Security/SecurityHardening.swift:267`) — chosen because C11 Annex K guarantees the compiler cannot optimize the call away.

The coordinator does not take the provider's word for any of this: `AntiDebugEnabled`, `CoreDumpsDisabled`, and `EnvScrubbed` are required capabilities at the routing chokepoint (`coordinator/registry/registry.go:926`).

**Can plaintext reach the SSD through the virtual-memory system?** The honest answer per path: *swap* — the code takes no `mlock`-style step to pin sensitive buffers; the actual mitigation is that macOS encrypts swap by default. *Sleep/hibernation* — the provider self-caffeinates while serving (`ProviderCore/.../AttestationReadiness.swift:126-133`), which narrows but does not remove the window. *GPU memory reuse* — freed Metal allocations are not separately scrubbed before reuse. None of these is a demonstrated leak; all three sit one class below the kernel-enforced guarantees above, and the docs state them so the boundary is exact.

## Step 3: prove the protections cannot turn off mid-flight

Everything above depends on SIP. The paper proves the key property as Theorem 1 (SIP Runtime Immutability):

1. SIP state lives in NVRAM and is read by the Boot ROM during secure boot (Lemma 1).
2. The only tool that changes it is `csrutil`, and Apple restricts `csrutil disable` to the Recovery Mode boot environment. In normal macOS it returns an error. SIP protects the NVRAM variables that control SIP — a self-reinforcing property.
3. Reaching Recovery Mode requires a reboot. A reboot terminates every process — including the provider process, which erases its in-memory key.

Therefore: if SIP is verified enabled when the process starts, SIP is enabled for that process's entire lifetime. The corollary: one startup check suffices. The production code still checks per request (12 ms, dominated by the `csrutil status` subprocess call) as defense-in-depth.

The same reboot logic closes the "lie and reconnect" hole: a reboot drops the WebSocket; reconnection forces fresh registration, a fresh attestation blob, and fresh code attestation. If the new blob reports SIP disabled, the provider is rejected. If the provider lies, the next MDM `SecurityInfo` query — answered by the OS, not by provider software — reveals the truth. See [attestation.md](attestation.md).

## The complete software attack surface

The paper enumerates it; each row is blocked under the stated assumptions:

| Attack | Defense | Enforced by |
|---|---|---|
| Attach debugger (lldb, dtrace, Instruments) | `ptrace(PT_DENY_ATTACH)` at startup | Kernel |
| Read memory via `task_for_pid` / `mach_vm_read` | Hardened Runtime without `get-task-allow` | Kernel |
| Intercept IPC | No IPC exists — inference is in-process | Architecture |
| Modify the provider binary to add logging | Code signing + SIP: macOS refuses modified signed binaries | Kernel + SIP |
| Replace the binary with a fork | APNs code-identity attestation — only the genuine team-signed app receives the push challenge | Coordinator + Apple |
| Inject a malicious runtime package | No embedded interpreter; the Swift binary links only signed `mlx-swift-lm` | Process + SIP |
| Load an unsigned kernel extension | SIP blocks all unsigned kexts on Apple Silicon | SIP |
| Patch the kernel at runtime | Kernel Integrity Protection — hardware denies writes to kernel pages after boot | Hardware |
| Disable SIP | Requires a Recovery reboot, which kills the process (Theorem 1) | Hardware |
| Read `/dev/mem` | The device node does not exist on Apple Silicon | Hardware |
| DMA via Thunderbolt/PCIe | Per-device IOMMU (DART), default-deny; unauthorized DMA panics the kernel | Hardware |
| RDMA over Thunderbolt 5 (80 Gb/s) | Reported in challenge-response; single-node inference is today's supported boundary; hypervisor Stage-2 isolation validated but not enforced | Hardware + policy |
| **Physical memory probing** | **Not defended.** LPDDR5x is soldered into the SoC package; desoldering is destructive. This is the accepted residual attack — the same one Apple PCC accepts. | — |

## The assumptions, stated honestly

The guarantee holds under three assumptions from the paper's threat model:

1. **Kernel integrity** — no unpatched macOS kernel vulnerability bypasses SIP, Hardened Runtime, or KIP. Apple patched known SIP-bypass CVEs (CVE-2022-22583, CVE-2022-42821, CVE-2023-32369) within weeks. A zero-day breaks the model. Only hardware TEEs are immune to this class.
2. **Secure Enclave integrity** — the SE correctly isolates its keys. Analogous to trusting Intel SGX or ARM TrustZone.
3. **Apple attestation CA integrity** — Apple's Enterprise Attestation Root CA key is not compromised. Analogous to trusting any Web PKI CA.

What is **not** protected even with all assumptions holding: token timing. The owner sees packets leave. Packet intervals reveal approximate prompt length, response length, and generation difficulty. See [performance-economics-limits.md](performance-economics-limits.md).
