import io
import json
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from compass.core import (Candidate, JevError, build_request, clean_help, help_text,
                          jev_rank, parse_help, read_history, shortlist, split_buffer,
                          suggest, templates)


class HistoryTests(unittest.TestCase):
    def test_history_is_recent_deduplicated_scoped_and_secret_filtered(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "history"
            path.write_text(": 1:0;aws ec2 describe-instances\n"
                            ": 2:0;kubectl get pods\n"
                            ": 3:0;aws configure set aws_secret_access_key something\n"
                            ": 4:0;aws ec2 describe-instances\n"
                            "aws s3 ls\naws ec2 describe-instances; touch /tmp/bad\n"
                            "aws ec2 describe-instances \\\n --profile prod\n"
                            "aws ec2 describe-volumes\n")
            commands = [c.command for c in read_history(path, "aws")]
            self.assertEqual(commands, ["aws ec2 describe-volumes", "aws s3 ls", "aws ec2 describe-instances"])

    def test_missing_history_is_ok(self):
        self.assertEqual(read_history(Path("/does/not/exist"), "aws"), [])


class DiscoveryTests(unittest.TestCase):
    def test_aws_manpage_and_cobra_and_azure(self):
        text = clean_help("A\bAV\bVA\bAI\bIL\bLA\bAB\bBL\bLE\bE C\bCO\bOM\bMM\bMA\bAN\bND\bDS\bS\n     +\bo describe-instances\n\n     +\bo terminate-instances\n")
        self.assertEqual([c.command for c in parse_help("aws ec2", text)],
                         ["aws ec2 describe-instances", "aws ec2 terminate-instances"])
        text = "Basic Commands (Beginner):\n  get     Display resources\nOther Commands:\n  config  Modify kubeconfig\nFlags:\n  --x     An option\n"
        self.assertEqual([c.command for c in parse_help("kubectl", text)], ["kubectl get", "kubectl config"])
        text = "Subgroups:\n    vm : Manage VMs.\nCommands:\n    login : Log in.\n"
        items = parse_help("az", text)
        self.assertTrue(items[0].group)
        self.assertEqual(items[1].description, "Log in.")

    def test_argparse_subparsers(self):
        items = parse_help("newcli", "positional arguments:\n  {init,list,help}  command\n")
        self.assertEqual([c.command for c in items], ["newcli init", "newcli list"])

    def test_help_never_executes_a_shell_expression(self):
        for path in ("aws ec2; touch bad", "aws $(whoami)", "aws ec2 --endpoint-url evil", "aws\nfoo"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                help_text(path)

    def test_new_cli_group_discovery(self):
        helps = {"newcli": "Commands:\n  compute  Manage virtual machines\n  storage  Manage disks\n",
                 "newcli compute": "Commands:\n  list  List virtual machines\n  delete  Delete virtual machines\n"}
        result = suggest("newcli", "list virtual machines", offline=True, no_history=True,
                         discover=lambda p: helps.get(p, ""))
        self.assertEqual(result.candidates[0].command, "newcli compute list")

    def test_cache_and_help_argv(self):
        with tempfile.TemporaryDirectory() as d:
            binary = Path(d) / "aws"
            binary.write_text("fake")
            with patch("compass.core.shutil.which", return_value=str(binary)), patch("compass.core.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "AVAILABLE COMMANDS\n + describe-instances\n"
                one = help_text("aws ec2", Path(d) / "cache")
                two = help_text("aws ec2", Path(d) / "cache")
                self.assertEqual(one, two)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0], ["aws", "ec2", "help"])
                self.assertNotIn("shell", run.call_args.kwargs)


class RecipeTests(unittest.TestCase):
    def test_ec2_table_request_has_flat_name_projection(self):
        result = suggest("aws ec2", "list all instance in table format", offline=True,
                         no_history=True, no_help=True)
        argv = shlex.split(result.candidates[0].command)
        self.assertEqual(argv[:3], ["aws", "ec2", "describe-instances"])
        self.assertEqual(argv[argv.index("--output") + 1], "table")
        self.assertEqual(argv[argv.index("--query") + 1],
                         "Reservations[].Instances[].{ID:InstanceId,State:State.Name,Type:InstanceType,Name:Tags[?Key==`Name`].Value|[0]}")

    def test_ec2_table_with_tags_flattens_tags_and_keeps_filter(self):
        result = suggest("aws ec2", "list instances with tags in table format with tag Environment=prod",
                         offline=True, no_history=True, no_help=True)
        argv = shlex.split(result.candidates[0].command)
        self.assertIn("Name=tag:Environment,Values=prod", argv)
        self.assertEqual(argv[argv.index("--output") + 1], "table")
        self.assertIn("Tags:join(", argv[argv.index("--query") + 1])

    def test_tag_named_table_does_not_change_output_format(self):
        result = suggest("aws ec2", "list instances with tag table", offline=True,
                         no_history=True, no_help=True)
        argv = shlex.split(result.candidates[0].command)
        self.assertEqual(argv[argv.index("--output") + 1], "json")

    def test_ec2_tag_key_and_value_are_both_available(self):
        items = templates("aws ec2", "list all ec2 with tag nitro")
        argv = [shlex.split(c.command) for c in items]
        self.assertTrue(any("Name=tag-key,Values=nitro" in a for a in argv))
        self.assertTrue(any("Name=tag-value,Values=nitro" in a for a in argv))

    def test_ec2_key_equals_value(self):
        result = suggest("aws ec2", "list all ec2 with tag Environment=prod", offline=True,
                         no_history=True, no_help=True)
        self.assertIn("Name=tag:Environment,Values=prod", shlex.split(result.candidates[0].command))

    def test_scope_flags_override_history_and_recipe_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "hist"
            h.write_text("aws ec2 describe-instances --profile old --output json\n")
            result = suggest("aws --profile new ec2 --region eu-west-1 --output table", "list instances",
                             history=h, offline=True, no_help=True)
            for candidate in result.candidates:
                argv = shlex.split(candidate.command)
                self.assertEqual(argv.count("--profile"), 1)
                self.assertEqual(argv[argv.index("--profile") + 1], "new")
                self.assertEqual(argv[argv.index("--region") + 1], "eu-west-1")
                self.assertEqual(argv[argv.index("--output") + 1], "table")

    def test_kubernetes_selector_and_all_namespaces(self):
        result = suggest("kubectl", "list pods in all namespaces with label app=nitro", offline=True,
                         no_history=True, no_help=True)
        argv = shlex.split(result.candidates[0].command)
        self.assertEqual(argv[:3], ["kubectl", "get", "pods"])
        self.assertIn("--all-namespaces", argv)
        self.assertIn("app=nitro", argv)

    def test_explicit_namespace_wins_over_all_namespaces_recipe(self):
        result = suggest("kubectl --namespace staging", "list pods in all namespaces", offline=True,
                         no_history=True, no_help=True)
        for candidate in result.candidates:
            argv = shlex.split(candidate.command)
            self.assertNotIn("--all-namespaces", argv)
            self.assertEqual(argv[argv.index("--namespace") + 1], "staging")

    def test_offline_nonsense_does_not_offer_recipes(self):
        result = suggest("aws ec2", "pizza bananas", offline=True, no_history=True, no_help=True)
        self.assertEqual(result.candidates, [])

    def test_azure_tags_quote_identifiers(self):
        items = templates("az vm", "list virtual machines with tag team.name=nitro")
        argv = [shlex.split(c.command) for c in items]
        self.assertTrue(any('[?tags."team.name"==\'nitro\']' in " ".join(a) for a in argv))

    def test_untrusted_slot_is_not_copied_to_command(self):
        items = templates("aws ec2", 'list instances with tag nitro; touch /tmp/bad')
        self.assertTrue(all("touch" not in c.command and ";" not in c.command for c in items))

    def test_empty_malformed_and_secret_inputs(self):
        for buffer, query in [("aws ec2", ""), ("aws; touch bad", "list"),
                              ("aws ec2 --profile", "list"), ("aws ec2", "api_key=private"),
                              ("aws ec2", "list\ninstances")]:
            with self.subTest(buffer=buffer, query=query), self.assertRaises(ValueError):
                suggest(buffer, query, offline=True, no_help=True, no_history=True)


class JevTests(unittest.TestCase):
    def test_jev_sees_requested_format_and_explicit_context_before_ranking(self):
        with tempfile.TemporaryDirectory() as d:
            history = Path(d) / "history"
            history.write_text("aws ec2 describe-instances --profile old --output json\n")
            def ranker(path, query, candidates, key):
                for candidate in candidates:
                    argv = shlex.split(candidate.command)
                    self.assertEqual(argv[argv.index("--output") + 1], "table")
                    self.assertEqual(argv[argv.index("--profile") + 1], "new")
                    self.assertEqual(argv.count("--output"), 1)
                self.assertTrue(any("Name:Tags[?Key==`Name`].Value|[0]" in c.command for c in candidates))
                return candidates, 0.99
            with patch.dict(os.environ, {"TYPESAFE_API_KEY": "fake"}):
                result = suggest("aws ec2 --profile new", "list all instance in table format",
                                 history=history, no_help=True, ranker=ranker)
            self.assertEqual(result.engine, "jev")

    def test_help_expansion_keeps_context_out_of_help_command_paths(self):
        helps = {"az custom": "Subgroups:\n  compute  Manage machines\n",
                 "az custom compute": "Commands:\n  list  List machines\n"}
        seen = []
        def discover(path):
            seen.append(path)
            return helps.get(path, "")
        result = suggest("az custom --subscription dev", "list machines in table format",
                         offline=True, no_history=True, discover=discover)
        self.assertIn("az custom compute", seen)
        self.assertTrue(all("--" not in path for path in seen))
        self.assertEqual(shlex.split(result.candidates[0].command),
                         ["az", "custom", "compute", "list", "--subscription", "dev", "--output", "table"])

    def setUp(self):
        self.items = [Candidate("aws ec2 describe-instances", "List instances", "help"),
                      Candidate("aws ec2 terminate-instances", "Terminate instances", "help")]

    def response(self, probabilities=None, fit=0.98):
        return {"answers": {"command": {"type": "choice", "choice": "0",
                  "probabilities": probabilities or {"0": 0.9, "1": 0.05, "none": 0.05}},
                "fit": {"type": "noul", "noul": fit}}}

    def test_request_is_typed_and_bounded_with_no_match(self):
        body = build_request("aws ec2", "list instances", self.items)
        self.assertEqual(body["questions"]["command"]["type"], "choice")
        self.assertIn("none", body["questions"]["command"]["criteria"])
        self.assertEqual(body["questions"]["fit"]["type"], "noul")
        with self.assertRaises(ValueError):
            build_request("aws", "list", self.items * 128)

    def test_parse_live_response_contract(self):
        with patch("compass.core.urlopen", return_value=io.BytesIO(json.dumps(self.response()).encode())) as open_url:
            ranked, fit = jev_rank("aws ec2", "list instances", self.items, "fake-test-key")
        self.assertEqual(ranked[0].command, "aws ec2 describe-instances")
        self.assertEqual(fit, 0.98)
        self.assertEqual(open_url.call_args.args[0].full_url, "https://api.typesafe.ai/v1/systemone")

    def test_no_match_and_low_fit_are_empty(self):
        for response in (self.response({"0": 0.1, "1": 0.1, "none": 0.8}), self.response(fit=0.2)):
            with patch("compass.core.urlopen", return_value=io.BytesIO(json.dumps(response).encode())):
                self.assertEqual(jev_rank("aws", "unrelated", self.items, "fake")[0], [])

    def test_invalid_response_is_rejected(self):
        for probabilities in ({"0": 1, "none": 0}, {"0": -0.5, "1": 1.5, "none": 0},
                              {"0": float("nan"), "1": 0, "none": 0}):
            with patch("compass.core.urlopen", return_value=io.BytesIO(json.dumps(self.response(probabilities)).encode())), self.assertRaises(JevError):
                jev_rank("aws", "list", self.items, "fake")

    def test_api_error_is_safe_and_falls_back(self):
        def failing(*args):
            raise JevError("TypeSafe rate limit reached")
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "fake"}):
            result = suggest("aws ec2", "list instances", no_history=True, no_help=True, ranker=failing)
        self.assertEqual(result.engine, "local")
        self.assertTrue(result.candidates)
        self.assertIn("rate limit", result.warnings[0])
        error = HTTPError("https://api.typesafe.ai", 401, "bad", {}, None)
        with patch("compass.core.urlopen", side_effect=error), self.assertRaisesRegex(JevError, "API key"):
            jev_rank("aws", "list", self.items, "private-test-key")

    def test_no_history_never_reads_history(self):
        with patch("compass.core.read_history") as read:
            suggest("aws ec2", "list instances", offline=True, no_help=True, no_history=True)
            read.assert_not_called()

    def test_candidate_prefilter_fits_choice_limits(self):
        items = [Candidate(f"aws ec2 action-{i}", "An action", "help") for i in range(800)] + self.items
        pool = shortlist(items, "list instances")
        self.assertLessEqual(len(pool), 120)
        self.assertIn(self.items[0], pool)


if __name__ == "__main__":
    unittest.main()
