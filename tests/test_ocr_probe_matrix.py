from pathlib import Path

import pytest

from scripts.run_ocr_inplace_probe_matrix import ExpectedProbe, _resolve_probe_source


def test_probe_matrix_requires_real_sources_when_requested(tmp_path: Path) -> None:
    probe = ExpectedProbe(
        name="missing_real_probe",
        plan_path=tmp_path / "plan.json",
        source_pdf=tmp_path / "missing.pdf",
        expected_decisions={},
    )

    with pytest.raises(FileNotFoundError, match="--require-real-sources"):
        _resolve_probe_source(
            probe,
            {"pages": []},
            tmp_path,
            require_real_sources=True,
        )

