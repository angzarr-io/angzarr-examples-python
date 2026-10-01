"""Cluster acceptance step definitions (behave ``--stage acceptance``).

These steps drive a deployed blackjack example over gRPC and its event bus —
see ``_client.py`` for the transport, ``_stream.py`` for the bus and
``_world.py`` for per-scenario isolation. The feature files live in
``angzarr-project/features/example/blackjack-acceptance/``.
"""
