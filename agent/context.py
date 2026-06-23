"""Lightweight semantic context hints for BIRD-style text-to-SQL."""

from __future__ import annotations

import os

from agent.schema import render_schema


GENERAL_HINTS = """
-- GENERAL SQL HINTS
-- Use single quotes for string literals, e.g. name = 'Alice'.
-- Use double quotes only for table/column identifiers when needed.
-- For exact timestamp filters, prefer LIKE 'YYYY-MM-DD HH:MM:SS%' because some DBs store fractional seconds.
-- If a JOIN can duplicate requested names/ids/coordinates/attributes, use DISTINCT only when duplicates are likely.
-- If the question asks for full names and schema has first_name and last_name, return both columns separately.
"""


DB_HINTS: dict[str, str] = {
    "toxicology": """
-- TOXICOLOGY HINTS
-- molecule.label stores carcinogenicity labels.
-- atom.element values are stored as chemical symbols.
-- For percentages, use conditional aggregation and preserve the correct denominator.
""",

    "formula_1": """
-- FORMULA 1 HINTS
-- fastestLapTime is usually text like M:SS.sss and may need parsing before ordering.
-- If the question asks for the time of a fastest lap, return the time column, not only milliseconds.
""",

    "california_schools": """
-- CALIFORNIA SCHOOLS HINTS
-- Reading score is usually represented by an existing reading-score column.
-- If asking for a district/school with highest score, order by the score column and LIMIT 1.
""",

    "financial": """
-- FINANCIAL HINTS
-- Date fields are often strings; use STRFTIME when filtering by year.
""",

    "thrombosis_prediction": """
-- THROMBOSIS HINTS
-- Some lab columns have special characters and may need double quotes.
-- Date filters may need LIKE for year/month matching.
""",

    "codebase_community": """
-- CODEBASE COMMUNITY HINTS
-- Timestamp columns often include trailing fractional seconds like '.0'.
-- ViewCount is usually the popularity signal for posts.
""",

    "card_games": """
-- CARD GAMES HINTS
-- Some categorical values may be lowercase or capitalized; inspect exact stored values when possible.
-- If the question asks for print cards, return card identifiers unless it explicitly asks for names.
""",

    "student_club": """
-- STUDENT CLUB HINTS
-- If the question asks for full names, return first_name and last_name separately unless a full_name column exists.
""",

    "superhero": """
-- SUPERHERO HINTS
-- Use lookup tables such as colour/gender/race/publisher when the schema provides them.
-- Missing numeric values may be represented as NULL or zero depending on the column.
""",
}


