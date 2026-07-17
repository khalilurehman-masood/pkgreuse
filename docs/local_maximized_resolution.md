# Local-Maximized Resolution

PKGReuse resolves both root requirements and transitive `Requires-Dist`
constraints against the target-local JSON index before invoking an installer
backend.

For each distribution name, the resolver:

1. Reads versions only from the indexed local environments.
2. Rejects editable, stale, missing-RECORD, target-owned, invalid-version, and
   constraint-incompatible candidates.
3. Accumulates constraints contributed by every selected parent distribution.
4. Selects the maximum PEP 440 version satisfying the intersection of those
   constraints.
5. Uses donor affinity only to choose between donors containing that same
   maximum version; affinity never permits a lower version to win.
6. Builds and validates the complete local transfer plan before creating files.

The resolver contains no HTTP client and does not query PyPI or another remote
registry. If no reusable local version satisfies a requirement, or the local
closure is unsafe or incomplete, the wrapper passes the user's original
requirement unchanged to the selected pip or uv backend. Any remote resolution
is therefore performed by pip or uv according to that installer's own normal
configuration.

Examples, given locally indexed versions `1.19`, `1.24`, and `2.0`:

- `numpy>=1.20,<2` selects local `1.24`.
- `numpy>=2` selects local `2.0`.
- `numpy>=3` has an empty local subset and delegates the unchanged `numpy>=3`
  requirement to pip or uv in wrapper mode.
