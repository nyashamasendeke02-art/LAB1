import pytest

from autolab.gates import GateError, Gates
from autolab.store import Store


def test_gate_lifecycle(tmp_path):
    s = Store(tmp_path / "db")
    g = Gates(s)
    a = g.request("protected_experiment", "PROT-1@v3", "run it")
    assert g.request("protected_experiment", "PROT-1@v3", "again").id == a.id  # no dupes
    assert [p.id for p in g.pending()] == [a.id]
    with pytest.raises(GateError):
        g.decide(a.id, True, by="scientist")  # agents cannot approve
    d = g.decide(a.id, True, by="human", note="ok")
    assert d.data["status"] == "approved"
    with pytest.raises(GateError):
        g.decide(a.id, False)
    assert s.events(subject=a.id, etype="gate.approved")
    s.close()
