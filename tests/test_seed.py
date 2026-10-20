import sys

from agent.config import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "tools"))
from seed_demo import seed  # noqa: E402


def test_seed_loads_confirmed_demo_and_respects_existing(store):
    r = seed(store)
    assert len(r["requirements"]["added"]) == 29 and r["criteria_confirmed"] == 29
    assert all(x["criteria_state"] == "confirmed" for x in store.list_requirements())

    again = seed(store)
    assert again["criteria_confirmed"] == 0 and len(again["criteria_skipped"]) == 29
    assert seed(store, force=True)["criteria_confirmed"] == 29
