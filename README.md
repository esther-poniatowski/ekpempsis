# Ekpempsis

Ekpempsis synchronizes a repository-owned set of files into a publication checkout, validates the
complete candidate, and publishes it only through an explicit command.

## Commands

```text
ekpempsis sync --config ekpempsis.yml
ekpempsis publish --config ekpempsis.yml --message "Publish supporting material"
ekpempsis status --config ekpempsis.yml
```

`sync` changes no Git history and contacts no remote. It constructs and validates the complete
publication image before it changes the checkout. `publish` repeats that preparation, commits only
the declared targets, pushes without force, and then reports the state returned by the publication
provider. `status` only queries that provider.

## Configuration

Paths are relative to the root of the consumer repository. Each target must be unique and remain
inside the publication checkout.

```yaml
version: 1
target:
  repository: esther-poniatowski/ccn2026
  checkout: artifacts/mixture-input-encoding_poster_ccn2026/deploy
  branch: main
  provider: github-pages
entrypoint: index.html
max_entrypoint_bytes: 30720
files:
  - source: artifacts/mixture-input-encoding_poster_ccn2026/landing/index.html
    target: index.html
  - source: artifacts/mixture-input-encoding_poster_ccn2026/landing/README.md
    target: README.md
    transform: strip-yaml-frontmatter
```

The schema rejects unknown fields. A transform names a built-in operation; configuration cannot
execute a shell command. Every declared source must exist. Resources that are not ready remain
absent from `files` and appear without a link in the page.
