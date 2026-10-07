import json
import os
import shlex
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compass.cli import main
from compass.core import Candidate, build_request, suggest
from compass.session import LIMIT, load_session, save_session


class ConversationTests(unittest.TestCase):
    def test_latest_format_correction_preserves_tag_and_scope(self):
        for earlier, latest, expected in (("json", "table", "table"), ("table", "JSON", "json")):
            with self.subTest(earlier=earlier, latest=latest):
                result = suggest("aws ec2 --profile dev", f"actually use {latest} format", offline=True,
                                 no_help=True, no_history=True, conversation=[{
                                     "intent": f"list instances with tag Environment=prod in {earlier} format",
                                     "suggested_command": "aws ec2 describe-instances --output json"}])
                for candidate in result.candidates:
                    argv = shlex.split(candidate.command)
                    self.assertEqual(argv[argv.index("--output") + 1], expected)
                    self.assertEqual(argv[argv.index("--profile") + 1], "dev")
                self.assertIn("Name=tag:Environment,Values=prod", shlex.split(result.candidates[0].command))

    def test_explicit_output_flag_wins_over_natural_language(self):
        result = suggest("aws ec2 --output table", "list instances in json format", offline=True,
                         no_help=True, no_history=True)
        argv = shlex.split(result.candidates[0].command)
        self.assertEqual(argv[argv.index("--output") + 1], "table")
        self.assertIn("Name:Tags[?Key==`Name`].Value|[0]", argv[argv.index("--query") + 1])

    def test_private_bounded_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "session"
            turns = [{"intent": f"request {i}", "suggested_command": "aws ec2 describe-instances"} for i in range(10)]
            save_session(path, {"buffer": "aws ec2", "turns": turns})
            state = load_session(path)
            self.assertEqual(len(state["turns"]), LIMIT)
            self.assertEqual(state["turns"][-1]["intent"], "request 9")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_saved_secret_or_shell_expression_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "session"
            for state in ({"buffer": "aws; touch bad", "turns": []},
                          {"buffer": "aws ec2", "turns": [{"intent": "api_key=private"}]},
                          {"buffer": "aws ec2", "turns": [{"intent": "list\ninstances"}]}):
                path.write_text(json.dumps(state))
                with self.assertRaises(ValueError):
                    load_session(path)

    def test_latest_literal_tag_replaces_earlier_value(self):
        result = suggest("aws ec2", "actually with tag Environment=staging", offline=True,
                         no_help=True, no_history=True,
                         conversation=[{"intent": "list instances with tag Environment=prod"}])
        self.assertIn("Values=staging", result.candidates[0].command)
        self.assertNotIn("Values=prod", result.candidates[0].command)

    def test_followup_carries_original_request_and_chosen_command_to_jev(self):
        conversation = [{"intent": "list all ec2 with tags", "selected_command": "aws ec2 describe-instances"}]
        item = Candidate("aws ec2 describe-instances", "List instances", "recipe")
        request = build_request("aws ec2", "actually without tags", [item], conversation)
        self.assertEqual(request["state"]["intent"], "actually without tags")
        self.assertEqual(request["state"]["conversation"], conversation)
        self.assertIn("overrides conflicting", request["questions"]["command"]["instructions"])
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "fake"}):
            def ranker(path, query, candidates, key, received):
                self.assertEqual(received, conversation)
                self.assertEqual(query, "actually only with tag nitro")
                return candidates, 0.9
            result = suggest("aws ec2", "actually only with tag nitro", conversation=conversation,
                             no_history=True, no_help=True, ranker=ranker)
        self.assertEqual(result.engine, "jev")

    def test_standalone_resume_uses_saved_scope(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "session"
            flags = ["--offline", "--no-help", "--no-history", "--json", "--session", str(path)]
            with patch("sys.stdout"):
                self.assertEqual(main(flags + ["--buffer", "aws ec2", "list instances with tags"]), 0)
                self.assertEqual(main(flags + ["--resume", "--buffer", "kubectl", "only with tag nitro"]), 0)
            state = load_session(path)
            self.assertEqual(state["buffer"], "aws ec2")
            self.assertEqual(len(state["turns"]), 2)
            self.assertIn("Name=tag-key,Values=nitro", state["turns"][-1]["suggested_command"])


if __name__ == "__main__":
    unittest.main()
