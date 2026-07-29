"""Tests for the evaluation suite itself — the eval set's own eval.

The suites in `eval/` are the evidence that the system is not making things up. Nothing
guards that evidence unless something re-derives it, which is what these three modules do:
`test_cases.py` on the schema, `test_oracle.py` on the independent re-aggregation, and
`test_expectations.py` on the literals in `golden_questions.yaml`.
"""
