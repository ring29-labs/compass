import tempfile
from pathlib import Path
import shlex
import unittest
from unittest.mock import patch

from compass.completion import completion_choices, completion_scope, read_completions
from compass.core import Candidate, suggest


class CompletionTests(unittest.TestCase):
    def test_records_preserve_literals_deduplicate_and_filter_secrets(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "completions"
            path.write_text("aws ec2 describe-instances\0List instances\0"
                            "aws ec2 describe-instances\0Duplicate\0"
                            "cat 'file with spaces.txt'\0A file\0"
                            "aws configure --api-key hidden\0Secret\0")
            items = read_completions(path)
            self.assertEqual(len(items), 2)
            self.assertEqual(shlex.split(items[1].command), ["cat", "file with spaces.txt"])

    def test_native_browsing_does_not_call_help_history_or_jev(self):
        native = [Candidate("newcli native-only-command", "Native choice", "completion")]
        with patch("compass.completion.read_history") as history, patch("compass.core.urlopen") as api:
            def discover(path):
                self.fail("Native browsing must not invoke help")
            result = completion_choices("newcli", native, None, False, False, discover)
            self.assertEqual(result.candidates, native)
            self.assertEqual(result.engine, "completion")
            history.assert_not_called()
            api.assert_not_called()

    def test_fallback_help_is_not_limited_to_eight_choices(self):
        text = "Commands:\n" + "".join(f"  action-{i}  Description {i}\n" for i in range(256))
        result = completion_choices("newcli", [], None, True, False, lambda _: text)
        self.assertEqual(len(result.candidates), 256)
        self.assertEqual(result.engine, "browse")

    def test_incomplete_flags_leave_a_valid_search_scope(self):
        self.assertEqual(completion_scope("aws ec2 --profile staging --output"), "aws ec2 --profile staging")
        self.assertEqual(completion_scope("aws ec2 describe-instances --unknown value"), "aws ec2 describe-instances")

    def test_native_only_command_is_available_to_semantic_search(self):
        native = Candidate("newcli native-only-command", "List widgets", "completion")
        result = suggest("newcli", "list widgets", extra_candidates=[native], offline=True,
                         no_help=True, no_history=True)
        self.assertEqual(result.candidates[0].command, native.command)

    def test_native_scope_with_global_flags_before_the_service_is_searchable(self):
        native = Candidate("aws --profile old ec2 native-only-command", "List native widgets", "completion")
        result = suggest("aws --profile staging ec2", "list native widgets", extra_candidates=[native],
                         offline=True, no_help=True, no_history=True)
        argv = shlex.split(result.candidates[0].command)
        self.assertEqual(argv[:3], ["aws", "ec2", "native-only-command"])
        self.assertEqual(argv[argv.index("--profile") + 1], "staging")


if __name__ == "__main__":
    unittest.main()
