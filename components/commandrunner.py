#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import time
import subprocess
from subprocess import PIPE


def do_nothing(*args, **kwargs):
    print("Raw _run call:", *args)


"""
_run is the raw command implementation.

Except in really weird cases, you should not be using this,
and should be using a ComandProvider.
"""


def _run(args, shell, clean_return, errorlog=do_nothing, infolog=do_nothing, debuglog=do_nothing,
         cwd=None, stdin_path=None, timeout=60 * 20, env=None):
    ran_to_completion = False
    stdout = None
    stderr = None
    exception = None

    if shell and isinstance(args, list):
        raise Exception("Only call run() with a string when passing shell=True")

    debuglog("----------------------------------------------")

    start = time.time()
    infolog("Running", args)
    # Optionally feed a file to the process's stdin (used to pass large input,
    # e.g. a Claude prompt, without hitting command-line length limits).
    # Otherwise give it no stdin: on Taskcluster stdin is a TTY nobody types into,
    # so an interactive prompt (e.g. arc diff's for a huge file) would hang until
    # the timeout instead of failing.
    stdin_handle = open(stdin_path, "rb") if stdin_path else None
    # Merge any extra env (e.g. secrets) over the inherited environment.
    run_env = {**os.environ, **env} if env else None
    try:
        # Output that isn't valid UTF-8 (e.g. a commit stored in another encoding)
        # has the bad bytes replaced, rather than making callers decode it.
        ret = subprocess.run(
            args, shell=shell, stdout=PIPE, stderr=PIPE, timeout=timeout,
            cwd=cwd, stdin=stdin_handle or subprocess.DEVNULL, env=run_env,
            encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        ran_to_completion = False
        # TimeoutExpired carries bytes even when the output is text
        stdout = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else e.stdout
        stderr = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else e.stderr
        exception = e
    else:
        ran_to_completion = True
        stdout = ret.stdout
        stderr = ret.stderr
    finally:
        if stdin_handle:
            stdin_handle.close()

    if not ran_to_completion:
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
    if not ran_to_completion:
        raise exception
    if ran_to_completion and clean_return:
        if ret.returncode:
            errorlog("Expected a clean process return but got:", ret.returncode)
            if isinstance(args, list):
                errorlog("   (", *args, ")")
            else:
                errorlog("   (", args, ")")
            ret.check_returncode()
    return ret
