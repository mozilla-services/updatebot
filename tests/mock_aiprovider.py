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
                     AI producing no parseable result (resolve returns None).
      'ai_details':  the list of detail strings to report.

    It also records how many times it was asked to resolve conflicts so tests
    can assert whether the AI path was taken.
    """

    def __init__(self, config):
        self.ai_outcome = config.get('ai_outcome', 'failure')
        self.ai_details = config.get('ai_details', [])
        self.resolve_call_count = 0

    def resolve_patch_conflicts(self, moz_yaml_path, commit_message, cwd=None,
                                library_name=None, job_id=None):
        self.resolve_call_count += 1
        self.logger.log("MockAIProvider.resolve_patch_conflicts called for %s (outcome=%s)" % (
            moz_yaml_path, self.ai_outcome), level=LogLevel.Info)
        if self.ai_outcome is None:
            return None
        return {"outcome": self.ai_outcome, "details": self.ai_details}
