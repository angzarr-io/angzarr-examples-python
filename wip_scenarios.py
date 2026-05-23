"""Scenarios that resolve to TODO-stub matchers and are skipped.

This list replaces the @wip gherkin tags we previously baked into
angzarr-project's .feature files. The skip policy belongs in the
harness (it is a statement about *this language's* implementation
state), not in the spec.

Sourced from the post-cucumber-rewrite audit
(/tmp/python_broken.txt union of behave parse_behave.py). Lookup
is by (feature_basename, scenario_name) so a name re-used across
features stays unambiguous. Scenario Outline rows collapse to the
parent outline name.

Un-skip a scenario by removing its entry once its step matchers
are no longer TODO stubs. There is no need to touch the .feature
file. Add entries here when new scenarios surface as broken in
audit output rather than tagging @wip in gherkin.
"""

WIP_SCENARIOS: set[tuple[str, str]] = {
    # TDA Rule 11D scenarios — their matcher impls (BalanceTables,
    # CombineFinalTable, BlindDodgePenalty in unit_steps/table_steps.py)
    # were keyed to the pre-rewrite tech-vocab phrasing. The
    # table.feature rewrite (5cec3c0) changed the steps to business
    # vocab; the matchers need their decorator regex updated to follow.
    (
        "table.feature",
        "Balancing moves the BB-next player from the larger table to the worst seat at the shorter table",
    ),
    (
        "table.feature",
        "Final-table combination — 9-handed event collapses 2 tables of 5 to one final table of 9",
    ),
    (
        "table.feature",
        "Broken-table player can take any seat except between SB and button",
    ),
    (
        "table.feature",
        "A player who skips a blind by moving forfeits the missed blinds and earns a round penalty",
    ),
    (
        "table.feature",
        "8-handed event combines 2 tables of 4 and 5 to a final table of 9 then 8",
    ),
    ("table.feature", "6-handed event combines at 7 remaining"),
    ("cluster.feature", "A cross-domain request reaches the correct service"),
    ("cluster.feature", "Cross-service saga propagates within realistic bound"),
    ("cluster.feature", "Player display reflects a deposit within bound"),
    ("cluster.feature", "Player state survives a service restart"),
    ("cluster.feature", "Smoke end-to-end hand completes across services"),
    (
        "cluster_tournament.feature",
        "Bubble triggers hand-for-hand play across all active tables",
    ),
    (
        "cluster_tournament.feature",
        "Color-up at level transition removes low-denom chips from every stack",
    ),
    (
        "cluster_tournament.feature",
        "Full-lifecycle complex tournament across every code path",
    ),
    (
        "cluster_tournament.feature",
        "Table balancing moves a player when one table is short",
    ),
    (
        "cluster_tournament.feature",
        "Three-player tournament with blind advance, rebuy, and eliminations",
    ),
    ("cluster_tournament.feature", "Two-player tournament completes after one hand"),
    (
        "hand.feature",
        "4-card flop - scramble all four, randomly select burn, remaining 3 = flop",
    ),
    ("hand.feature", "7th-street showdown order - high hand showing tables first"),
    (
        "hand.feature",
        "A folded player's contributions stay in the pot they were already part of",
    ),
    (
        "hand.feature",
        "All-in for less than min-raise does not create a side pot when only one other caller remains",
    ),
    (
        "hand.feature",
        "An uncontested over-bet by the deepest stack is returned, not pooled",
    ),
    ("hand.feature", "Ante contributes to the main pot for side-pot accounting"),
    ("hand.feature", "Awarding the pot completes the hand"),
    ("hand.feature", "Completing a multi-pot award lists every winner across pots"),
    ("hand.feature", "Deal Five Card Draw hand to 4 players"),
    ("hand.feature", "Deal Omaha hand to 3 players"),
    ("hand.feature", "Deal Texas Hold'em hand to 2 players"),
    ("hand.feature", "Deal the river"),
    ("hand.feature", "Deal the turn"),
    (
        "hand.feature",
        "Deterministic deal produces identical hole cards for the same seed",
    ),
    ("hand.feature", "Disordered stub triggers reshuffle of the remaining stub"),
    (
        "hand.feature",
        "Exposing cards with action pending earns a penalty and the hand stays live",
    ),
    ("hand.feature", "Folded players are excluded from the showdown order"),
    (
        "hand.feature",
        "Fouled deck - duplicate (rank, suit) found at any time returns all bets",
    ),
    ("hand.feature", "Four-way all-in produces a main pot and two distinct side pots"),
    ("hand.feature", "Full house beats flush"),
    (
        "hand.feature",
        "HORSE button shifts when game type changes from flop game to stud",
    ),
    ("hand.feature", "Hand ending early does not reveal the unburned community cards"),
    (
        "hand.feature",
        "Hidden chip discovered after a call to all-in is not in play this hand",
    ),
    ("hand.feature", "High card comparison with kickers"),
    (
        "hand.feature",
        "Incorrect button movement after substantial action stands for the rest of the hand",
    ),
    ("hand.feature", "Invalid bet declaration outcomes"),
    ("hand.feature", "Kicker determines winner with matching pairs"),
    ("hand.feature", "Last aggressor on the river shows cards first"),
    (
        "hand.feature",
        "Level change during dealer push - incoming dealer deals one hand at the prior level",
    ),
    ("hand.feature", "Limit - at most 1 bet and 4 raises per round until heads-up"),
    (
        "hand.feature",
        "Limit - short all-in of at least 50% of a full bet reopens betting",
    ),
    (
        "hand.feature",
        "Misdeal triggers - pre-SA, hand is redealt; post-SA, hand stands",
    ),
    ("hand.feature", "Mucked-while-still-claiming - uncalled raise is refunded"),
    (
        "hand.feature",
        "No-burn 3-card flop after action - flop stands, no extra burn for the turn",
    ),
    (
        "hand.feature",
        "No-burn 3-card flop pre-action - scramble flop, one becomes burn, complete flop from stub",
    ),
    (
        "hand.feature",
        "Non-standard bet declaration is ruled by the floor with player at risk",
    ),
    (
        "hand.feature",
        "Odd-chip H/L split - extra chip in the total pot goes to the high side",
    ),
    (
        "hand.feature",
        "Odd-chip split awards the extra chip to first seat clockwise of the button",
    ),
    (
        "hand.feature",
        "PL high (illegal) underbet is corrected for all players anywhere on the current street",
    ),
    (
        "hand.feature",
        "PLO pre-flop pot calculation assumes full blinds even with a short SB",
    ),
    (
        "hand.feature",
        "Premature flop - burn stays, premature flop returns to stub, reshuffle, re-deal without new burn",
    ),
    (
        "hand.feature",
        "Premature river - burn stays, premature card returns, reshuffle, re-deal without new burn",
    ),
    (
        "hand.feature",
        "Premature turn - burn stays, premature card returns, reshuffle, re-deal without new burn",
    ),
    (
        "hand.feature",
        "RP-10A - downcard exposed on initial deal becomes the player's upcard",
    ),
    (
        "hand.feature",
        "RP-10B - exposed 7th-street card is replaced when betting action remains",
    ),
    (
        "hand.feature",
        "RP-10E - bring-in player all-in for the ante: betting starts to their left",
    ),
    (
        "hand.feature",
        "RP-10F - open pair on 4th street does NOT enable a doubled bet (TDA standard)",
    ),
    (
        "hand.feature",
        "RP-10G / RP-5D - premature card in stud returned to stub, reshuffled, no extra burn",
    ),
    (
        "hand.feature",
        "RP-10H sub-A - short stub: stub + prior burns reaches required count",
    ),
    (
        "hand.feature",
        "RP-10H sub-B - stub has >=3 but combining with burns is still short -> community card",
    ),
    (
        "hand.feature",
        "RP-10H sub-C - 7th-street short stub (<3 cards) becomes a community card",
    ),
    ("hand.feature", "Re-deal preserves the dealer button position and blind levels"),
    (
        "hand.feature",
        "Robert's RAZZ #3 - open pair on 4th street does not affect the limit (Razz only)",
    ),
    (
        "hand.feature",
        "Robert's SC Stud #18 - hand with too few or too many cards at showdown is dead",
    ),
    ("hand.feature", "Royal flush beats straight flush"),
    ("hand.feature", "Split pot when hands are identical"),
    ("hand.feature", "State with community cards"),
    ("hand.feature", "String bet - chips beyond the first forward motion are returned"),
    ("hand.feature", "Stub reshuffle mid-hand still burns exactly one card per street"),
    (
        "hand.feature",
        "Stud - exposed first or second downcard on initial deal is a misdeal",
    ),
    (
        "hand.feature",
        "Substantial Action threshold - pre-SA misdeals redeal, post-SA stand",
    ),
    (
        "hand.feature",
        "Three-way all-in at different stacks creates a main pot and one side pot",
    ),
    ("hand.feature", "Tied late-reg seat picks resolved by deterministic randomness"),
    ("hand.feature", "Two consecutive cards on the button are not a misdeal"),
    (
        "hand.feature",
        "Two cumulative short all-ins that together do not meet a full raise do not reopen",
    ),
    (
        "hand.feature",
        "Two cumulative short all-ins that together meet a full raise reopen the bet",
    ),
    (
        "hand.feature",
        "Underraise corrected on the same street before the next street is dealt",
    ),
    (
        "hand.feature",
        "Verbal undercall in turn is corrected up to the actual bet before SA",
    ),
    (
        "hand.feature",
        "Verbal undercall in turn stands at the lesser amount after substantial action",
    ),
    (
        "hand.feature",
        "WSOP - absent at 3rd-street completion forfeits ante and bring-in",
    ),
    (
        "hand.feature",
        "WSOP - all 3 first cards dealt face down: scramble, randomly turn one face up",
    ),
    (
        "hand.feature",
        "WSOP - bring-in completion to a full bet does not count as a raise",
    ),
    (
        "hand.feature",
        "WSOP - open pair on 4th street locks lower limit in Stud Hi/Lo and Razz",
    ),
    (
        "hand.feature",
        "With no river betting, the first seat clockwise of the dealer shows first",
    ),
    ("process_manager.feature", "Action passes to the next player after one acts"),
    ("process_manager.feature", "Post-flop action starts on the big blind in heads-up"),
    (
        "process_manager.feature",
        "Post-flop action starts on the first active seat left of the dealer (3-handed)",
    ),
    (
        "saga.feature",
        "A hand ending releases every participant, even those with no net change",
    ),
    ("saga.feature", "A hand ending with no participants releases nothing"),
    (
        "saga.feature",
        "When a hand ends, each participant's reserved chips are released",
    ),
    ("saga.feature", "When a hand finishes, the table is told to end the round"),
    ("saga.feature", "When a hand starts at a table, cards are dealt"),
    ("saga.feature", "When a pot is awarded, each winner's bankroll is credited"),
    (
        "table.feature",
        "A 2-player deficit does not trigger halt (below the 3-short threshold)",
    ),
    ("table.feature", "A halted table refuses StartHand until the coordinator resumes"),
    ("table.feature", "AddRebuyChips emits RebuyChipsAdded with new stack"),
    ("table.feature", "AddRebuyChips rejects a non-positive amount"),
    ("table.feature", "AddRebuyChips rejects when player_root is empty"),
    ("table.feature", "AddRebuyChips rejects when seat does not match"),
    ("table.feature", "AddRebuyChips rejects when the player is not seated"),
    ("table.feature", "AddRebuyChips rejects when the table does not exist"),
    (
        "table.feature",
        "BB busts — button stays put, BB skips to the next active seat (dead button)",
    ),
    ("table.feature", "Cannot create table twice"),
    ("table.feature", "Cannot end hand not in progress"),
    ("table.feature", "Cannot join full table"),
    ("table.feature", "Cannot join occupied seat"),
    ("table.feature", "Cannot join table twice"),
    ("table.feature", "Cannot join with insufficient buy-in"),
    ("table.feature", "Cannot leave during hand"),
    ("table.feature", "Cannot leave table not joined"),
    ("table.feature", "Cannot start hand while one is in progress"),
    ("table.feature", "Cannot start hand with fewer than 2 players"),
    ("table.feature", "ChipsAdded updates the player stack via re-buy"),
    ("table.feature", "Create a Five Card Draw table"),
    ("table.feature", "Create a Texas Hold'em table"),
    ("table.feature", "CreateTable rejects big_blind below small_blind"),
    ("table.feature", "CreateTable rejects max_buy_in below min_buy_in"),
    ("table.feature", "CreateTable rejects max_players above 10"),
    ("table.feature", "CreateTable rejects max_players below 2"),
    ("table.feature", "CreateTable rejects non-positive min_buy_in"),
    ("table.feature", "CreateTable rejects non-positive small_blind"),
    ("table.feature", "CreateTable rejects zero big_blind"),
    ("table.feature", "CreateTable requires a table_name"),
    ("table.feature", "Dealer button advances each hand"),
    ("table.feature", "End hand and update stacks"),
    ("table.feature", "End hand updates player stacks with wins and losses"),
    ("table.feature", "EndHand rejects mismatched hand_root"),
    ("table.feature", "EndHand rejects when table does not exist"),
    ("table.feature", "EndHand transitions status back to waiting"),
    ("table.feature", "Full create/join/start/end/leave lifecycle"),
    ("table.feature", "Halt comparator uses the largest table, not the average"),
    ("table.feature", "Halt re-arms after a previous resume if the deficit reopens"),
    (
        "table.feature",
        "Halted table resumes after the coordinator issues ResumePlayAtTable",
    ),
    (
        "table.feature",
        "Initial button placement on hand 1 starts at the seat to the dealer's right",
    ),
    ("table.feature", "JoinTable rejects occupied preferred seat"),
    ("table.feature", "JoinTable rejects when buy-in exceeds max"),
    ("table.feature", "JoinTable rejects when table does not exist"),
    ("table.feature", "JoinTable requires a player_root"),
    ("table.feature", "LeaveTable rejects when table does not exist"),
    ("table.feature", "LeaveTable requires a player_root"),
    ("table.feature", "Negative preferred_seat picks the next available seat"),
    (
        "table.feature",
        "No player pays the big blind twice in a row across an elimination",
    ),
    (
        "table.feature",
        "Play halts on a short table when 3+ behind once the blinds are impacted",
    ),
    ("table.feature", "Player joins table at any seat"),
    ("table.feature", "Player joins table at preferred seat"),
    ("table.feature", "Player leaves table"),
    ("table.feature", "PlayerSatIn restores a sat-out player to active"),
    ("table.feature", "Rebuild state during hand"),
    ("table.feature", "Rebuild state with multiple players"),
    ("table.feature", "SB busts — BB stays in place, button advances normally"),
    ("table.feature", "Seat 0 is an explicit valid preferred seat"),
    ("table.feature", "SeatPlayer emits PlayerSeated on success"),
    ("table.feature", "SeatPlayer emits SeatingRejected when amount exceeds maximum"),
    ("table.feature", "SeatPlayer emits SeatingRejected when amount is below minimum"),
    ("table.feature", "SeatPlayer emits SeatingRejected when player is already seated"),
    ("table.feature", "SeatPlayer emits SeatingRejected when player_root is empty"),
    (
        "table.feature",
        "SeatPlayer emits SeatingRejected when requested seat is occupied",
    ),
    ("table.feature", "SeatPlayer emits SeatingRejected when seat is out of range"),
    ("table.feature", "SeatPlayer rejects when the table does not exist"),
    ("table.feature", "SeatPlayer with seat -1 picks the next available seat"),
    ("table.feature", "SeatPlayer with seat -1 rejects when table is full"),
    ("table.feature", "Start a new hand"),
    ("table.feature", "StartHand in heads-up: dealer posts small blind"),
    ("table.feature", "StartHand rejects when table does not exist"),
    ("table.feature", "StartHand with 3 players: SB is left of dealer"),
    ("table.feature", "Table id is derived from the table name"),
    (
        "table.feature",
        "Three players collapse to heads-up — button advances, dealer is SB",
    ),
    (
        "table.feature",
        "Tournament seat assignment is uniformly random among available seats",
    ),
    ("table.feature", "active_player_count excludes sitting-out players"),
    ("table.feature", "is_full becomes true when max_players reached"),
    (
        "tournament.feature",
        "Late-reg player can be dealt the button on their first hand without missing the hand",
    ),
}
