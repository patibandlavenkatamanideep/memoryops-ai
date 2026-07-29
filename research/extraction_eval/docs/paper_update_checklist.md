# Paper update checklist

Update the paper **only after** the locked run *and* independent annotations exist.
`build_paper_artifacts` writes a `PAPER_UPDATE_PLACEHOLDER.md`; never paste numbers by hand.

- [ ] Replace the 25-turn pilot headline with the 150-case locked result table
      (precision/recall/F1/exact-match, case-level CIs).
- [ ] Add the provider-comparison figure (fig1) + behavioural-accuracy figure.
- [ ] Add reliability + cost/latency tables (tokens primary; cost only if prices verified).
- [ ] Add the human-agreement (Cohen's kappa) paragraph with N and per-field kappa.
- [ ] Add the error-analysis appendix (representative cases, not only flattering ones).
- [ ] State the frozen runtime tag + commit, dataset hash, prompt hash, seed, model IDs.
- [ ] Keep the 25-turn pilot described as preliminary; do not delete it.
- [ ] Do **not** alter the abstract/conclusion with placeholder or stub-only numbers.
