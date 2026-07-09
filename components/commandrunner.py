#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import time
import platform
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

    # On Windows we need to call things slightly differently
    if isinstance(args, list) and platform.system() == 'Windows':
        # translate git -> git.exe
        if args[0] == "git":
            infolog("Translating git to git.exe")
            args[0] = 'git.exe'
        # ./mach doesn't work on automation, we need to pass it to an interpretter
        # ./mach is actually a shell script that re-executes itself with the correct python
        # BUT in automation it uses the default python3, so we can skip the shell-based
        # python3 locator code and go straight to python3
        elif args[0] == "./mach" and "MOZ_AUTOMATION" in os.environ:
            args.insert(0, "python3")

    start = time.time()
    infolog("Running", args)
    # Optionally feed a file to the process's stdin (used to pass large input,
    # e.g. a Claude prompt, without hitting command-line length limits).
    stdin_handle = open(stdin_path, "rb") if stdin_path else None
    # Merge any extra env (e.g. secrets) over the inherited environment.
    run_env = {**os.environ, **env} if env else None
    try:
        ret = subprocess.run(
            args, shell=shell, stdout=PIPE, stderr=PIPE, timeout=timeout,
            cwd=cwd, stdin=stdin_handle, env=run_env)
    except subprocess.TimeoutExpired as e:
        ran_to_completion = False
        stdout = e.stdout
        stderr = e.stderr
        exception = e
    else:
        ran_to_completion = True
        stdout = ret.stdout.decode()
        stderr = ret.stderr.decode()
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
