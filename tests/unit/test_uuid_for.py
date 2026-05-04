"""Cross-language byte-identity tests for the test-side uuid helpers.

Pinned hex values must equal the values produced by Rust's
``poker_tests::uuid_for(seed)`` and ``generate_hand_root(table_root, n)``.
Drift here means cucumber assertions that hardcode a hex value (e.g. on
``table_root_hex`` rejection details) would diverge across languages.
"""

from tests.helpers import generate_hand_root, uuid_for


def test_uuid_for_is_deterministic():
    assert uuid_for("alice") == uuid_for("alice")
    assert len(uuid_for("alice")) == 16


def test_uuid_for_differs_for_different_seeds():
    assert uuid_for("alice") != uuid_for("bob")


def test_uuid_for_matches_rust_uuid5_namespace_oid_table_1():
    # Rust counterpart: see tests/src/lib.rs::test_uuid_for_matches_python_uuid5_namespace_oid
    assert uuid_for("table-1").hex() == "eba6a19b488f5e1097a5a34a92553679"


def test_generate_hand_root_is_deterministic():
    table_root = uuid_for("test-table")
    a = generate_hand_root(table_root, 1)
    b = generate_hand_root(table_root, 1)
    assert a == b
    assert len(a) == 16


def test_generate_hand_root_differs_for_different_hand_numbers():
    table_root = uuid_for("test-table")
    assert generate_hand_root(table_root, 1) != generate_hand_root(table_root, 2)
