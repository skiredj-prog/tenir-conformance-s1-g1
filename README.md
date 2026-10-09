# tenir-conformance-s1-g1
S1 G0+G1 executable harness for REG/TENIR — Evidence Lost After Commit (candidate operational definition + self-contained harness). Not a validation of production REG.

## S11 scope and limitations

> **Trust anchor.** The signed Realm-manifest loader (introduced in follow-up PR #13) accepts the public key from the caller. A signed trust-root lookup is not yet implemented. Until it is, the caller controls what is trusted.
>
> **Key rotation and revocation.** Not implemented. A key accepted at load time remains trusted for the lifetime of the process.
>
> **Postconditions.** Declared postconditions are checked against the Realm policy. They are not proofs that an effect occurred in the external world. Assumption D (declarative attributes are truthful) is required for the end-to-end claim.

S11 execution commitments are in-process conformance artifacts, not a durable or distributed commit protocol. The RFC 8785 checks are targeted vectors, not the complete conformance corpus. This repository's CI is not evidence of production deployment validation.
