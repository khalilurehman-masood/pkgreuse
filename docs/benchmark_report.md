# Initial refactor benchmark report

Measured on Windows, CPython 3.13.7, using the existing target-local index.
Figures are medians from warm repeated runs and are intended as regression
reference points rather than cross-machine claims.

| Measurement | Prototype reference | Initial refactor |
| --- | ---: | ---: |
| Initial scan | 6.8433 s | Not repeated; would rescan the user's Desktop |
| Index size | Not recorded | 438,815 bytes |
| JSON load | Included in observed lookup | 12.891 ms |
| In-memory package lookup | About 13–38 ms observed end-to-end | 0.0127 ms |
| Small RECORD plan | No matching baseline | 6.339 ms for 12 files |
| Application-service lookup | Not applicable | 9.687 ms median; 13.705 ms p95 |
| Local-max candidate selection | Not applicable | 2.8035 ms median across the local index |

The refactor retains the package-first JSON shape. Index loading plus lookup
remains within the SRS target of 50 ms, and planning remains far below the
one-second target. A controlled before/after scan benchmark still needs a
stable fixture tree; rescanning arbitrary user directories is not suitable for
repeatable CI.

The application-service measurement includes repository JSON loading,
validation, requirement parsing, and lookup. It therefore represents the
user-visible hot lookup boundary after the second-phase extraction and remains
comfortably below the 50 ms acceptance target.
