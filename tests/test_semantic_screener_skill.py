"""Contract tests for the semantic-screener skill guidance."""

from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPOSITORY_ROOT / "skills/dfin-semantic-screener"


class SemanticScreenerSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.metadata = (SKILL_ROOT / "agents/openai.yaml").read_text(encoding="utf-8")

    def test_skill_identity_and_trigger_boundaries(self):
        self.assertIn("name: dfin-semantic-screener", self.skill)
        self.assertIn("first applies quantitative screener criteria", self.skill)
        self.assertIn("Do not use for a pure quantitative screen", self.skill)
        self.assertIn("$dfin-semantic-screener", self.metadata)

    def test_source_coverage_rules_are_explicit(self):
        self.assertIn(
            '`databaseCoverage={"relation":"or","values":["filings"]}`',
            self.skill,
        )
        self.assertIn(
            '`databaseCoverage={"relation":"or","values":["transcripts"]}`',
            self.skill,
        )
        self.assertIn(
            '`databaseCoverage={"relation":"or","values":["filings","transcripts"]}`',
            self.skill,
        )
        self.assertIn(
            '`databaseCoverage={"relation":"and","values":["filings","transcripts"]}`',
            self.skill,
        )
        self.assertIn("The live coverage contract is positive-only", self.skill)
        self.assertIn("not the former `operator` shape", self.skill)
        self.assertIn("every selected ticker ends in `.US`", self.skill)
        self.assertIn("eligible ADRs", self.skill)
        self.assertIn("nonzero `document_count`", self.skill)

    def test_candidate_and_batch_limits_are_explicit(self):
        self.assertIn("Cap the candidate search budget at 100", self.skill)
        self.assertIn("screen/evaluate up to N companies", self.skill)
        self.assertIn("find N companies with evidence", self.skill)
        self.assertIn("stop early", self.skill)
        self.assertIn("batches of at most 25", self.skill)
        self.assertIn("split 26 as 24 plus 2", self.skill)
        self.assertIn("at most four bulk calls per source", self.skill)
        self.assertIn("exactly one candidate", self.skill)

    def test_search_and_failure_guidance_is_explicit(self):
        self.assertIn('`result_format="by_ticker"` by default', self.skill)
        self.assertIn("five calendar years", self.skill)
        self.assertIn("capacity-exceeded response", self.skill)
        self.assertIn("completed empty search may legitimately have no artifact", self.skill)
        self.assertIn("never the private result-artifact URL", self.skill)


if __name__ == "__main__":
    unittest.main()
