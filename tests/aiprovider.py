#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys
import json
import tempfile
import unittest

sys.path.append(".")
sys.path.append("..")

from components.aiprovider import AIProvider, CONFLICT_RESOLUTION_RESULT_FILE
from components.utilities import Struct, load_prompt
from components.logging import SimpleLogger


class RecordingCommandProvider:
    """
    Stands in for the CommandProvider: records how it was invoked (args, cwd,
    stdin, env), returns canned `claude` JSON, and optionally writes a
    conflict_resolution_result.json into cwd the way the real CLI would.
    """

    def __init__(self, stdout="{}", returncode=0, result_file_contents=None):
        self.stdout = stdout
        self.returncode = returncode
        self.result_file_contents = result_file_contents
        self.calls = []

    def run(self, args, shell=False, clean_return=True, cwd=None, stdin_path=None, timeout=60 * 20, env=None):
        call = {"args": args, "cwd": cwd, "stdin_path": stdin_path, "env": env,
                "prompt": None, "system_prompt": None}
        if stdin_path and os.path.exists(stdin_path):
            with open(stdin_path) as f:
                call["prompt"] = f.read()
        if "--append-system-prompt-file" in args:
            system_path = args[args.index("--append-system-prompt-file") + 1]
            if os.path.exists(system_path):
                with open(system_path) as f:
                    call["system_prompt"] = f.read()
        self.calls.append(call)
        if self.result_file_contents is not None and cwd:
            with open(os.path.join(cwd, CONFLICT_RESOLUTION_RESULT_FILE), "w") as f:
                f.write(self.result_file_contents)
        return Struct(**{"stdout": self.stdout.encode(),
                         "returncode": self.returncode,
                         "check_returncode": lambda: None})


def make_ai(config, command_provider):
    ai = AIProvider(config)
    ai.update_config({
        "CommandProvider": command_provider,
        "LoggingProvider": SimpleLogger({"local": False}),
    })
    return ai


class TestAIProviderParseResult(unittest.TestCase):
    def _parse(self, stdout, returncode):
        ai = make_ai({}, RecordingCommandProvider())
        return ai._parse_result(Struct(**{"stdout": stdout, "returncode": returncode,
                                          "check_returncode": lambda: None}))

    def test_success(self):
        r = self._parse(b'{"is_error": false, "result": "done", "session_id": "abc"}', 0)
        self.assertTrue(r.success)
        self.assertEqual(r.text, "done")
        self.assertEqual(r.session_id, "abc")

    def test_is_error_true(self):
        r = self._parse(b'{"is_error": true, "result": "nope"}', 0)
        self.assertFalse(r.success)

    def test_nonzero_returncode(self):
        r = self._parse(b'{"is_error": false, "result": "x"}', 1)
        self.assertFalse(r.success)

    def test_malformed_json(self):
        r = self._parse(b'this is not json', 0)
        self.assertFalse(r.success)


class TestAIProviderResolvePatchConflicts(unittest.TestCase):
    def test_success_returns_dict_and_uses_expected_invocation(self):
        canned = json.dumps({"outcome": "trivial success", "details": ["updated foo.patch"]})
        cmd = RecordingCommandProvider(stdout='{"is_error": false, "result": "ok"}',
                                       result_file_contents=canned)
        ai = make_ai({"apikey": "sk-test", "model": "claude-test-model"}, cmd)

        with tempfile.TemporaryDirectory() as d:
            resolution = ai.resolve_patch_conflicts("media/libfoo/moz.yaml", "Bug 1 - fix patches", cwd=d)
            # The result file is consumed (removed) after being read.
            self.assertFalse(os.path.exists(os.path.join(d, CONFLICT_RESOLUTION_RESULT_FILE)))

        self.assertEqual(resolution["outcome"], "trivial success")
        self.assertEqual(resolution["details"], ["updated foo.patch"])

        call = cmd.calls[0]
        self.assertEqual(call["args"][0], "claude")
        self.assertIn("-p", call["args"])
        self.assertIn("--permission-mode", call["args"])
        self.assertIn("bypassPermissions", call["args"])
        self.assertIn("--append-system-prompt-file", call["args"])
        self.assertIn("claude-test-model", call["args"])
        self.assertEqual(call["env"], {"ANTHROPIC_API_KEY": "sk-test"})
        # The prompt is fed over stdin and rendered from the templates.
        self.assertIsNotNone(call["prompt"])
        self.assertIn("media/libfoo/moz.yaml", call["prompt"])
        self.assertIn("Bug 1 - fix patches", call["prompt"])
        self.assertIn("Conflict Resolution Process", call["prompt"])
        # The system prompt is prompts/system.md.
        self.assertIn("Updatebot", call["system_prompt"])

    def test_missing_result_file_returns_none(self):
        cmd = RecordingCommandProvider(stdout='{"is_error": false}', result_file_contents=None)
        ai = make_ai({"apikey": "sk-test"}, cmd)
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(ai.resolve_patch_conflicts("m/moz.yaml", "msg", cwd=d))

    def test_garbage_result_file_returns_none(self):
        cmd = RecordingCommandProvider(stdout='{"is_error": false}', result_file_contents="not json")
        ai = make_ai({"apikey": "sk-test"}, cmd)
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(ai.resolve_patch_conflicts("m/moz.yaml", "msg", cwd=d))

    def test_no_apikey_passes_no_env(self):
        canned = json.dumps({"outcome": "failure", "details": []})
        cmd = RecordingCommandProvider(stdout='{"is_error": false}', result_file_contents=canned)
        ai = make_ai({}, cmd)  # no apikey configured
        with tempfile.TemporaryDirectory() as d:
            ai.resolve_patch_conflicts("m/moz.yaml", "msg", cwd=d)
        self.assertIsNone(cmd.calls[0]["env"])


class TestLoadPrompt(unittest.TestCase):
    def test_substitution(self):
        p = load_prompt("conflict_resolution_details",
                        moz_yaml_path="media/libx/moz.yaml",
                        patch_fix_commit_message="Bug 2 - update patches")
        self.assertIn("media/libx/moz.yaml", p)
        self.assertIn("Bug 2 - update patches", p)
        self.assertNotIn("{{ moz_yaml_path }}", p)
        self.assertNotIn("{{ patch_fix_commit_message }}", p)

    def test_composition(self):
        details = load_prompt("conflict_resolution_details",
                              moz_yaml_path="X", patch_fix_commit_message="M")
        p = load_prompt("conflict_resolution", conflict_resolution_instructions=details)
        self.assertNotIn("{{ conflict_resolution_instructions }}", p)
        self.assertIn("Conflict Resolution Process", p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
