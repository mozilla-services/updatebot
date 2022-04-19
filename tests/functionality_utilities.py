#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import platform


def AssertFalse(a=False, b=False, c=False):
    assert False, "We should not have called this function in this test."


def SHARED_COMMAND_MAPPINGS(expected_values, callbacks):
    def echo_str(s):
        if platform.system() != "Windows":
            return s.replace("echo {", "echo '{")
    return {
        "./mach vendor --patch-mode only": callbacks['patch'] if 'patch' in callbacks else AssertFalse,
        "./mach vendor --check-for-update": lambda: expected_values.library_new_version_id() + " 2020-08-21T15:13:49.000+02:00",
        "./mach vendor ": callbacks['vendor'] if 'vendor' in callbacks else lambda: "",
        "hg commit": callbacks['commit'] if 'commit' in callbacks else lambda: "",
        "hg checkout -C .": lambda: "",
        "hg purge .": lambda: "",
        "hg status": lambda: "",
        "hg strip": lambda: "",
        "arc diff --verbatim": callbacks['phab_submit'] if 'phab_submit' in callbacks else lambda: ARC_OUTPUT % (expected_values.phab_revision_func(), expected_values.phab_revision_func()),
        echo_str("echo {\"constraints\""): lambda: CONDUIT_USERNAME_SEARCH_OUTPUT,
        echo_str("echo {\"transactions\": [{\"type\":\"reviewers.set\""): lambda: CONDUIT_EDIT_OUTPUT,
        echo_str("echo {\"transactions\": [{\"type\":\"abandon\""): callbacks['abandon'] if 'abandon' in callbacks else AssertFalse,
        echo_str("echo {\"transactions\": [{\"type\":\"bugzilla.bug-id\""): lambda: CONDUIT_EDIT_OUTPUT,
        "git log -1 --oneline": lambda: "0481f1c (HEAD -> issue-115-add-revision-to-log, origin/issue-115-add-revision-to-log) Issue #115 - Add revision of updatebot to log output",
        "git clone https://example.invalid .": lambda: "",
        "git merge-base": lambda: "_current",
        "git log --pretty=%H|%ai|%ci": lambda cmd: "\n".join(expected_values.git_pretty_output_func("_current" not in cmd)),
        "git diff --name-status": lambda: GIT_DIFF_FILES_CHANGES,
        "git log --pretty=%s": lambda: "Roll SPIRV-Tools from a61d07a72763 to 1cda495274bb (1 revision)",
        "git log --pretty=%an": lambda: "Tom Ritter",
        "git log --pretty=%b": lambda: GIT_COMMIT_BODY,
    }


def TRY_OUTPUT(revision, include_auto_line=True):
    s = ""
    if include_auto_line:
        s = "warning: 'mach try auto' is experimental, results may vary!\n"
    s += """
Test configuration changed. Regenerating backend.
Creating temporary commit for remote...
A try_task_config.json
pushing to ssh://hg.mozilla.org/try
searching for changes
remote: adding changesets
remote: adding manifests
remote: adding file changes
remote: recorded push in pushlog
remote: added 2 changesets with 1 changes to 6 files (+1 heads)
remote:
remote: View your changes here:
remote:   https://hg.mozilla.org/try/rev/a8adec7d117968b8f0006a9e54393dba7c444717
remote:   https://hg.mozilla.org/try/rev/%s
remote:
remote: Follow the progress of your build on Treeherder:
remote:   https://treeherder.mozilla.org/#/jobs?repo=try&revision=%s
remote: recorded changegroup in replication log in 0.011s
push complete
temporary commit removed, repository restored
""" % (revision, revision)
    return s


ARC_OUTPUT = """
Submitting 1 commit for review:
(New) 539627:dc5f73bea33e Bug 1652039 - Include checks in subdirectories in MozillaTidyModule.cpp r?andi
dc5f73bea33e is based off non-public commit 76fbb2477f01
Warning: found 2 untracked files (will not be submitted):
  sshkey.patch
  taskcluster/ci/fetch/toolchains.yml.orig
Automatically submitting (as per submit.auto_submit in ~/.moz-phab-config)

Creating new revision:
539627:dc5f73bea33e Bug 1652039 - Include checks in subdirectories in MozillaTidyModule.cpp r?andi
1 new orphan changesets
rebasing 539628:2f4625139f7e "Bug 1652037 - Wire up build_clang_tidy_external in build-clang.py r?#build" (civet)
1 files updated, 0 files merged, 0 files removed, 0 files unresolved
(activating bookmark civet)

Completed
(D%s) 539629:94adaadd8131 Bug 1652039 - Include checks in subdirectories in MozillaTidyModule.cpp r?andi
-> https://phabricator-dev.allizom.org/D%s
"""

CONDUIT_USERNAME_SEARCH_OUTPUT = """
{"error":null,"errorMessage":null,"response":{"data":[{"id":154,"type":"USER","phid":"PHID-USER-dd6rge2k2csia46r2wcw","fields":{"username":"tjr","realName":"Tom Ritter","roles":["verified","approved","activated"],"dateCreated":1519415695,"dateModified":1519416233,"policy":{"view":"public","edit":"no-one"}},"attachments":[]}],"maps":[],"query":{"queryKey":null},"cursor":{"limit":100,"after":null,"before":null,"order":null}}}
"""

CONDUIT_EDIT_OUTPUT = """
{"error":null,"errorMessage":null,"response":{"object":{"id":3643,"phid":"PHID-DREV-4pi6s6fwd57bktfzvfns"},"transactions":[{"phid":"PHID-XACT-DREV-om5mlg2ib34yaoi"},{"phid":"PHID-XACT-DREV-2pzq4qktezb7qqc"}]}}
"""

GIT_DIFF_FILES_CHANGES = """
M	src/libANGLE/renderer/vulkan/VertexArrayVk.cpp
M	src/tests/gl_tests/StateChangeTest1.cpp
A	src/tests/gl_tests/StateChangeTest2.cpp
D	src/tests/gl_tests/StateChangeTest3.cpp
R	src/tests/gl_tests/StateChangeTest4.cpp
Q	src/tests/gl_tests/StateChangeTest5.cpp
"""

GIT_COMMIT_BODY = """
If glBufferSubData results in a new vk::BufferHelper allocation,
VertexArrayVk::mCurrentElementArrayBuffer needs to be updated.
VertexArrayVk::syncState was working under the assumption that
DIRTY_BIT_ELEMENT_ARRAY_BUFFER_DATA cannot result in a vk::BufferHelper
pointer change.

This assumption was broken in
https://chromium-review.googlesource.com/c/angle/angle/+/2204655.

Bug: b/178231226
Change-Id: I969549c5ffec3456bdc08ac3e03a0fa0e7b4593f
(cherry picked from commit bb062070cb5257098f0e2d775fa66b74d6d32468)
Reviewed-on: https://chromium-review.googlesource.com/c/angle/angle/+/2693346
Reviewed-by: Jamie Madill <jmadill@chromium.org>
Commit-Queue: Jamie Madill <jmadill@chromium.org>
"""
