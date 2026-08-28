# How Darkbloom Works — Explainer Docs

Darkbloom rents idle Apple Silicon Macs as an OpenAI-compatible inference cloud. The Mac owner has root access and physical custody, yet the owner cannot read your prompt or the model reply.

These documents explain the system. Sources: the paper `dginf-private-inference.pdf` (April 2026, Gajesh Naik, Eigen Labs) and the repository `d-inference/` (release candidate v0.8.14, 2026-08-26). All file references point into `d-inference/`.

## Navigation

| Question | Document |
|---|---|
| What is Darkbloom? Why does it exist? | [overview/what-is-darkbloom.md](overview/what-is-darkbloom.md) |
| What do the terms mean? | [overview/key-concepts.md](overview/key-concepts.md) |
| How does a prompt travel? Who can read it where? | [concepts/encryption-path.md](concepts/encryption-path.md) |
| How does the Mac hide the plaintext from its own owner? | [concepts/access-path-elimination.md](concepts/access-path-elimination.md) |
| How does the coordinator know a Mac is genuine and hardened? | [concepts/attestation.md](concepts/attestation.md) |
| How does the coordinator pick a Mac for my request? | [concepts/routing.md](concepts/routing.md) |
| How does the network manage thousands of home Macs? | [concepts/fleet-management.md](concepts/fleet-management.md) |
| How does the money work? Why are payments fair? | [concepts/accounting-and-payments.md](concepts/accounting-and-payments.md) |
| How fast is it? What does it cost? What does it NOT protect? | [concepts/performance-economics-limits.md](concepts/performance-economics-limits.md) |
| Which questions did I not know to ask? | [reference/unknown-unknowns.md](reference/unknown-unknowns.md) |
| Where does the paper differ from the code? | [reference/paper-vs-repo.md](reference/paper-vs-repo.md) |

## Reading order

1. Read [what-is-darkbloom.md](overview/what-is-darkbloom.md) for the mental model.
2. Read the concept documents in order: encryption path, access path elimination, attestation, routing, fleet management, accounting and payments.
3. Read [performance-economics-limits.md](concepts/performance-economics-limits.md) for the numbers and the honest limits.
4. Read [unknown-unknowns.md](reference/unknown-unknowns.md) for the questions the architecture raises but marketing does not answer.
5. Read [paper-vs-repo.md](reference/paper-vs-repo.md) before you quote the paper. The code moved past the paper in several places.

## Scope note

These documents track the paper `papers/dginf-private-inference.tex` (1,268 lines) and repository state on 2026-08-27. The repository has its own 92-file documentation set at `d-inference/docs/` with `d-inference/docs/README.md` as entry point. These explainer files do not replace that set. They answer one question: how does Darkbloom work.
