"""Human/LLM attribution shown in the app's About dialog and documented on disk."""

from __future__ import annotations

IMPLEMENTATION_MODEL = "DeepSeek V4.1 Flash"
MODEL_ID = "deepseek-ai/DeepSeek-V4.1-Flash"

ABOUT_TEXT = (
    "StreamStudy \u2014 experimental, made for playing around.\n\n"
    "Human-prompted, LLM-implemented.\n"
    f"The idea, requirements, reviews and corrections came from a human; the code, tests, "
    f"documentation and screenshots were written by {IMPLEMENTATION_MODEL} running in "
    "LM Studio Bionic, LM Studio's agentic coding harness.\n\n"
    "Data: USGS NWIS \u00b7 NWS \u00b7 Open-Meteo \u00b7 CoCoRaHS \u00b7 OpenStreetMap\n"
    "Not for flood safety, emergency planning or engineering decisions."
)
