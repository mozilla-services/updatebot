#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
sys.path.append(".")
sys.path.append("..")

from components.utilities import Struct
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


class MockLibraryProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    def get_libraries(self, gecko_path):
        return [Struct(**{
            "schema": 1,
            "bugzilla": {"product": "Core", "component": "Audio/Video: Playback"},
            "origin": {
                "name": "dav1d",
                "description": "dav1d, a fast AV1 decoder",
                "url": "https://code.videolan.org/videolan/dav1d",
                "release": "commit 0243c3ffb644e61848b82f24f5e4a7324669d76e (2020-09-27T15:38:45.000+02:00).",
                "revision": "0243c3ffb644e61848b82f24f5e4a7324669d76e",
                "license": "BSD-2-Clause",
                "license-file": "COPYING"
            },
            "updatebot": {
                "enabled": True,
                "maintainer-phab": "nobody",
                "maintainer-bz": "nobody@mozilla.com"
            },
            "vendoring": {
                "url": "https://code.videolan.org/videolan/dav1d.git",
                "source-hosting": "gitlab",
                "vendor-directory": "third_party/dav1d",
                "exclude": ["build/.gitattributes", "build/.gitignore"],
                "update-actions": [
                    {
                        "action": "copy-file",
                        "from": "include/vcs_version.h.in",
                        "to": "{yaml_dir}/vcs_version.h"
                    },
                    {
                        "action": "replace-in-file",
                        "pattern": "@VCS_TAG@",
                        "with": "{revision}",
                        "file": "{yaml_dir}/vcs_version.h"
                    }
                ]
            },
            "yaml_path": "mozilla-central/source/media/libdav1d/moz.yaml"
        })]
