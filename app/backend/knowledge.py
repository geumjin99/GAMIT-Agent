"""Assemble the skill/references/*.md knowledge base into the agent system prompt.

The knowledge core (GAMIT control-file schema / workflow / error catalogue / QC interpretation)
was empirically calibrated during the Skill phase and is reused here as-is -- this is exactly how
"the Skill work is not wasted": it becomes the domain brain of the DeepSeek agent.
"""
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent      # .../GAMITagent
REF_DIR = REPO_DIR / "skill" / "references"

# the two most relevant for diagnosis/self-correction (in practice these two suffice to judge class A/D/C)
_DIAGNOSTIC = ["errors.md", "workflow.md"]
_FULL = ["control-files.md", "workflow.md", "errors.md", "qc.md"]


def load_references(names) -> str:
    parts = []
    for n in names:
        p = REF_DIR / n
        if p.is_file():
            parts.append(f"\n===== knowledge: {n} =====\n{p.read_text()}")
    return "\n".join(parts)


def diagnostic_knowledge() -> str:
    return load_references(_DIAGNOSTIC)


def full_knowledge() -> str:
    return load_references(_FULL)
