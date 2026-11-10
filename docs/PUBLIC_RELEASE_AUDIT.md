# Publication-readiness review

This public summary package was constructed from the verified 10 November 2026 research publication bundle and the original frozen source-code commit.

### Excluded
- Full second-level `observed_seconds.csv` files and associated `event_report.json`, `window_summary.csv`, `endpoint_returns.csv`.
- Detailed CRC32 audit CSV files; they remain with the author.
- Source/analysis hashes containing private local paths, local raw manifests, and full analysis metadata with host paths.
- Original raw exchange message streams and partial segments.
- Publication package provenance files that refer to excluded datasets as bundled/public.

### Included
- Original frozen protocol and scripts, plus synthetic tests, reproduced from the pre-recording Git commit.
- Public-summary working paper, five figures, aggregated case/contrast CSVs, and a standalone aggregation consistency checker.

### Security-check scope
A targeted pattern scan of the 10 tracked files in the original frozen source commit did not identify obvious GitHub credential, API key, SSH private key or password literals. This does not replace external secret scanning or review of any untracked VM data. The public release script refuses to package `.env`, `.pem`, `.key`, `.git`, and raw/derived observations. The source root is deliberately allowlisted.

### Critical history note
The existing data-bearing private repository should **not** be changed to public: its second commit already contains derived time-series files, which remain accessible in its history even after a later delete. Instead create a separate public repository whose ancestry contains ONLY the original clean frozen-methodology commit and this sanitized publication commit. See https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository .
