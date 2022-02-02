#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys
sys.path.append(".")
sys.path.append("..")

from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider
from components.libraryprovider import LibraryProvider, Library


class MockLibraryProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        self.config = config

    def get_libraries(self, gecko_path):
        def path_wrapper(p):
            return os.path.join(os.getcwd(), "tests/" if not os.getcwd().endswith("tests") else "", p)

        def default_repo():
            return "test-repo.bundle"

        return [
            Library({
                "name": "dav1d",
                "bugzilla_product": "Core",
                "bugzilla_component": "Audio/Video: Playback",
                "maintainer_phab": "nobody",
                "maintainer_bz": "nobody@mozilla.com",
                "revision": self.config.get('vendoring_revision_override', None),
                "repo_url": "https://example.invalid",
                "has_patches": False,
                "tasks": [
                    LibraryProvider.validate_task({
                        "type": "vendoring",
                        "enabled": True
                    }, "n/a")
                ],
                "yaml_path": "mozilla-central/source/media/libdav1d/moz.yaml"
            }),
            Library({
                "name": "aom",
                "bugzilla_product": "Core",
                "bugzilla_component": "Audio/Video: Playback",
                "maintainer_phab": "nobody",
                "maintainer_bz": "nobody@mozilla.com",
                "revision": self.config.get('commitalert_revision_override', lambda: None)(),
                "repo_url": path_wrapper((self.config.get('commitalert_repo_override', None) or default_repo)()),
                "has_patches": False,
                "tasks": [
                    LibraryProvider.validate_task({
                        "type": "commit-alert",
                        "enabled": True,
                        "branch": self.config.get('commitalert_branch_override', None)
                    }, "n/a")
                ],
                "yaml_path": "mozilla-central/source/media/libaom/moz.yaml"
            }),
            Library({
                "name": "aom",
                "bugzilla_product": "Core",
                "bugzilla_component": "Audio/Video: Playback",
                "maintainer_phab": "nobody",
                "maintainer_bz": "nobody@mozilla.com",
                "revision": self.config.get('commitalert_revision_override', lambda: None)(),
                "repo_url": path_wrapper((self.config.get('commitalert_repo_override', None) or default_repo)()),
                "has_patches": False,
                "tasks": [
                    LibraryProvider.validate_task({
                        "type": "commit-alert",
                        "enabled": True,
                        "branch": self.config.get('commitalert_branch_override', None)
                    }, "n/a")
                ],
                "yaml_path": "mozilla-central/source/media/libaom/moz.yaml"
            })]
