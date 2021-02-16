#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
sys.path.append(".")
sys.path.append("..")

from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider
from components.libraryprovider import LibraryProvider, Library


class MockLibraryProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    def get_libraries(self, gecko_path):
        return [Library({
            "name": "dav1d",
            "bugzilla_product": "Core",
            "bugzilla_component": "Audio/Video: Playback",
            "maintainer_phab": "nobody",
            "maintainer_bz": "nobody@mozilla.com",
            "revision": "None",
            "tasks": [
                LibraryProvider.validate_task({
                    "type": "vendoring",
                    "enabled": True
                }, "n/a")
            ],
            "yaml_path": "mozilla-central/source/media/libdav1d/moz.yaml"
        })]
