# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import subprocess

from components.utilities import string_date_to_uniform_string_date, retry
from components.logging import logEntryExit
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


class VendorResult:
    SUCCESS = 1
    MOZBUILD_ERROR = 2
    SPURIOUS_UPDATE = 3
    GENERAL_ERROR = 4
    PATCH_CONFLICT = 5


class VendorProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    @logEntryExit
    @retry
    def check_for_update(self, library):
        result = self.run(["./mach", "vendor", "--check-for-update", library.yaml_path]).stdout.strip()

        if "Creating " in result and " state directory" in result:
            # If no ~/.mozbuild directory was present this gets output unfortunately.
            result_lines = result.split("\n")
            result_lines = [line.strip() for line in result_lines if line.strip() and "/builds/worker" not in line]
            result = result_lines[0] if result_lines else ""

        # ./mach vendor produces no output when no update is available
        if not result:
            return (None, None)

        # ./mach vendor prints "<revision> <timestamp>", and the timestamp is not
        # space-free on every host (googlesource: "Wed Sep 09 17:56:48 2026").
        revision, timestamp = result.split(" ", 1)
        return (revision, string_date_to_uniform_string_date(timestamp))

    def stage_command(self, library, index, revision):
        """The `./mach vendor` command that runs one of the library's stages, on top of
        the working directory. Only the first takes the revision: later ones use the
        one it recorded in the moz.yaml."""
        if not library.uses_stages:
            # The old format, until every moz.yaml uses stages
            if index == 0:
                return ["./mach", "vendor", library.yaml_path, "--revision", revision] + (
                    ["--patch-mode", "none"] if library.has_patches else [])
            return ["./mach", "vendor", "--patch-mode", "only", library.yaml_path]

        cmd = ["./mach", "vendor", library.yaml_path]
        if index == 0:
            cmd += ["--revision", revision]
        if len(library.stages) > 1:
            cmd += ["--stage", str(index + 1)]
        return cmd

    @logEntryExit
    def vendor_stage(self, library, index, revision):
        try:
            ret = self.run(self.stage_command(library, index, revision), clean_return=False)

            if ret.returncode == 0:
                return (VendorResult.SUCCESS, "")

            msg = ret.stderr.rstrip() + "\n\n" if ret.stderr else ""
            msg += (ret.stdout or "").rstrip()

            if ret.returncode == 255:
                return (VendorResult.MOZBUILD_ERROR, msg)
            elif ret.returncode == 254 and not library.uses_stages:
                # The old format's spurious-update check
                return (VendorResult.SPURIOUS_UPDATE, msg)
        except Exception as e:
            if isinstance(e, subprocess.CalledProcessError):
                msg = e.stderr.rstrip() + "\n\n" if e.stderr else ""
                msg += (e.stdout or "").rstrip()
            else:
                msg = str(e)
        # mach logs this for a patch that doesn't apply, and not for a failed action
        if "Could not apply" in msg:
            return (VendorResult.PATCH_CONFLICT, msg)
        return (VendorResult.GENERAL_ERROR, msg)
