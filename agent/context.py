"""Lightweight semantic context hints for BIRD-style text-to-SQL.

No extra LLM calls. These hints are appended to the schema prompt.
"""

from __future__ import annotations

from agent.schema import render_schema


GENERAL_HINTS = """
-- GENERAL SQL HINTS
-- Use single quotes for string literals, e.g. name = 'Alice'.
-- Use double quotes only for table/column identifiers when needed.
-- For exact timestamp filters, prefer LIKE 'YYYY-MM-DD HH:MM:SS%' because some DBs store fractional seconds.
-- If a JOIN can duplicate requested names/ids/coordinates/attributes, use DISTINCT.
-- If the question asks for full names and schema has first_name and last_name, return both columns separately.
-- If the question asks whether something is true/well-finished/mostly X or Y, return the requested label using CASE, GROUP BY, or ORDER BY COUNT as appropriate.
"""


DB_HINTS: dict[str, str] = {
    "toxicology": """
-- TOXICOLOGY HINTS
-- molecule.label is the carcinogenicity label. '+' means carcinogenic and '-' means non carcinogenic.
-- atom.element values are lowercase chemical symbols such as 'cl' and 'ca', not 'Chlorine' or 'Calcium'.
-- For "mostly carcinogenic or non carcinogenic", group by molecule.label and order by COUNT DESC LIMIT 1.
-- For percentages, use conditional aggregation. Be careful not to filter away the denominator unless the question says "among".
""",

    "formula_1": """
-- FORMULA 1 HINTS
-- fastestLapTime is usually text like M:SS.sss. Convert to seconds with:
-- CAST(SUBSTR(fastestLapTime, 1, INSTR(fastestLapTime, ':') - 1) AS INTEGER) * 60
-- + CAST(SUBSTR(fastestLapTime, INSTR(fastestLapTime, ':') + 1) AS REAL)
-- If the question asks for the time of the fastest lap record, return lapTimes.time, not MIN(milliseconds).
-- For "disqualified", statusId = 2 is often the intended status in results.
-- If the question says from race no. X to Y, prefer raceId > X AND raceId < Y unless inclusive is explicit.
""",

    "california_schools": """
-- CALIFORNIA SCHOOLS HINTS
-- Excellence rate in SAT scores is NumGE1500 / NumTstTakr.
-- Reading score is usually satscores.AvgScrRead.
-- If asking for the district/school with highest score, order by the score column and LIMIT 1; do not AVG unless grouping is explicitly requested.
""",

    "financial": """
-- FINANCIAL HINTS
-- district.A15 is crimes committed in 1995.
-- district.A14 is a different crime-year field, not 1995.
-- account.date is a date string; use STRFTIME('%Y', account.date) for year filters.
""",

    "thrombosis_prediction": """
-- THROMBOSIS HINTS
-- Normal Ig G level means Laboratory.IGG BETWEEN 900 AND 2000.
-- Normal uric acid UA depends on sex: female UA < 6.5, male UA < 8.0.
-- Outpatient clinic admission is represented by Patient.Admission = '-'.
-- Normal total blood bilirubin T-BIL means Laboratory."T-BIL" < 2.0.
-- October 1991 dates can be matched with Laboratory.Date LIKE '1991-10-%'.
""",

    "codebase_community": """
-- CODEBASE COMMUNITY HINTS
-- Timestamp columns often include a trailing fractional second like '.0'. Use LIKE 'YYYY-MM-DD HH:MM:SS%' for exact timestamp questions.
-- A post is well-finished if posts.ClosedDate IS NOT NULL; otherwise it is NOT well-finished.
-- Popularity is usually based on ViewCount. For popularity by user, group by user/display name and order by SUM(posts.ViewCount) DESC.
""",

    "card_games": """
-- CARD GAMES HINTS
-- legalities.format values are lowercase, e.g. 'gladiator'.
-- legalities.status values may be capitalized, e.g. 'Banned'.
-- If the question asks for print cards, return cards.id unless it explicitly asks for names.
-- "Originally printed" usually refers to cards.originalType and should exclude NULL originalType.
""",

    "student_club": """
-- STUDENT CLUB HINTS
-- Department names may include the word 'Department', e.g. 'Art and Design Department'.
-- If the question asks for full names, return first_name and last_name as separate columns unless a full_name column exists.
""",

    "superhero": """
-- SUPERHERO HINTS
-- Missing weight data may be represented by weight_kg = 0 OR weight_kg IS NULL.
-- Use the colour table for eye colors instead of assuming NULL means no color.
""",
}


def render_context(db_id: str, question: str) -> str:
    parts = [
        render_schema(db_id),
        GENERAL_HINTS,
        DB_HINTS.get(db_id, ""),
    ]
    return "\n".join(p for p in parts if p.strip())
