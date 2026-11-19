GEN_SYSTEM = (
    "You are an expert SQLite analyst. Given a database schema and a question, write ONE SQLite query that "
    "answers the question. Use only tables and columns that appear in the schema. Select only what the question "
    "asks for. Reply with the SQL in a single ```sql code block and nothing else."
)
GEN_USER = "Database schema:\n{schema}\n\nQuestion: {question}\n\nSQLite query:"

RERANK_SYSTEM = (
    "You are a database expert. You decide which tables of a database are needed to answer a question. "
    "Reply with JSON only."
)
RERANK_USER = (
    "Question: {question}\n\n"
    "Candidate tables (name(columns)):\n{candidates}\n\n"
    "Select at most {k} tables that are needed to write the SQL query for the question. "
    "Include tables that are only needed as join bridges between other selected tables. "
    'Return ONLY JSON of the form {{"tables": ["table_a", "table_b"]}} ordered from most to least relevant.'
)

# ---------------------------------------------------------------- error-fix / retry loop
FIX_USER = (
    "Your previous query is not acceptable: {reason}.\n"
    "Fix it. Use only tables and columns from the schema. "
    "Reply with the corrected SQLite query in a single ```sql code block and nothing else."
)

JUDGE_SYSTEM = "You are a careful reviewer of SQL query results. Reply with JSON only."
JUDGE_USER = (
    "Question: {question}\n\n"
    "SQL query:\n{sql}\n\n"
    "Result ({n_rows} row(s) in total; first rows shown, columns in query order):\n{preview}\n\n"
    "Does this result plausibly and completely answer the question? Check that the right columns are returned, "
    "that the filters / aggregation match the question and that nothing obvious is missing. "
    "Be lenient about column order, aliases and formatting. "
    'Reply ONLY with JSON: {{"answers_question": true or false, "reason": "<one short sentence>"}}'
)