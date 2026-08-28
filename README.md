# d-inference-tutorial

**This is the tutorial clone of the original [d-inference](https://github.com/Layr-Labs/d-inference) repository.** It does not contain the Darkbloom source code. It contains an independent explainer documentation set that demystifies how Darkbloom works, written from two primary sources:

1. The paper: *Private Distributed Inference on Consumer Hardware* (Gajesh Naik, Eigen Labs, April 2026) — included here as [`dginf-private-inference.pdf`](dginf-private-inference.pdf).
2. The `d-inference` repository code, examined at release candidate v0.8.14 (2026-08-26).

Video introduction: Matt Berman's ["This feels illegal..."](https://www.youtube.com/watch?v=z1ez0yWu1P4) covers Darkbloom.

Darkbloom turns idle Apple Silicon Macs into a private, OpenAI-compatible inference cloud. The Mac owner has root access and physical custody — yet the owner cannot read the prompts or the replies. These docs explain how that works, how the network manages a fleet of home machines, how the accounting stays fair, and which hard questions remain open.

## Read the tutorial

- **Website (GitHub Pages):** https://az9713.github.io/d-inference-tutorial/
- **Markdown entry point:** [`docs/index.md`](docs/index.md)

| Section | Content |
|---|---|
| Overview | What Darkbloom is, why it exists, and a full glossary |
| Encryption path | The hop-by-hop journey of one prompt, and who can read it where |
| Access path elimination | How a Mac hides plaintext from its own root user |
| Attestation | The five layers that prove a Mac is genuine, hardened, and running the real binary |
| Routing | The 12 eligibility gates and the cost function that picks a machine |
| Fleet management | How thousands of home Macs become a dependable service |
| Accounting and payments | Micro-USD ledger, reserve→settle→refund, fraud clamps, base rewards |
| Unknown unknowns | 12 questions the architecture raises, answered honestly with open/partial/solved status |
| Paper vs. repo | Where the April 2026 paper and the current code differ |

## Layout

```
README.md                    this file
dginf-private-inference.pdf  the paper (also in the original repo under papers/)
md2html.py                   regenerates every docs/*.html from its .md twin
docs/
├── index.md / index.html    entry point (index.html is the GitHub Pages home)
├── overview/                what-is-darkbloom, key-concepts
├── concepts/                encryption-path, access-path-elimination, attestation,
│                            routing, fleet-management, accounting-and-payments,
│                            performance-economics-limits
└── reference/               unknown-unknowns, paper-vs-repo
```

Each Markdown file has a matching dark-mode HTML twin. After editing any `.md`, run `python md2html.py` to refresh the HTML.

## Not affiliated

This tutorial is an independent study companion. Darkbloom, the d-inference code, and the paper belong to their authors; the original repository carries its own license. All `file:line` references in these docs point into the original repository's tree.
