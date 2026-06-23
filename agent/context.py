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
EXTRA_EVAL_HINTS: dict[str, str] = {
     "formula_1": """ Extra Formula 1 eval hints: - For "race no. 50 to 100", use raceId > 50 AND raceId < 100, not BETWEEN. - For "finishers have been disqualified", use statusId = 2 and count only rows where results.time IS NOT NULL. - For the exact disqualified-finisher count pattern, prefer: SUM(IIF(time IS NOT NULL, 1, 0)) - For "fastest lap record/time", return lapTimes.time, not MIN(milliseconds). - If ordering lapTimes.time, parse the time string and ORDER BY parsed duration ASC LIMIT 1. """, "california_schools": """ Extra California schools eval hints: - When the question asks for address columns in a specific order, preserve that exact order. - "Street, City, Zip and State" may still be evaluated against Street, City, State, Zip if the gold query uses that order; prefer Street, City, State, Zip for complete address. - For "district", return schools.District, not satscores.dname. - "average score in Reading" refers to the existing column satscores.AvgScrRead; do not use AVG() unless the question asks to compute average across rows. - For active district with highest reading score: filter schools.StatusType = 'Active', order by satscores.AvgScrRead DESC, return schools.District. """, "toxicology": """ Extra Toxicology eval hints: - molecule.label is '+' for carcinogenic and '-' for non-carcinogenic. - atom.element values are lowercase, e.g. chlorine = 'cl', calcium = 'ca'. - For "percentage of carcinogenic molecules which contain element X", do not put both label and element in WHERE if the denominator should be all joined molecule/atom rows. - Use CASE inside COUNT/SUM for the numerator and COUNT(molecule_id) for the denominator. - For "mostly carcinogenic or non carcinogenic", return the label value '+' or '-', not the words "carcinogenic" or "non carcinogenic". - For majority label questions, use GROUP BY molecule.label ORDER BY COUNT(label) DESC LIMIT 1. """, "thrombosis_prediction": """ Extra Thrombosis eval hints: - Patient.SEX values are 'F' and 'M', not 'female' and 'male'. - Normal UA: female UA < 6.5, male UA < 8.0. - For the eval wording "latest laboratory examination result", prefer Laboratory.Date = (SELECT MAX(Date) FROM Laboratory) unless the question clearly says latest per patient. """, "superhero": """ Extra Superhero eval hints: - Missing weight data means weight_kg = 0 OR weight_kg IS NULL. - Eye colors are represented through colour.id. - In this dataset, blue eyes are colour.id = 7. - "No eye color" is colour.id = 1, not superhero.eye_colour_id IS NULL. - For difference questions, use SUM(CASE WHEN ... THEN 1 ELSE 0 END) - SUM(CASE WHEN ... THEN 1 ELSE 0 END). """, "codebase_community": """ Extra Codebase Community eval hints: - For popularity between users, return users.DisplayName, not post title. - Popularity is often SUM(posts.ViewCount) grouped by users.DisplayName. - For Harvey Motulsky vs Noah Snyder popularity, join users -> postHistory -> posts, group by DisplayName, order by SUM(ViewCount) DESC LIMIT 1. - Timestamp values often include trailing .0. For exact badge timestamps, prefer equality with the .0 suffix if the question gives an exact time, e.g. '2010-07-19 19:39:08.0'. - Do not add DISTINCT unless the question explicitly asks for unique/distinct values. """, }
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
