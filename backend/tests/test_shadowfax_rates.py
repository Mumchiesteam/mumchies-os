from app.services.shadowfax_rates import bengaluru_origin_rate


def test_bengaluru_origin_rate_card_zones_include_gst() -> None:
    assert bengaluru_origin_rate("Karnataka", "Bengaluru").including_gst == 46.02
    assert bengaluru_origin_rate("Karnataka", "Mysuru").including_gst == 57.82
    assert bengaluru_origin_rate("Maharashtra", "Mumbai").including_gst == 69.62
    assert bengaluru_origin_rate("Assam", "Guwahati").including_gst == 81.42


def test_special_zone_is_classified_before_general_india() -> None:
    estimate = bengaluru_origin_rate("Jammu & Kashmir", "Srinagar")
    assert estimate is not None
    assert (estimate.zone, estimate.base_rate, estimate.including_gst) == ("Zone E", 69.0, 81.42)


def test_ambiguous_destination_has_no_rate_estimate() -> None:
    assert bengaluru_origin_rate("Karnataka", "") is None
    assert bengaluru_origin_rate("", "Bengaluru") is None
    assert bengaluru_origin_rate("Unknown", "Anywhere") is None
