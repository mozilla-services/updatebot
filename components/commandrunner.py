#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import time
import subprocess
from subprocess import PIPE


def do_nothing(*args, **kwargs):
    pass


"""
_run is the raw command implementation.

Except in really weird cases, you should not be using this,
and should be using a ComandProvider.
"""


def _run(args, shell, clean_return, errorlog=do_nothing, infolog=do_nothing, debuglog=do_nothing):
    ran_successfully = False
    stdout = None
    stderr = None
    exception = None

    debuglog("----------------------------------------------")
    start = time.time()
    infolog("Running", args)
    try:
        ret = subprocess.run(
            args, shell=shell, stdout=PIPE, stderr=PIPE, timeout=60 * 10)
    except subprocess.TimeoutExpired as e:
        ran_successfully = False
        stdout = e.stdout
        stderr = e.stderr
        exception = e
    else:
        ran_successfully = True
        stdout = ret.stdout.decode()
        stderr = ret.stderr.decode()

    if not ran_successfully:
        errorlog("Command Timed Out. Will abort....")
    else:
        infolog("Return:", ret.returncode,
                "Runtime (s):", int(time.time() - start))
    debuglog("-------")
    debuglog("stdout:")
    debuglog(stdout)
    debuglog("-------")
    debuglog("stderr:")
    debuglog(stderr)
    debuglog("----------------------------------------------")
    if not ran_successfully:
        raise exception
    if ran_successfully and clean_return:
        if ret.returncode:
            errorlog("Expected a clean process return but got:", ret.returncode)
            errorlog("   (", *args, ")")
            ret.check_returncode()
    return ret
