# Router anchor-miss analysis

REM-02 demonstrates that anchor reconstruction is not the dominant recovery mechanism in this corpus. It uniquely recovered zero pages and overlapped REM-01 on one page. Among 147 baseline standard misses, 73.47% still had at least three OCR tokens. Token reconstruction recovered one CMS document and no UB documents.

The persisted diagnostic taxonomy distinguishes OCR absence/partial text, segmentation, clipping/degradation, variation, zone displacement, present-but-unmatched text and reading order. The next experiment must sample these categories from new reproductions; adding anchors or another OCR engine is not justified by REM-02.

