import edge


class FakeCloudflare:
    """Answers like the API from a dict of state, recording each write."""

    def __init__(self, phases=None, settings=None, r2_dev=True, fail=()):
        self.phases = phases or {}
        self.settings = settings or {}
        self.r2_dev = r2_dev
        self.fail = fail
        self.writes = []

    def call(self, method, path, body=None):
        if any(part in path for part in self.fail):
            raise edge.CloudflareError(f"{method} {path}: refused")
        if path.startswith("/zones?name="):
            return [{"id": "z1"}]
        if method != "GET":
            self.writes.append((method, path, body))
        if "/rulesets/phases/" in path:
            phase = path.split("/phases/")[1].split("/")[0]
            if method == "GET":
                return {"rules": self.phases[phase]} if phase in self.phases else None
            self.phases[phase] = body["rules"]
            return {}
        if path.endswith("/domains/managed"):
            if method == "GET":
                return {"enabled": self.r2_dev}
            self.r2_dev = body["enabled"]
            return {}
        if method == "GET":
            return {"value": self.settings.get(path, "off")}
        self.settings[path] = body["value"]
        return {}


def test_merge_keeps_other_rules_and_replaces_ours_in_place():
    ours = edge.desired_rules("data.example", 100)["http_request_firewall_custom"]
    other = {"id": "a", "ref": "hand-made", "expression": "true", "action": "block", "version": "3", "last_updated": "x"}
    stale = dict(ours, id="b", expression="(false)")
    rules, changed = edge.merge([other, stale], ours)
    assert changed
    assert rules[0] == {"id": "a", "ref": "hand-made", "expression": "true", "action": "block"}
    assert rules[1]["id"] == "b" and rules[1]["expression"] == ours["expression"]
    assert len(rules) == 2


def test_merge_reports_no_change_when_ours_is_current():
    ours = edge.desired_rules("data.example", 100)["http_ratelimit"]
    _, changed = edge.merge([dict(ours, id="r", version="1")], ours)
    assert not changed


def test_cache_rule_drops_the_query_string_from_the_cache_key():
    rule = edge.desired_rules("data.example", 100)["http_request_cache_settings"]
    assert rule["action_parameters"]["cache"] is True
    assert rule["action_parameters"]["cache_key"]["custom_key"]["query_string"] == {"exclude": {"all": True}}


def test_dry_run_writes_nothing():
    cf = FakeCloudflare()
    assert edge.configure(cf, "acct", 200, apply=False) == []
    assert cf.writes == []


def test_apply_sets_everything_and_a_second_run_is_a_no_op():
    cf = FakeCloudflare(phases={"http_request_firewall_custom": [{"id": "h", "ref": "mine", "expression": "true", "action": "block"}]})
    assert edge.configure(cf, "acct", 200, apply=True) == []
    assert [rule["ref"] for rule in cf.phases["http_request_firewall_custom"]] == ["mine", "mooligan-data-private"]
    assert set(cf.phases) == {"http_request_cache_settings", "http_request_firewall_custom", "http_ratelimit"}
    assert set(cf.settings.values()) == {"on"} and len(cf.settings) == 2
    assert cf.r2_dev is False
    cf.writes.clear()
    assert edge.configure(cf, "acct", 200, apply=True) == []
    assert cf.writes == []


def test_one_refused_step_does_not_stop_the_others():
    cf = FakeCloudflare(fail=("http_ratelimit",))
    errors = edge.configure(cf, "acct", 200, apply=True)
    assert len(errors) == 1 and errors[0].startswith("http_ratelimit")
    assert "http_request_cache_settings" in cf.phases and cf.r2_dev is False
