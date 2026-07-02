#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import json
import shutil
import tempfile

from components.utilities import load_prompt
from components.logging import logEntryExit, LogLevel
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


CONFLICT_RESOLUTION_RESULT_FILE = "conflict_resolution_result.json"


class AIResult:
    def __init__(self, success, text, session_id=None):
        self.success = success
        self.text = text
        self.session_id = session_id


class AIProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    """
    Invokes an AI coding agent headlessly to perform a task described by a
    prompt, and returns its result. Currently backed by the Claude Code CLI
    (`claude -p`).

    The prompt and system prompt are written to files rather than passed on the
    command line, so we never hit command-line length limits: the prompt is fed
    on stdin (claude reads the prompt from stdin when given no positional
    prompt) and the system prompt is passed with --append-system-prompt-file.
    """

    def __init__(self, config):
        self.model = config.get('model', 'claude-opus-4-8')
        self.max_turns = config.get('max-turns', 30)
        self.timeout = config.get('timeout', 60 * 60)
        # API key for the AI CLI, supplied through the config dictionary (like
        # the Database password and Bugzilla apikey). Passed to the CLI via the
        # environment variable it expects rather than on the command line.
        self.apikey = config.get('apikey', None)

    @logEntryExit
    def _run_prompt(self, prompt, system_prompt=None, cwd=None):
        tmpdir = tempfile.mkdtemp(prefix="updatebot-claude-")
        try:
            prompt_path = os.path.join(tmpdir, "prompt.txt")
            with open(prompt_path, "w") as f:
                f.write(prompt)

            args = ["claude", "-p",
                    "--output-format", "json",
                    "--permission-mode", "bypassPermissions",
                    "--model", self.model,
                    "--max-turns", str(self.max_turns)]

            if system_prompt:
                system_path = os.path.join(tmpdir, "system_prompt.txt")
                with open(system_path, "w") as f:
                    f.write(system_prompt)
                args += ["--append-system-prompt-file", system_path]

            env = {"ANTHROPIC_API_KEY": self.apikey} if self.apikey else None

            # claude returns is_error (and a non-zero exit) on failure but still
            # prints the JSON result we want to read, so don't let run() raise.
            ret = self.run(args, shell=False, clean_return=False, cwd=cwd,
                           stdin_path=prompt_path, timeout=self.timeout, env=env)
            return self._parse_result(ret)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _parse_result(self, ret):
        stdout = ret.stdout.decode() if isinstance(ret.stdout, bytes) else ret.stdout
        try:
            data = json.loads(stdout)
        except ValueError:
            self.logger.log("The AI CLI did not return parseable JSON output.", level=LogLevel.Error)
            return AIResult(False, stdout)

        success = (ret.returncode == 0) and not data.get("is_error", True)
        return AIResult(success, data.get("result", ""), data.get("session_id"))

    @logEntryExit
    def resolve_patch_conflicts(self, moz_yaml_path, commit_message, cwd=None):
        # Ask the AI to resolve local-patch conflicts for a library. It works in
        # the checkout (cwd), updates the .patch files / moz.yaml so they apply,
        # and writes its verdict to CONFLICT_RESOLUTION_RESULT_FILE. Returns the
        # parsed {"outcome", "details"} dict, or None if it produced no result.
        instructions = load_prompt("conflict_resolution_details",
                                   moz_yaml_path=moz_yaml_path,
                                   patch_fix_commit_message=commit_message)
        prompt = load_prompt("conflict_resolution", conflict_resolution_instructions=instructions)
        system_prompt = load_prompt("system")

        self._run_prompt(prompt, system_prompt=system_prompt, cwd=cwd)

        result_path = os.path.join(cwd, CONFLICT_RESOLUTION_RESULT_FILE) if cwd else CONFLICT_RESOLUTION_RESULT_FILE
        try:
            with open(result_path) as f:
                resolution = json.load(f)
            os.remove(result_path)
        except (OSError, ValueError):
            self.logger.log("Could not read %s after AI conflict resolution." % CONFLICT_RESOLUTION_RESULT_FILE, level=LogLevel.Warning)
            return None
        self.logger.log("AI conflict resolution outcome: %s" % resolution.get("outcome"), level=LogLevel.Info)
        return resolution
