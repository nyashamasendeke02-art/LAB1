import sqlite3

import pytest

from autolab.store import ArtifactStore, ChainError, FrozenRecordError, Store, StoreError


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "lab.db")
    yield s
    s.close()


def test_ids_are_sequential_and_immutable(store):
    assert store.next_id("HYP") == "HYP-0001"
    assert store.next_id("HYP") == "HYP-0002"
    r = store.create("hypothesis", {"statement": "x"}, prefix="HYP")
    assert r.id == "HYP-0003"
    with pytest.raises(StoreError):
        store.create("hypothesis", {}, record_id="HYP-0003")


def test_update_creates_versions_and_requires_reason(store):
    r = store.create("hypothesis", {"statement": "a", "status": "active"}, prefix="HYP")
    with pytest.raises(StoreError):
        store.update(r.id, {"status": "x"}, reason="")
    store.update(r.id, {"status": "rejected"}, reason="data")
    hist = store.history(r.id)
    assert [h.version for h in hist] == [1, 2]
    assert hist[0].data["status"] == "active"  # old version preserved
    assert store.get(r.id).data["status"] == "rejected"


def test_frozen_records_only_change_by_recorded_amendment(store):
    r = store.create("protocol", {"seeds": [1, 2]}, prefix="PROT")
    f = store.freeze(r.id, author="controller", reason="prereg")
    assert f.frozen and f.data["_freeze_hash"]
    with pytest.raises(FrozenRecordError):
        store.update(r.id, {"seeds": [1]}, reason="drop a seed")
    with pytest.raises(StoreError):
        store.amend(r.id, {"seeds": [1]}, author="x", reason="")
    a = store.amend(r.id, {"seeds": [1, 2, 3]}, author="scientist", reason="power")
    assert a.data["_freeze_hash"] != f.data["_freeze_hash"]
    assert a.data["_amendments"][0]["reason"] == "power"
    assert store.events(subject=r.id, etype="record.amended")


def test_sql_level_append_only(store):
    store.create("x", {"a": 1}, record_id="X-1")
    with pytest.raises(sqlite3.DatabaseError):
        store._conn.execute("UPDATE records SET data='{}'")
    with pytest.raises(sqlite3.DatabaseError):
        store._conn.execute("DELETE FROM events")


def test_hash_chain_detects_tampering(tmp_path):
    s = Store(tmp_path / "lab.db")
    for i in range(5):
        s.append_event("controller", "t", f"S{i}", {"i": i})
    assert s.verify_chain() >= 5
    s._conn.execute("DROP TRIGGER events_no_update")
    s._conn.execute("UPDATE events SET data='{\"i\": 99}' WHERE seq=3")
    with pytest.raises(ChainError):
        s.verify_chain()
    s.close()


def test_record_tampering_detected(tmp_path):
    s = Store(tmp_path / "lab.db")
    s.create("result", {"effect": 1.0}, record_id="RES-1")
    s._conn.execute("DROP TRIGGER records_no_update")
    s._conn.execute("UPDATE records SET data='{\"effect\": 9.0}'")
    with pytest.raises(ChainError):
        s.verify_chain()
    s.close()


def test_transaction_rollback(store):
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.create("x", {}, record_id="X-9")
            raise RuntimeError
    assert not store.exists("X-9")


def test_artifacts_content_addressed(tmp_path):
    a = ArtifactStore(tmp_path / "art")
    d1 = a.put_text("raw data")
    assert a.put_text("raw data") == d1
    assert a.get_text(d1) == "raw data"
    p = a._path(d1)
    p.chmod(0o666)
    p.write_text("forged")
    with pytest.raises(ChainError):
        a.get_bytes(d1)
