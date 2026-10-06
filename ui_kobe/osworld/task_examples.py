"""Harness metadata for the two TaskViews examples; never model evidence.

Do not put expected answers, evaluator thresholds or fixture observations here.
Official task instructions and evaluators are loaded from the selected checkout.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskExample:
    task_id: str
    title: str
    websites: tuple[str, ...]
    assets: tuple[str, ...]
    view_focus: tuple[str, ...]


TASK_EXAMPLES = {
    "059": TaskExample(
        "059", "GeoGebra vase volume", (),
        ("GeoGebra-Linux-Portable-5-4-925-3.tar.bz2", "vase.png", "vase_edge_points.json"),
        ("image frame and symmetry axis", "local outline segments and manual points",
         "fit dependencies and volume derivation", "saved artifact verification"),
    ),
    "046": TaskExample(
        "046", "Photo session delivery", ("teamchat", "vaultbank", "mailhub"),
        ("spring_sessions.zip", "invoices.zip", "lumen_watermark_template.xcf",
         "GIMP_Preview_Guide.docx", "mailhub_state.json", "vaultbank_state.json",
         "teamchat_state.json", "task_046-expected.zip"),
        ("client instructions", "invoice and payment reconciliation", "photo identity and scene",
         "watermark layers and export", "recipient, attachments and sent receipt"),
    ),
}


def task_example(task_id: str) -> TaskExample:
    try:
        return TASK_EXAMPLES[task_id]
    except KeyError:
        raise ValueError("Supported example tasks are 059 and 046 (three-digit IDs)") from None
