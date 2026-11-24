from datetime import datetime, timedelta, timezone


def test_get_snapshot_by_id_time_and_latest(store):
    a = store.save_snapshot("sn-1", "p01_intake", {"step": 1})
    middle = datetime.now(timezone.utc)
    b = store.save_snapshot("sn-1", "p03_verification", {"step": 2})
    assert store.get_snapshot("sn-1")["id"] == b                                  # latest
    assert store.get_snapshot("sn-1", snapshot_id=a)["state"] == {"step": 1}      # by id
    assert store.get_snapshot("sn-1", at_or_before=middle)["id"] == a              # as it stood at a time
    assert store.get_snapshot("sn-1", at_or_before=middle - timedelta(days=1)) is None
    assert [s["agent"] for s in store.snapshots("sn-1")] == ["p01_intake", "p03_verification"]


def test_snapshots_are_per_session(store):
    store.save_snapshot("sn-a", "x", {"k": "a"})
    assert store.get_snapshot("sn-b") is None
