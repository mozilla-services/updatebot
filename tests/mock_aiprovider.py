#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
sys.path.append(".")
sys.path.append("..")

from components.providerbase import BaseProvider, INeedsLoggingProvider
from components.logging import LogLevel


class MockAIProvider(BaseProvider, INeedsLoggingProvider):
    """
    A stand-in for AIProvider used by the functionality tests. It never shells
    out to a real AI CLI; instead resolve_patch_conflicts returns a result
    driven by the provider's config:

      'ai_outcome':  the 'outcome' value to report ('trivial success',
                     'uncertain success', 'failure'), or None to simulate the
                     AI producing no parseable result (reported as 'failure').
      'ai_details':  the list of detail strings to report.
      'ai_fix':      optional; called with the checkout's path and the commit
                     message to use, to do what the AI would (fix the patches
                     and commit them).

    It also records how many times it was asked to resolve conflicts so tests
    can assert whether the AI path was taken.
    """

    def __init__(self, config):
        self.ai_outcome = config.get('ai_outcome', 'failure')
        self.ai_details = config.get('ai_details', [])
        # Called with the gecko path to act out the AI's fix: editing and committing
        # the patches, as the real one does
        self.ai_fix = config.get('ai_fix')
        self.resolve_call_count = 0
        self.resolve_calls = []

    def resolve_patch_conflicts(self, library, stage, stage_command, commit_message, cwd=None, job_id=None):
        self.resolve_call_count += 1
        self.resolve_calls.append({'stage_name': stage['name'], 'stage_command': " ".join(stage_command), 'commit_message': commit_message})
        self.logger.log("MockAIProvider.resolve_patch_conflicts called for %s (outcome=%s)" % (
            library.yaml_path, self.ai_outcome), level=LogLevel.Info)
        if self.ai_fix:
            self.ai_fix(cwd, commit_message)
        if self.ai_outcome is None:
            return ("failure", "")
        return (self.ai_outcome, "\n".join(self.ai_details))
