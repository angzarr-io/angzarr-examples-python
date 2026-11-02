"""The player's composition root: ``__main__.py`` builds the logic and hands
it to the generated host's ``run``."""

from __future__ import annotations

import angzarr_player.__main__ as entry
from angzarr_player.logic_impl import PlayerLogicImpl


def test_main_runs_the_players_logic(monkeypatch):
    handed = []
    monkeypatch.setattr(entry, "run", handed.append)
    entry.main()
    [logic] = handed
    assert isinstance(logic, PlayerLogicImpl)
