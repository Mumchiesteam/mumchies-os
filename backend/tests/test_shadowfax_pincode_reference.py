import json

from app.services import shadowfax_pincode_reference as reference


def test_reference_dataset_has_expected_shape_and_regression_pincode():
    payload = json.loads(reference.DATA_FILE.read_text(encoding="utf-8"))
    assert len(payload) == 13_875
    assert all(len(pincode) == 6 and pincode.isdigit() for pincode in payload)
    assert {row[2] for row in payload.values()} == {"Super Confident", "Confident"}
    assert reference.shadowfax_pincode_recommendation("123001") == {
        "pincode": "123001", "hub": "NNL_Narnaul", "region": "Haryana",
        "confidence": "Super Confident", "reference_only": True,
    }


def test_confident_absent_blank_and_malformed_pincodes():
    assert reference.shadowfax_pincode_recommendation("100191")["confidence"] == "Confident"
    assert reference.shadowfax_pincode_recommendation("999999") is None
    assert reference.shadowfax_pincode_recommendation("") is None
    assert reference.shadowfax_pincode_recommendation(None) is None
    assert reference.shadowfax_pincode_recommendation("12345") is None
    assert reference.shadowfax_pincode_recommendation("12300A") is None


def test_reference_file_is_loaded_once_not_per_lookup(monkeypatch):
    reference._reference_data.cache_clear()
    assert reference.shadowfax_pincode_recommendation("123001") is not None
    monkeypatch.setattr(type(reference.DATA_FILE), "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("dataset reopened")))
    assert reference.shadowfax_pincode_recommendation("100191") is not None
    assert reference._reference_data.cache_info().hits >= 1
