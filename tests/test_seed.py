import sys

from agent.config import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "tools"))
from seed_demo import seed  # noqa: E402


def test_seed_loads_confirmed_demo_and_respects_existing(store):
    r = seed(store)
    assert len(r["requirements"]["added"]) == 32 and r["criteria_confirmed"] == 32
    assert r["reports_seeded"] == 11
    assert all(x["criteria_state"] == "confirmed" for x in store.list_requirements())
    statuses = [x["status"] for x in store.list_requirements()]
    assert (statuses.count("완료"), statuses.count("부분완료"), statuses.count("미착수")) == (22, 2, 8)

    again = seed(store)
    assert again["criteria_confirmed"] == 0 and len(again["criteria_skipped"]) == 32
    assert again["reports_seeded"] == 0 and store.counts()["reports"] == 11
    forced = seed(store, force=True)
    assert forced["criteria_confirmed"] == 32 and store.counts()["reports"] == 11
