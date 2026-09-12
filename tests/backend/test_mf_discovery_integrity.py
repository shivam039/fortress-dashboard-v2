import mf_lab.services.data as data


class _Response:
    def json(self):
        return [
            {"schemeCode": "1", "schemeName": "Example Direct Growth Large Cap Fund"},
            {"schemeCode": "2"},
            {"schemeCode": "3", "schemeName": "Example Direct Growth Liquid Fund"},
        ]


def test_discovery_skips_malformed_record_without_losing_valid_funds(monkeypatch):
    monkeypatch.setattr(data, "safe_api_get", lambda url: _Response())

    result = data.discover_funds()

    assert [row["schemeCode"] for row in result] == ["1", "3"]
