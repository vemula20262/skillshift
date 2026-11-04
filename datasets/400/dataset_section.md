# Dataset section draft — 400-task version

We use SpreadsheetBench Verified, preserving its original instructions and input/reference workbook pairs. This version contains 400 source tasks and 398 eligible tasks allocated to development (198), validation (100), and test (100). Source metadata warnings exclude tasks 56225 (initial file already passes verification) and 56274 (reference data-validation inconsistency) from execution. All raw source records remain available in the original archive.

Selection and split assignment are deterministic and do not use model outcomes. Observed workbook identity and precautionary split blocks are distinguished. The smaller version excludes unresolved-lineage candidates before selecting 120 tasks; the larger version retains them in whole precautionary blocks. Neither procedure proves all task sources independent. File readability and hashes are checked, but reference semantics and evaluator behavior are not certified by these checks.

The accompanying data_summary.csv supplies measured split/category counts. We plan two attempts per eligible development task (396 original attempts). No such attempts have been collected in this package; feedback pool definitions, success/failure ratios, and concentration statistics remain pending. This draft must be updated after actual collection.
