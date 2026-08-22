# CDP Unknown Structured Routing

`UNKNOWN_STRUCTURED` is now a first-class `BundleType`, canonical route,
event-payload field and downstream extraction trigger. It is no longer
collapsed into `D_UNSTRUCTURED`. `UNKNOWN_UNSTRUCTURED` and `NON_CLAIM` are
also explicit. Non-claims complete routing without creating an extraction
request or an artificial review requirement.
