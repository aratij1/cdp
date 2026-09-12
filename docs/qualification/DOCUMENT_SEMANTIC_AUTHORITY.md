# Document and semantic authority policy

This policy must be bound to the frozen Track B comparator and membership receipt before production qualification. Updating it invalidates prior qualification; it is not a retrospective relabeling of Track A.

| Case | Authority and decision |
| --- | --- |
| SAME | Preserve printed SAME and its location. Resolve only an explicitly defined form reference to an unambiguous source field in the same owner-approved claim. Retain reference chain and original evidence. Missing referent, cycles, or disagreement require review. |
| Identity aliases | Case/spacing presentation normalization does not establish identity. Nicknames, reordered components and alternative identities require an approved authoritative alias relationship with provenance. Never infer aliases from Track A predictions. |
| Member ID presentation | Preserve original identifier, leading zeros and suffixes. Only documented issuer-specific separator/case rules may normalize presentation. No fuzzy matching, digit substitution, dropped prefixes, or patient-name-based correction. |
| Source-absent totals | Annotate SOURCE_ABSENT distinctly from illegible, blank, zero and VALUE. An absent printed total cannot be manufactured by arithmetic or an attachment. Required absent fields require review under the field acceptance policy. |
| Derived versus printed totals | Keep derived totals separately with formula, input source references and decimal arithmetic. Printed total remains the printed-field truth. Disagreement requires review; never overwrite printed evidence with a computed sum. |
| Multi-page membership | Source owner approves exact page hashes, document/claim aliases, page order, page role, completeness and provenance before field review. Missing, reused, unbound or ambiguous pages block freezing and claim-level STP. |
| Attachment ownership | Require explicit source-owner binding to one claim and document; adjacency or matching names alone is insufficient. Shared/ambiguous attachments require adjudicated ownership. Attachment values cannot silently override claim-form fields. |

Reviewers inspect source-only material independently. Neither model output nor candidate Recall@5 is truth. Disagreements require a third authorized adjudicator with reasons and evidence. Freeze candidate, policy, source, membership, review and truth digests before one untouched Track B acceptance run.

Use the existing operator contract in track_b_completion/INPUT_CONTRACT.md and the existing evaluation.qualification_closure controller. No owner approvals or reviewer decisions are implied by this document. These explicit requirements still need runtime/comparator parity verification before qualification.


## Runtime and qualification boundary

`ClaimDecisionService` reports runtime `STP_STANDARD` eligibility and
`runtime_evidence_safe`; it cannot assert correctness against unseen truth.
Its `stp_safe` remains false and `qualification_status` is `NOT_EVALUATED`.
Output requires complete matching persisted field decisions, the canonical
claim decision, and explicit owner-approved membership. Missing ownership or
an incomplete decision creates a durable output hold. Owner membership must
be supplied by the governed deployment as `claim_membership` in the internal
processing envelope; workers preserve it through preparation, routing,
extraction and validation. Public file upload alone confers no ownership.

The existing Track B controller binds the semantic-policy digest and owner
membership digest into frozen truth. The existing release comparator alone
computes measured `stp_safe` after matching accepted fields against that truth,
checking complete membership and attachment ownership, semantic evidence,
no human intervention, and successful automatic output. Historical runtime
`STP_SAFE` strings are declarations, not proof. Changed policy, membership or
candidate inputs require a new governed freeze; old measurements cannot be
requalified retrospectively.

The SAME resolver validates every explicit reference and retains its original
printed evidence. Raw SAME remains under review at the machine-acceptance
boundary; resolution does not bypass field evidence or acceptance policy.
Name comparison preserves component boundaries and order. No issuer-specific
member-ID presentation rule or identity-alias authority is activated by this
remediation; exact identifiers remain the default.
