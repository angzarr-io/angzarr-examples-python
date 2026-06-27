"""Side-pot construction and odd-chip resolution for hand showdowns.

Pure functions over per-player contributions — no aggregate state, no protos — so
the same math serves the showdown-derivation steps today and any future award
handler. A "player" key is opaque (a root or a name); callers use whatever
identity they hold.

Side-pot construction (TDA Rule 21 / Robert's section 38): contributions are
sliced into bands at each distinct all-in level. A band that only one player
reached is uncontested and returned to them; otherwise it forms a pot whose
eligible winners are the band's non-folded contributors. Consecutive bands with
identical eligibility merge into one pot. The lowest band is the main pot; the
rest are side_1, side_2, … in ascending order.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Pot:
    """A contestable pot: its chip total, the set of players eligible to win it,
    and its label ("main", "side_1", …)."""

    amount: int
    eligible: set
    pot_type: str


def compute_side_pots(contributions):
    """Layer ``contributions`` — a list of ``(player, amount, folded)`` — into an
    ordered list of :class:`Pot` (main first) plus a ``{player: chips}`` map of
    uncontested chips returned to the over-bettor."""
    returned: dict = {}
    levels = sorted({amount for _, amount, _ in contributions if amount > 0})
    bands = []  # (amount, eligible frozenset) in ascending level order
    prev = 0
    for level in levels:
        slice_amount = level - prev
        contributors = [c for c in contributions if c[1] >= level]
        if len(contributors) == 1:
            # No opponent reached this band — the chips return, they do not pool.
            player = contributors[0][0]
            returned[player] = returned.get(player, 0) + slice_amount
        else:
            eligible = frozenset(p for p, _, folded in contributors if not folded)
            bands.append((slice_amount * len(contributors), eligible))
        prev = level

    # Merge consecutive bands that the same players contest.
    merged: list = []
    for amount, eligible in bands:
        if merged and merged[-1][1] == eligible:
            merged[-1] = (merged[-1][0] + amount, eligible)
        else:
            merged.append((amount, eligible))

    pots = [
        Pot(
            amount=amount,
            eligible=set(eligible),
            pot_type="main" if i == 0 else f"side_{i}",
        )
        for i, (amount, eligible) in enumerate(merged)
    ]
    return pots, returned


def split_with_odd_chip(amount, winners, odd_chip_index=0):
    """Split ``amount`` among ``winners`` (an ordered list): every winner gets the
    floor share and the remainder is handed out one chip at a time starting at
    ``odd_chip_index`` (TDA Rule 20 — the odd chip follows a defined order rather
    than landing arbitrarily). Returns ``{winner: chips}``."""
    n = len(winners)
    base, remainder = divmod(amount, n)
    result = {w: base for w in winners}
    for k in range(remainder):
        result[winners[(odd_chip_index + k) % n]] += 1
    return result
