"""The contract does not pin `env list`'s output shape, and binaries diverge.

One answers with a list whose records carry `name`; another with a map keyed by
name whose values carry everything else. Both describe the same records, and the
picker must offer them either way — a host that understands only one shape shows
an empty dropdown for a binary that has environments, which reads as "there are
none" rather than "answered differently".
"""
from api.plugins import _as_named_list


class TestEnvironmentListingShape:
    def test_a_map_keyed_by_name_becomes_records_carrying_name(self):
        listed = _as_named_list({"e1": {"kind": "uat", "url": "https://h/v2/"}})
        assert listed == [{"name": "e1", "kind": "uat", "url": "https://h/v2/"}]

    def test_a_list_of_records_is_returned_unchanged(self):
        records = [{"name": "e1", "kind": "uat", "url": "https://h/v2/"}]
        assert _as_named_list(records) == records

    def test_both_shapes_normalise_to_the_same_records(self):
        as_map = _as_named_list({"e1": {"kind": "uat"}})
        as_list = _as_named_list([{"name": "e1", "kind": "uat"}])
        assert as_map == as_list

    def test_a_value_carrying_its_own_name_is_not_relabelled_by_its_key(self):
        # A binary keying a map by something other than the name must not have
        # its records silently renamed to the key.
        assert _as_named_list({"k": {"name": "real", "kind": "uat"}})[0]["name"] == "real"

    def test_a_shape_nobody_anticipated_yields_nothing_rather_than_raising(self):
        # The reported crash was .map() on an object. Whatever arrives, the
        # endpoint returns something the caller can iterate.
        for junk in ("nope", None, 7, [1, 2]):
            assert isinstance(_as_named_list(junk), list)

    def test_a_non_dict_member_of_a_map_still_produces_a_named_record(self):
        assert _as_named_list({"e1": "https://h/v2/"}) == [
            {"name": "e1", "value": "https://h/v2/"}
        ]
