# Prototype module and responsibility inventory

This inventory captures the repository at the start of the first refactoring
assignment.

| Module | Current responsibility | Direction |
| --- | --- | --- |
| `cli.py` | Argument parsing, rendering, progress, and adapter composition | Keep terminal rendering while application services own use-case decisions |
| `dependencies.py` | Characterized dependency display analysis | Preserve until the typed resolver replaces it |
| `index.py` | Query parsing, lookup helpers, active-index compatibility API | Delegate persistence and normalization to ports/domain policy |
| `inventory.py` | Static `.dist-info` inventory | Keep as metadata infrastructure; never import donors |
| `resolver.py` | Local dependency closure and overlap detection | Migrate dictionary results to immutable domain plans incrementally |
| `scanner.py` | Discovery, identity probing, indexing orchestration, progress | Split scanner adapter from application initialization over time |
| `transfer.py` | RECORD planning, classification, transfer, rollback, validation | Preserve transaction behavior while extracting strategies and validators |
| `domain/` | Typed values, errors, package-name and transfer policy | New architecture-neutral domain layer |
| `ports.py` | Protocols for replaceable dependencies | New application boundary |
| `application/indexing.py` | Explicit and automatic initialization; target-only refresh | Own index lifecycle without terminal output |
| `application/installation.py` | Exact install preparation, safety gating, execution | Own install decisions without CLI dependencies |
| `application/queries.py` | Lookup, transfer planning, dependency analysis, resolution | Own read-only index-backed use cases |
| `infrastructure/` | JSON repository and installer adapters | New concrete adapters |

Known prototype duplication at baseline:

- Distribution-name normalization existed in both `index.py` and
  `inventory.py`.
- Path normalization is centralized in `transfer.py`, but should later move to
  a dedicated planning policy module.
- CLI imports and formatting were duplicated and the CLI owned backend process
  creation.

The initial refactor intentionally keeps compatibility functions at the old
module paths so verified behavior can be characterized before deeper service
extraction.
