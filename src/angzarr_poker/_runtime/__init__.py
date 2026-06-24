"""Self-contained service runtime for the poker example.

The example owns its own gRPC server bootstrap and logging setup — it depends
only on the reframed ``io.angzarr.v1`` generated code (``angzarr_poker._gen``)
and the ``angzarr_router_ffi`` FFI core, with no external client library.
"""
