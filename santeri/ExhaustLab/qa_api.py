"""Check the running local API against the recorded physics and budget semantics."""
import json
import time
import urllib.error
import urllib.request


def get_study():
    return json.load(urllib.request.urlopen("http://127.0.0.1:8003/api/study", timeout=90))


def evaluate(body):
    request = urllib.request.Request("http://127.0.0.1:8003/api/evaluate",
              data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(request, timeout=90))


if __name__ == "__main__":
    start = time.monotonic()
    nominal = get_study()
    assert len(nominal["cases"]) == 3
    for case in nominal["cases"]:
        assert case["validation"]["passed"] and case["provenance"]["case"].endswith("fine")
        assert abs(case["capture_fraction"] + case["outlet_fraction"] + case["unresolved_fraction"] - 1) < 1e-12
        assert case["unresolved_fraction"] == 0 and case["pressure_drop_pa"] > 0
    print("Nominal study seconds:", round(time.monotonic()-start, 2))
    print([{key: case[key] for key in ("case", "capture_fraction", "pressure_drop_pa", "unresolved_fraction")}
           for case in nominal["cases"]])
    budget = evaluate({"costs": {"gap4": 100, "gap6": 50, "gap8": 25},
                       "budget_eur": 60, "supply_power_w": 1, "power_budget_w": 2})
    assert [case["within_budget"] for case in budget["cases"]] == [False, True, True]
    zero = evaluate({"charge_e": 0})
    assert all(case["capture_fraction"] == 0 and case["outlet_fraction"] > .99 for case in zero["cases"])
    try:
        evaluate({"charge_e": 61})
        raise AssertionError("Out-of-envelope input should fail")
    except urllib.error.HTTPError as error:
        assert error.code == 400
    print("PASS: genuine fine sources, fate accounting, budget checks, zero charge and input bounds")
