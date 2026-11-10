# Implementation notes

## Assumptions

- The PDF's simplified rules are implemented literally. Matching uses only first
  name, last name, suffix, ZIP, house number, street, and unit. Other columns
  cannot create or prevent a match. Original mailing text is retained in output.
- REC_ID is a unique integer; Plan keys are unique and all record keys must
  exist in Plan. Structural errors stop the run, while the specified mail-record
  validation failures produce REJECT. Empty rows are skipped. Formula/error cells
  are unsupported and reported rather than interpreted as missing values.
- Integral numeric ZIP cells are treated as digit strings before padding;
  decimal ZIPs are invalid. House numbers remain digit strings (014 differs from
  14). A numeric-only ADDRESS_1 is valid because no non-empty street check is
  specified. Missing first names are valid but cannot match anything.
- Lookup keys/values are normalized; conflicting entries fail validation.
  Nicknames use one lookup, not recursive alias expansion. LIST values and
  KEY_CODE values are exact; identical Outside LIST values count once.

## Where the rules can fail on real data

1. **Initial bridges can merge different people.** Input 100064 (John Smith),
   100003 (Jane Smith), and 100141 (J Smith) share 3 River Rd, ZIP 37201.
   J matches both names, so all three become one group; John survives and Jane
   is dropped even though they could be distinct household members. A production
   rule could flag ambiguous initials for review or require corroborating evidence
   before merging two different full names.

2. **Missing unit numbers can miss a duplicate.** Input 100161 (Nina Shaw,
   9 Elm Court, no unit) and 100124 (Nina Shaw, 9 Elm Ct, Apt 3), ZIP 27601,
   both survive. If these identify the same person, two letters are sent. A
   production rule could verify the missing unit against a validated address
   source or request review when a unique candidate exists. Treating every blank
   unit as a wildcard would risk merging residents of different apartments.

3. **Suffix gaps can erase a generation boundary.** Input 100007 (Daniel Price,
   no suffix) and 100026 (Daniel Price JR) at 42 Quarry Rd, ZIP 78701, merge.
   They could be a parent and child. A production rule could request review and
   require additional evidence before combining them.

These are possible failures, not claims that the sample records describe
different real people. Changing them would change the required output.

## Testing

Run the 37 tests with:

```sh
python -m unittest discover -s tests -v
```

Tests include normalization edge
cases, non-matching unit/suffix boundaries, transitive nickname/initial/suppress
bridges, priority and numeric-ID ties, distinct LIST counts, original-field
preservation, summary balances, shuffled-input determinism, and union-find versus
an explicit graph traversal. Integration tests reopen generated XLSX files and
check exact sheet/column names, ZIP text, formula safety, CLI failures, and known
decisions from the supplied workbook. Larger same-address blocks should be
benchmarked before adopting this batch implementation at production scale.
