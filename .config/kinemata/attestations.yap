# Findings this repository declares correct, and why. Hand-written; see the
# README's "Text that is correct as written". Each entry fails the run if it
# stops matching a finding, so edit it together with the line it names.
attestations:
  - registry: "claims"
    entry: "claim:commit"
    antipattern: "badf00d0"
    path: "README.md"
    text: "`` `badf00d0` `` gets it read as a commit, because a pure-hex code span almost"
    correct: "badf00d0 is the hex value this paragraph uses to illustrate data that claims mistakes for a commit; it names no commit"
  - registry: "claims"
    entry: "claim:commit"
    antipattern: "badf00d0"
    path: "README.md"
    text: "text: \"`badf00d0`, the bytes `ba df 00 d0`; `bin'0101'` is `0x50`; `dna'GAC'` is\""
    correct: "the line is the example attestation's own text field, quoting yapyon's spec line; badf00d0 there is bytes data, not a commit"
