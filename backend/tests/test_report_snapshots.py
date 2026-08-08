from app.services import report_snapshots


def test_snapshot_preserves_last_success_when_refresh_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report_snapshots, "SNAPSHOT_FILE", tmp_path / "reports.json")

    report_snapshots.ReportSnapshotStore.save_success("reconciliation", {"missing_in_shiprocket": 41})
    report_snapshots.ReportSnapshotStore.save_error("reconciliation", "Shiprocket temporarily unavailable")
    snapshot = report_snapshots.ReportSnapshotStore.get("reconciliation")

    assert snapshot["data"] == {"missing_in_shiprocket": 41}
    assert snapshot["last_refreshed_at"]
    assert snapshot["refresh_error"] == "Shiprocket temporarily unavailable"
