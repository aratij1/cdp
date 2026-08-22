# Router geometry remediation

`NormalizedPageGeometry` detects content bounds and maps OCR boxes relative to effective content width and height. Unit contracts cover scanner padding, positive dimensions and content-relative coordinates.

REM-01 recovered nine pages and lost one: CMS recall 18.33%→23.33% and UB recall 2%→7%. P95 changed 1,022→1,074 ms. Despite acceptable latency, both recall gains are only +5 points versus the required +10, so REM-01 is rejected and disabled by default.

