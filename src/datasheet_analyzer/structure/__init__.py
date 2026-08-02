"""Structure stage: raw extracted HTML/text -> refined, atomic corpus blocks."""

from datasheet_analyzer.structure.boilerplate import strip_boilerplate
from datasheet_analyzer.structure.corpus import build_section_plans
from datasheet_analyzer.structure.footnotes import attach_footnotes
from datasheet_analyzer.structure.tables import html_table_to_block

__all__ = [
    "attach_footnotes",
    "build_section_plans",
    "html_table_to_block",
    "strip_boilerplate",
]
