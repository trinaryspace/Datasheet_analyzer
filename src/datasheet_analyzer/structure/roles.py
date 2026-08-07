"""Header role detection: map table headers to semantic roles.

Deterministic, ordered regex rules. Empty leading columns in parametric
TI tables are inferred from position (symbol/name/conditions) so that
tables whose HTML thead lost the PARAMETER colspan still classify correctly.
"""

from __future__ import annotations

import re

_ROLE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # ADI-style conditions headers measured in AD9081/HMC520A:
    # "Test Conditions/Comments" and footnote-suffixed variants
    (re.compile(r"(?i)^test conditions?(\s*/\s*comments?)?(\(\d+\))?$"), "conditions"),
    (re.compile(r"(?i)^(min|minimum)(\(\d+\))?$"), "min"),
    (re.compile(r"(?i)^(typ|typical)(\(\d+\))?$"), "typ"),
    (re.compile(r"(?i)^(nom|nominal)(\(\d+\))?$"), "typ"),
    (re.compile(r"(?i)^(max|maximum)(\(\d+\))?$"), "max"),
    (re.compile(r"(?i)^unit(s)?(\(\d+\))?$"), "unit"),
    # QPA1003P's 2-column value tables use "Value / Range" (measured on
    # page 2); TI's bare "VALUE" stays covered by the pattern above.
    (re.compile(r"(?i)^value(\s*/\s*range)?(\(\d+\))?$"), "value"),
    (re.compile(r"(?i)^parameter(\(\d+\))?$"), "parameter"),
    # thermal metric spans the symbol+name columns like a colspan PARAMETER
    (re.compile(r"(?i)^thermal metric(\(\d+\))?$"), "parameter"),
    (re.compile(r"(?i)^part number(\(\d+\))?$"), "symbol"),
    (re.compile(r"(?i)^package size(\(\d+\))?$"), "value"),
    (re.compile(r"(?i)^package(\(\d+\))?$"), "name"),
]

_NUMERIC_ROLES = {"min", "typ", "max", "value", "unit"}


def assign_roles(headers: list[str]) -> tuple[list[str], list[str]]:
    """Map header list to role list, returning (roles, unmapped_headers).

    Output roles: symbol, name, conditions, min, typ, max, value, unit, other.
    """
    prelim: list[str | None] = []
    unmapped_headers: list[str] = []
    for h in headers:
        h_stripped = h.strip()
        role: str | None = None
        for pat, r in _ROLE_PATTERNS:
            if pat.match(h_stripped):
                role = r
                break
        prelim.append(role)
        if role is None and h_stripped:
            unmapped_headers.append(h_stripped)

    # Expand PARAMETER/Thermal metric columns: first -> symbol, second -> name.
    param_count = 0
    roles: list[str] = []
    for role in prelim:
        if role == "parameter":
            param_count += 1
            if param_count == 1:
                roles.append("symbol")
            elif param_count == 2:
                roles.append("name")
            else:
                roles.append("other")
        else:
            roles.append(role or "other")

    # Infer empty leading columns in parametric-style tables from position.
    has_numeric = any(r in _NUMERIC_ROLES for r in roles)
    if has_numeric:
        try:
            first_numeric = next(i for i, r in enumerate(roles) if r in _NUMERIC_ROLES)
        except StopIteration:
            first_numeric = len(roles)
        empties = [
            i
            for i in range(first_numeric)
            if not headers[i].strip() and roles[i] == "other"
        ]
        inferred = ["symbol", "name", "conditions"]
        for idx, inferred_role in zip(empties, inferred):
            roles[idx] = inferred_role

        # If the table has a unit but no min/typ/max/value role, the column
        # immediately before the unit (with a name column somewhere to its
        # left) is the value column (e.g. 4.4 Thermal Information).
        if "unit" in roles and not ({"min", "typ", "max", "value"} & set(roles)):
            unit_idx = roles.index("unit")
            candidate = unit_idx - 1
            if (
                candidate >= 0
                and roles[candidate] == "other"
                and headers[candidate].strip()
                and "name" in roles[:candidate]
            ):
                roles[candidate] = "value"

    unmapped_headers = [
        headers[i].strip()
        for i, r in enumerate(roles)
        if r == "other" and headers[i].strip()
    ]
    return roles, unmapped_headers


def classify_table(headers: list[str], roles: list[str]) -> str:
    """Classify a table by its header roles."""
    has_name_symbol = any(r in {"symbol", "name"} for r in roles)
    has_numeric = any(r in {"min", "typ", "max", "value"} for r in roles)
    has_unit = "unit" in roles

    if has_name_symbol and has_numeric and has_unit:
        return "parametric"
    if has_name_symbol and not has_unit and not any(
        r in {"min", "typ", "max"} for r in roles
    ):
        return "info"
    return "unmapped"
