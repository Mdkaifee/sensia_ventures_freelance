import random
import unittest

from merge_purge.engine import merge
from merge_purge.matching import components, duplicates
from merge_purge.normalization import address, name, normalize, unit, zip5

NICKNAMES = {"BOB": "ROBERT", "BILL": "WILLIAM", "WILL": "WILLIAM", "LIZ": "ELIZABETH"}
SUFFIXES = {"STREET": "ST", "ST": "ST", "ROAD": "RD", "RD": "RD"}
PLAN = [
    dict(KEY_CODE="H", TYPE="House", PRIORITY=10, LIST="House"),
    dict(KEY_CODE="A", TYPE="Outside", PRIORITY=50, LIST="Alpha"),
    dict(KEY_CODE="B", TYPE="Outside", PRIORITY=50, LIST="Beta"),
    dict(KEY_CODE="C", TYPE="Outside", PRIORITY=60, LIST="Alpha"),
    dict(KEY_CODE="S", TYPE="Suppress", PRIORITY=None, LIST="DNC"),
]


def record(rec_id, key="A", first="John", **changes):
    result = dict(REC_ID=rec_id, KEY_CODE=key, FIRST_NAME=first, LAST_NAME="King", SUFFIX=None,
                  ADDRESS_1="14 Maple Street", ADDRESS_2=None, CITY="Boston", STATE="MA", ZIP=2134,
                  EMAIL="unused@example.com", CUSTOMER_ID="unused", PHONE="unused",
                  GENDER="unused", LAST_ORDER_DATE="unused", ORDER_TOTAL=999)
    result.update(changes)
    return result


def run(*rows):
    return merge(PLAN, list(rows), NICKNAMES, SUFFIXES)


class NormalizationTests(unittest.TestCase):
    def test_names_are_ascii_letters_only(self):
        for raw, expected in [("  michael ", "MICHAEL"), ("o'brien", "OBRIEN"),
                              ("Smith-Jones", "SMITHJONES"), ("Jr.", "JR"), (None, ""),
                              ("Émile 2", "MILE")]:
            with self.subTest(raw=raw):
                self.assertEqual(name(raw), expected)

    def test_postal_codes(self):
        for raw, expected in [(2134, "02134"), (2134.0, "02134"), ("02134-1102", "02134"),
                              (" 123 ", "00123"), ("12345", "12345"), ("N/A", None),
                              ("12", None), ("123456", None), (2134.5, None), (None, None),
                              ("１２３４５", None), (True, None)]:
            with self.subTest(raw=raw):
                self.assertEqual(zip5(raw), expected)

    def test_address_rules_are_literal(self):
        self.assertEqual(address("14, Maple Street.", SUFFIXES), ("14", "MAPLE ST"))
        self.assertEqual(address("14A Maple St", SUFFIXES), ("", ""))
        self.assertEqual(address("14", SUFFIXES), ("14", ""))
        self.assertEqual(address("014 Maple St", SUFFIXES), ("014", "MAPLE ST"))

    def test_units(self):
        for raw in ["Apt. 12b", "#12B", "SUITE 12 B", "Apartment 12B", "Unit 12B", "Ste 12B"]:
            self.assertEqual(unit(raw), "12B")
        self.assertEqual(unit("APT"), "")
        self.assertEqual(unit("APT12B"), "APT12B")