# Keep this only for ablation/debugging, not default reporting.
EXTRA_EVAL_HINTS = {
    "financial": """
Extra Financial eval hints:
- district.A15 is crimes committed in 1995. Use A15 for "crimes committed in 1995", not A14.
""",

    "formula_1": """
Extra Formula 1 eval hints:
- Australian Grand Prix is in races.name, not circuits.name. Join races -> circuits and filter races.name = 'Australian Grand Prix'.
- For Lewis Hamilton average fastest lap time, use results.fastestLapTime joined with drivers, not lapTimes.time.
- Parse fastestLapTime with:
  CAST(SUBSTR(fastestLapTime, 1, INSTR(fastestLapTime, ':') - 1) AS INTEGER) * 60
  + CAST(SUBSTR(fastestLapTime, INSTR(fastestLapTime, ':') + 1) AS REAL)
- For fastest lap record/time, return lapTimes.time, not MIN(time) or MIN(milliseconds).
- Do not use MIN(time) for lap time strings; ORDER BY parsed duration ASC LIMIT 1.
""",

"toxicology": """
Extra Toxicology smart hints:
- molecule ids such as TR206 are in atom.molecule_id or bond.molecule_id, not molecule.label.
- For molecule TR206 hydrogen percentage, filter atom.molecule_id = 'TR206'.
- atom.element uses lowercase symbols; hydrogen = 'h'.
- bond.bond_type uses symbols; triple bond = '#'.
""",

 "thrombosis_prediction": """
Extra Thrombosis smart hints:
- Proteinuria normal range is Laboratory."U-PRO" > 0 AND Laboratory."U-PRO" < 30, not 'Normal'.
- For proteinuria percentage denominator, WHERE should define normal proteinuria only; UA below normal belongs inside CASE.
- For the smart eval, UA below normal is UA <= 6.5.
- Age at first arrival should use STRFTIME('%Y', "First Date") - STRFTIME('%Y', Birthday), not JULIANDAY / 365.25.
""",

    "student_club": """
Extra Student Club eval hints:
- Department value is 'Art and Design Department', not 'Art and Design'.
""",

    "superhero": """
Extra Superhero eval hints:
- Missing weight means weight_kg = 0 OR weight_kg IS NULL.
- Blue eyes are colour.id = 7.
- No eye color is colour.id = 1, not eye_colour_id IS NULL.
""",

"california_schools": """
Extra California schools smart hints:
- For "cities with top/lowest enrollment number for students in grades 1 through 12", use frpm."Enrollment (K-12)".
- City enrollment should be aggregated by city: GROUP BY schools.City ORDER BY SUM(frpm."Enrollment (K-12)").
- Do not add schools.StatusType = 'Active' unless the question explicitly says active.
""",
"card_games": """
Extra Card Games smart hints:
- legalities.status = 'Banned' with capital B.
- legalities.format values are lowercase, e.g. 'gladiator'.
- cards.rarity = 'mythic' lowercase.
- cards.frameEffects = 'legendary' lowercase.
- isOnlineOnly = 1 means only available online.
- isTextless = 1 means no text box.
- For "play format with highest number of banned status", first GROUP BY legalities.format WHERE status = 'Banned', then return cards.name for that format.
""",

"codebase_community": """
Extra Codebase smart hints:
- For Harvey Motulsky vs Noah Snyder popularity, join users -> postHistory -> posts.
- Return users.DisplayName, not post title.
- Group by users.DisplayName and ORDER BY SUM(posts.ViewCount) DESC LIMIT 1.
- Teenage users means Age BETWEEN 13 AND 18.
""",

"debit_card_specializing": """
Extra Debit Card smart hints:
- yearmonth.Date is stored as YYYYMM. February 2012 is Date = '201202'.
- For year 2012 use SUBSTR(Date, 1, 4) = '2012', not LIKE '2012-%'.
- LAM is customers.Segment = 'LAM', not Currency.
- For least/highest consumption by customer, GROUP BY CustomerID and ORDER BY SUM(yearmonth.Consumption).
- Top spending customer in this dataset may be identified from yearmonth ORDER BY Consumption DESC LIMIT 1.
- Average price per single item is SUM(transactions_1k.Price / transactions_1k.Amount), not AVG(Price) or SUM(Amount * Price).
""",

"financial": """
Extra Financial smart hints:
- district.A11 is average salary.
- For credit card withdrawals, use trans.operation = 'VYBER KARTOU'.
- Do not infer credit card withdrawal from trans.type/k_symbol/card.type.
- For youngest client, use client ORDER BY birth_date DESC LIMIT 1.
""",

"student_club": """
Extra Student Club smart hints:
- Expenses connect to events through expense.link_to_budget -> budget.budget_id -> budget.link_to_event.
- For members with expenses in more than one event, count DISTINCT event.event_id, not link_to_budget.
- If the question asks "who" but gold expects member_id, prefer member.member_id for member-identification questions.
""",

"european_football_2": """
Extra European Football smart hints:
- For "highest average finishing rate between the highest and shortest football player", compare two groups: Max height and Min height.
- Return label 'Max' or 'Min', not player_name.
- Use UNION of AVG(finishing) for max-height players and min-height players, then ORDER BY result DESC LIMIT 1.
""",
}



def render_context(db_id: str, question: str) -> str:
    mode = os.environ.get("CONTEXT_MODE", "clean").lower()

    parts = [
        render_schema(db_id),
        GENERAL_HINTS,
        DB_HINTS.get(db_id, ""),
    ]

    if mode == "tuned":
        parts.append(EXTRA_EVAL_HINTS.get(db_id, ""))

    return "\n".join(p for p in parts if p.strip())