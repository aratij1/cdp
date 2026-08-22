# REM-03A candidate-admission report

REM-03A separates eligibility from acceptance using `StandardEligibilityEvidence`, explicit independent evidence classes, configured paths, rejection reasons and observed/required threshold gaps. `ENABLE_REM03A_ELIGIBILITY` is false by default.

All stages fail the remediation gate. Maximum eligibility recall was 35% CMS and 55% UB versus the required 90%. Final CMS/UB recall remained 18.33%/2%, final precision remained 100%, false standard routes remained zero, OCR stayed at one call/page, and decision-only cost was about 6 ms/page.

Decision: `REJECT`. Do not lower eligibility thresholds, combine more paths, rerun A/B/C/D, run holdout, or resume extraction. The next separately authorized work should investigate CMS evidence-class availability and, for already eligible UB pages, REM-03B score normalization/ranking.

