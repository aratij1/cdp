# CDP Architecture Reset Baseline

## Immutable code baseline

- Baseline commit: `3a7d5d1aa8310cad653de352e1c68182ef55e3c4`
- Commit subject: `feat: complete phase 8.10 region precision recovery`
- Branch at audit time: `main`
- GitHub `origin/main` at audit time: `1ed19cd0015aa6ef72afc13a99b39d81e951eb17`
- GitHub status: Phase 8.10 is committed locally but is not on `origin/main`.
- Later Phase 8.11 files in the working tree are explicitly outside this baseline and were not promoted or rewritten by this reset.

The commit is the immutable code boundary. Phase 8.10 generated results are ignored by Git, so the result boundary is the frozen replay summary below, not merely a directory name.

## Dataset and truth freeze

The reset uses only `SOURCE_A`, `SOURCE_B`, and `SOURCE_C` under `evaluation_data/phase8_8_generalization`. The locked holdout was not opened.

- Dataset inventory: 72 files
- Deterministic dataset inventory SHA-256: `8cc484492305c8b9cf807c9d34eab62e9cf1ff684a033bc30f5dfd1b36c75405`
- Six truth-file inventory SHA-256: `8f15a42fc00fdd4bf6a2fcd1dd5a5d63a6ab7cd0a9596f49d59d0ea126255e37`
- Phase 8.10 replay summary SHA-256: `2443e63a6333db31f44af1d18ec987ec309b1cc345a09ca3cc0a75b65255d8f0`
- Samples: 420 validation fields, 89 UB service-line rows
- Dataset firewall: DEV, VALIDATION, and ADVERSARIAL only; locked holdout untouched

The inventory hash is SHA-256 over sorted `relative-path NUL file-sha256 LF` entries. This definition makes the aggregate reproducible across filesystems.

## Frozen implementation identity

| Concern | Frozen identity |
| --- | --- |
| CMS template | `cms1500@02-12`; SHA-256 `eda2d70ae53af7459bc6823afd13e22eeb6a2846a3426e887749545a70ee86e4` |
| UB template | `ub04@2014`; SHA-256 `041aa18e4174915c05d9a26d76cd8afe497662d09c10b65d23d28205a2b84fc9` |
| CMS field graph | `cms1500_v1`; SHA-256 `5bf013021879be595e8c62f1363e1cd1978089c0a28a1cefe6249c27002456b9` |
| UB field registry | `ub04_v1`; SHA-256 `90bfcb55bd309bbef42c91be9d1137b6081c22fc04db64451a17e890009bb881` |
| Localization scoring | SHA-256 `d1242c99f71826a74e7c97795ec6b6a16d76054ac41785d5323bb84b11d92a3c` |
| Candidate scoring | SHA-256 `ead8dffee216b6d36caa42b6d810d6e21a81632388b3f4470c8291c9f01864a4` |
| Evaluation OCR routes | SHA-256 `6fa2f1080f145e3ae30ecd34883e849496fe39860cad9993892169c958aa0440` |
| OCR preprocessing | SHA-256 `0573ce7c7879be1a328d9baeb9e4c9a77f07bf399546ef7f8fa50c0fc40f40d3` |
| OCR runtime | RapidOCR ONNX Runtime 1.4.4; ONNX Runtime 1.29.0; OpenCV headless 5.0.0.93; Pillow 12.3.0 |
| Normalization | `packages/field_normalization.py`; SHA-256 `43e93354b295f656631d4dcf71fa2b381d241c3f8f540e5915cf625a8d1ff839` |
| Evaluation evidence policy | `evidence-policy-v4-dependency-aware-balanced`; SHA-256 `0529ee537d82e253797cfc22e2d4cebb3d2d3fafee3b68c8d1a365e8bc4e1cd2` |
| Runtime evidence policy | `evidence-policy-v4-dependency-aware` |
| Claim evidence | `claim-evidence-v1`; SHA-256 `4241e517548bfe0874e41d4e57fcf6d5f4562205e7b94538c09573895216a06a` |
| Claim decision | `claim-decision-v1`; SHA-256 `86678924bc441882463366ccc3631ba138384f5009b667843973f61e7dd9d941` |

## Reproduction result

The frozen replay is internally stable at 89.05% overall, 88.74% CMS, 89.42% UB, and 91.67% critical-field accuracy, with 100% accepted precision, zero critical false accepts, and $0 cloud cost. The extraction path is reproducible. Full runtime/evaluation parity is not: evaluation selects an evaluation-only route registry and the balanced evidence policy while runtime loads the default runtime policy. This is an evaluation-plane defect, not an extraction improvement.
