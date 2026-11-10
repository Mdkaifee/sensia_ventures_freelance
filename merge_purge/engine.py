"""Apply group decisions and build the three prescribed output tables."""

from collections import Counter
from dataclasses import dataclass

from .matching import components
from .normalization import normalize

MAIL_COLUMNS = ("REC_ID", "KEY_CODE", "FIRST_NAME", "LAST_NAME", "SUFFIX", "ADDRESS_1",
                "ADDRESS_2", "CITY", "STATE", "ZIP5", "MULTI_COUNT")
DROP_COLUMNS = ("REC_ID", "KEY_CODE", "REASON", "SURVIVOR_REC_ID")
SUMMARY_COLUMNS = ("KEY_CODE", "INPUT", "REJECT", "SUPPRESS", "DUP_INTER", "DUP_INTRA", "NET", "MULTIS")


@dataclass
class Result:
    mail: list[tuple]
    drops: list[tuple]
    summary: list[tuple]


def merge(plan: list[dict], records: list[dict], nicknames: dict[str, str],
          suffixes: dict[str, str]) -> Result:
    files = {p["KEY_CODE"]: p for p in plan}
    counts = {key: Counter() for key, p in files.items() if p["TYPE"] != "Suppress"}
    valid_records, identities, drops, mail = [], [], [], []
    for row in records:
        key = row["KEY_CODE"]
        is_mail = files[key]["TYPE"] != "Suppress"
        if is_mail:
            counts[key]["INPUT"] += 1
        identity = normalize(row, suffixes)
        if not identity.valid:
            if is_mail:
                drops.append((row["REC_ID"], key, "REJECT", None))
                counts[key]["REJECT"] += 1
            continue
        valid_records.append(row)
        identities.append(identity)

    for indices in components(identities, nicknames):
        members = [valid_records[i] for i in indices]
        mailable = [r for r in members if files[r["KEY_CODE"]]["TYPE"] != "Suppress"]
        if any(files[r["KEY_CODE"]]["TYPE"] == "Suppress" for r in members):
            for row in mailable:
                drops.append((row["REC_ID"], row["KEY_CODE"], "SUPPRESS", None))
                counts[row["KEY_CODE"]]["SUPPRESS"] += 1
            continue
        survivor = min(mailable, key=lambda r: (files[r["KEY_CODE"]]["PRIORITY"], r["REC_ID"]))
        key = survivor["KEY_CODE"]
        multi_count = (len({files[r["KEY_CODE"]]["LIST"] for r in mailable
                            if files[r["KEY_CODE"]]["TYPE"] == "Outside"})
                       if files[key]["TYPE"] == "Outside" else 0)
        # All members share the exact address/ZIP block, including via transitivity.
        postal = identities[indices[0]].postal
        mail.append(tuple(survivor[c] for c in MAIL_COLUMNS[:-2]) + (postal, multi_count))
        counts[key]["NET"] += 1
        counts[key]["MULTIS"] += int(multi_count >= 2)
        for row in mailable:
            if row["REC_ID"] == survivor["REC_ID"]:
                continue
            reason = "DUP_INTRA" if row["KEY_CODE"] == key else "DUP_INTER"
            drops.append((row["REC_ID"], row["KEY_CODE"], reason, survivor["REC_ID"]))
            counts[row["KEY_CODE"]][reason] += 1

    summary = [(key,) + tuple(c[col] for col in SUMMARY_COLUMNS[1:]) for key, c in counts.items()]
    summary.append(("TOTAL",) + tuple(sum(row[i] for row in summary) for i in range(1, 8)))
    for row in summary:
        if row[1] != sum(row[2:7]):
            raise RuntimeError(f"Summary does not balance for {row[0]}")
    return Result(sorted(mail), sorted(drops), summary)