class GroupTests(unittest.TestCase):
    def test_worked_example_and_transitive_initial(self):
        result = run(record(11, "H", "Robert"), record(12, "A", "bob"),
                     record(13, "B", "R."), record(14, "B", "Mary"))
        self.assertEqual([r[0] for r in result.mail], [11, 14])
        self.assertEqual([r[-1] for r in result.mail], [0, 1])
        self.assertEqual(result.drops, [(12, "A", "DUP_INTER", 11), (13, "B", "DUP_INTER", 11)])

    def test_initial_uses_original_first_letter(self):
        a = normalize(record(1, first="R"), SUFFIXES)
        b = normalize(record(2, first="Bob"), SUFFIXES)
        self.assertFalse(duplicates(a, b, NICKNAMES))

    def test_suffix_conflict_and_empty_bridge(self):
        a, b = record(1, SUFFIX="JR"), record(2, SUFFIX="SR")
        self.assertEqual(len(run(a, b).mail), 2)
        result = run(a, b, record(3))
        self.assertEqual([r[0] for r in result.mail], [1])

    def test_blank_first_names_never_match(self):
        result = run(record(1, first=None), record(2, first=None), record(3, first="John"))
        self.assertEqual(len(result.mail), 3)

    def test_unit_zip_house_and_last_name_boundaries(self):
        result = run(record(1), record(2, ADDRESS_2="Apt 3"), record(3, ZIP="02135"),
                     record(4, ADDRESS_1="15 Maple Street"), record(5, LAST_NAME="Kings"))
        self.assertEqual(len(result.mail), 5)

    def test_equivalent_units_match(self):
        self.assertEqual(len(run(record(1, ADDRESS_2="Apt. 12b"), record(2, ADDRESS_2="#12B")).mail), 1)

    def test_priority_precedes_id_and_intra_is_relative_to_survivor(self):
        result = run(record(2, "A"), record(3, "A"), record(100, "H"))
        self.assertEqual(result.mail[0][0], 100)
        self.assertEqual(result.drops, [(2, "A", "DUP_INTER", 100), (3, "A", "DUP_INTER", 100)])

    def test_ties_use_numeric_id(self):
        result = run(record(10, "A"), record(2, "B"), record(3, "B"))
        self.assertEqual(result.mail[0][0], 2)
        self.assertEqual(result.drops, [(3, "B", "DUP_INTRA", 2), (10, "A", "DUP_INTER", 2)])
        self.assertEqual(result.mail[0][-1], 2)

    def test_multi_counts_distinct_lists_not_files_or_records(self):
        self.assertEqual(run(record(1, "A"), record(2, "C"), record(3, "A")).mail[0][-1], 1)
        self.assertEqual(run(record(1, "A"), record(2, "B"), record(3, "C")).mail[0][-1], 2)

    def test_suppression_is_transitive_and_precedes_survivor(self):
        result = run(record(1, "H", "Robert"), record(2, "A", "Bob"), record(3, "S", "R"))
        self.assertEqual(result.mail, [])
        self.assertEqual(result.drops, [(1, "H", "SUPPRESS", None), (2, "A", "SUPPRESS", None)])

    def test_suppress_can_bridge_otherwise_distinct_mail_records(self):
        result = run(record(1, first="John"), record(2, first="Jane"), record(3, "S", "J"))
        self.assertEqual(len(result.drops), 2)
        self.assertTrue(all(r[2] == "SUPPRESS" for r in result.drops))

    def test_invalid_mail_is_rejected_before_suppression(self):
        result = run(record(1, ZIP="N/A"), record(2, "S", ZIP="N/A"))
        self.assertEqual(result.drops, [(1, "A", "REJECT", None)])

    def test_invalid_suppression_is_ignored(self):
        result = run(record(1), record(2, "S", ADDRESS_1="No number"))
        self.assertEqual(len(result.mail), 1)
        self.assertEqual(result.drops, [])

    def test_each_validation_condition(self):
        for changes in [dict(LAST_NAME="---"), dict(ZIP="bad"), dict(ADDRESS_1="A14 Maple")]:
            self.assertEqual(run(record(1, **changes)).drops, [(1, "A", "REJECT", None)])

    def test_forbidden_fields_do_not_affect_matching(self):
        result = run(record(1), record(2, CUSTOMER_ID="different", EMAIL="different", PHONE="different",
                                     GENDER="different", CITY="different", STATE="different",
                                     LAST_ORDER_DATE=None, ORDER_TOTAL=0))
        self.assertEqual(len(result.mail), 1)

    def test_original_fields_preserved(self):
        row = record(1, first="  joHn ", ADDRESS_1="14 Maple Street.")
        self.assertEqual(run(row).mail[0][2:9], tuple(row[k] for k in
                         ["FIRST_NAME", "LAST_NAME", "SUFFIX", "ADDRESS_1", "ADDRESS_2", "CITY", "STATE"]))
        self.assertEqual(run(row).mail[0][-2], "02134")

    def test_empty_input_and_plan_order(self):
        result = run()
        self.assertEqual([r[0] for r in result.summary], ["H", "A", "B", "C", "TOTAL"])
        self.assertTrue(all(r[1:] == (0,) * 7 for r in result.summary))

    def test_input_order_does_not_affect_result(self):
        rows = [record(1, "H", "Robert"), record(2, "A", "Bob"), record(3, "B", "R"),
                record(4, "A", "Jane"), record(5, "B", "J"), record(6, "S", "John")]
        expected = run(*rows)
        rng = random.Random(42)
        for _ in range(30):
            rng.shuffle(rows)
            self.assertEqual(run(*rows), expected)

    def test_union_find_against_graph_traversal(self):
        # Independent graph traversal checks the grouping algorithm on random blocks.
        rng = random.Random(72)
        for _ in range(40):
            identities = [normalize(record(i, first=rng.choice(["John", "Jane", "J", "Bob", "Robert", "R", ""]),
                                           SUFFIX=rng.choice(["JR", "SR", ""]), ZIP=rng.choice([2134, 6103])),
                                    SUFFIXES) for i in range(25)]
            adjacency = {i: set() for i in range(len(identities))}
            for i, a in enumerate(identities):
                for j in range(i):
                    if duplicates(a, identities[j], NICKNAMES):
                        adjacency[i].add(j)
                        adjacency[j].add(i)
            unseen, expected = set(adjacency), set()
            while unseen:
                stack, group = [unseen.pop()], set()
                while stack:
                    node = stack.pop()
                    if node in group:
                        continue
                    group.add(node)
                    stack.extend(adjacency[node] - group)
                unseen -= group
                expected.add(frozenset(group))
            self.assertEqual({frozenset(g) for g in components(identities, NICKNAMES)}, expected)


if __name__ == "__main__":
    unittest.main()
