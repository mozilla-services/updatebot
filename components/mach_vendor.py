# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import subprocess

from components.utilities import string_date_to_uniform_string_date
from components.logging import logEntryExit
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


class VendorResult:
    SUCCESS = 1
    MOZBUILD_ERROR = 2
    GENERAL_ERROR = 3


class VendorProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    @logEntryExit
    def check_for_update(self, library):
        result = self.run(["./mach", "vendor", "--check-for-update", library.yaml_path]).stdout.decode().strip()

        # ./mach vendor produces no output when no update is available
        if not result:
            return (None, None)

        if "Creating " in result and " state directory" in result:
            # If no ~/.mozbuild directory was present this gets output unfortunately.
            result_lines = result.split("\n")
            result_lines = [l.strip() for l in result_lines if l.strip() and "state directory" not in l]
            result = result_lines[0]

        parts = result.split(" ")
        return (parts[0], string_date_to_uniform_string_date(parts[1]))

    @logEntryExit
    def vendor(self, library, revision):
        try:
            cmd = ["./mach", "vendor", "--ignore-modified", library.yaml_path, "--revision", revision]
            if library.has_patches:
                cmd += ["--patch-mode", "none"]
            ret = self.run(cmd, clean_return=False)

            if ret.returncode == 0:
                return (VendorResult.SUCCESS, "")

            msg = ret.stderr.decode().rstrip() + "\n\n" if ret.stderr else ""
            msg += ret.stdout.decode().rstrip()

            if ret.returncode == 255:
                return (VendorResult.MOZBUILD_ERROR, msg)
            else:
                return (VendorResult.GENERAL_ERROR, msg)
        except Exception as e:
            if isinstance(e, subprocess.CalledProcessError):
                msg = e.stderr.decode().rstrip() + "\n\n" if e.stderr else ""
                msg += e.stdout.decode().rstrip()
            else:
                msg = str(e)
            return (VendorResult.GENERAL_ERROR, msg)

    @logEntryExit
    def patch(self, library, revision):
        cmd = ["./mach", "vendor", "--patch-mode", "only", "--ignore-modified", library.yaml_path, "--ignore-modified"]
        self.run(cmd, clean_return=True)
