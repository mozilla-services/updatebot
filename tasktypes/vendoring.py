#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import copy
import functools
import os
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta

from tasktypes.base import BaseTaskRunner
from apis.phabricator import ArcNeedsInputError, DiffTooLargeError
from apis.taskcluster import Classification, TryPushNotFoundError, TryTreeClosedError
from components.bugzilla import CommentTemplates
from components.mach_vendor import VendorResult
from components.dbmodels import JOBSTATUS, JOBOUTCOME, JOBTYPE
from components.logging import LogLevel, logEntryExit, logEntryExitNoArgs
from components.scmprovider import CommitTemplates


class VendoringUtilities:
    # Upstream's license files are usually named like these (LICENSE.txt, COPYING.LIB,
    # LICENSE_FOXIT, ...); moz.yaml's license-file covers any that aren't.
    LICENSE_FILE_NAME = re.compile(r"^(LICEN[CS]E|COPYING|COPYRIGHT|NOTICE|UNLICENSE)", re.IGNORECASE)

    @staticmethod
    def give_up(vendoring_task, job, library, outcome, comment):
        # Mark a new job done with outcome, and tell the maintainer why on its bug
        vendoring_task.dbProvider.update_job_status(job, JOBSTATUS.DONE, outcome)
        vendoring_task.bugzillaProvider.comment_on_bug(job.bugzilla_id, comment, needinfo=library.maintainer_bz)

    @staticmethod
    @logEntryExit
    def reset_for_new_job(vendoring_task):
        # Remove the commits made processing this library, if there are any
        vendoring_task.logger.log("Removing any outgoing commits before moving on.", level=LogLevel.Info)

        # If we are on TC, update to the HEAD commit to avoid stripping WIP commits on holly
        status = vendoring_task.cmdProvider.run(["hg", "status"]).stdout
        head = os.environ.get("GECKO_HEAD_REV", "")
        if not status.strip() and head and vendoring_task.cmdProvider.run(["hg", "log", "-r", ".", "-T", "{node}"]).stdout.strip() == head:
            # Most jobs we look at don't touch the checkout, and a full reset takes ~20s
            vendoring_task.logger.log("The working directory is clean and at %s, so there's nothing to reset." % head[:12], level=LogLevel.Info)
            return
        vendoring_task.mercurialProvider.reset_repository()

    @staticmethod
    def has_commandeered_revision(vendoring_task, job):
        for p in job.phab_revisions:
            try:
                if vendoring_task.phabricatorProvider.is_commandeered(p.revision):
                    return True
            except Exception as e:
                # If we can't tell, close the bug as we always have
                vendoring_task.logger.log_exception(e)
        return False

    @staticmethod
    @logEntryExit
    def changed_license_files(vendoring_task, library, since):
        license_file = os.path.normpath(os.path.join(library.vendor_directory, library.license_file)) if library.license_file else None
        return [f for f in vendoring_task.mercurialProvider.changed_files_in(library.vendor_directory, since)
                if VendoringUtilities.LICENSE_FILE_NAME.match(os.path.basename(f)) or os.path.normpath(f) == license_file]

    @staticmethod
    def exception_message(e):
        # A failed command's output, or any other exception's message, for a bug comment
        if isinstance(e, subprocess.CalledProcessError):
            msg = ("stderr:\n" + e.stderr.rstrip() + "\n\n") if e.stderr else ""
            msg += ("stdout:\n" + e.stdout.rstrip()) if e.stdout else ""
            return msg
        return str(e)


# A try push this old that has no results on Treeherder never will. (Results for a
# new push appear within minutes.)
TRY_RESULTS_GONE_DAYS = 7


class VendorTaskRunner(BaseTaskRunner):
    def __init__(self, provider_dictionary, config_dictionary):
        self.jobType = JOBTYPE.VENDORING
        self.__dict__.update(provider_dictionary)
        self.logger = copy.deepcopy(self.loggingProvider)
        self.logger.log = functools.partial(self.logger.log, category=self.__class__.mro()[0].__name__)
        self.config = config_dictionary

    # ====================================================================

    def process_task(self, library, task):
        assert task.type == 'vendoring'

        # Collect all the existing jobs, and figure out which have open bugs
        all_jobs = self.dbProvider.get_all_jobs_for_library(library, JOBTYPE.VENDORING)
        open_bugs = self.bugzillaProvider.find_open_bugs_info([j.bugzilla_id for j in all_jobs])
        for j in all_jobs:
            j.bugzilla_is_open = j.bugzilla_id in open_bugs
            j.bugzilla_assignee = open_bugs[j.bugzilla_id]['assigned_to_detail']['email'] if j.bugzilla_id in open_bugs else None
            j.bugzilla_assignee = None if j.bugzilla_assignee in ["nobody@mozilla.org", "update-bot@bmo.tld"] else j.bugzilla_assignee

        # Get the list of all jobs we want to do something about
        all_jobs_not_done = [j for j in all_jobs if j.status != JOBSTATUS.DONE or j.bugzilla_is_open]

        # Then process all of them
        for j in all_jobs_not_done:
            self.logger.set_context(library.name, j.id)
            self.logger.log("Processing job id %s for %s which is currently %s and has a %s bug" % (j.id, library.name, j.status.name, "open" if j.bugzilla_is_open else "closed"))
            self._process_existing_job(library, task, j)
            VendoringUtilities.reset_for_new_job(self)
        self.logger.set_context(library.name)

        # See if we have a new upstream commit to process
        new_version, timestamp = self.vendorProvider.check_for_update(library)
        if not new_version:
            self.logger.log("No new version for %s was found." % library.name, level=LogLevel.Info)
            return

        # Then see if we already made a job for it.
        existing_job = [j for j in all_jobs if j.version == new_version]
        assert len(existing_job) < 2, "We found more than two jobs for version %s" % new_version
        if any(existing_job):
            existing_job = existing_job[0]
            self.logger.log("Job id %s was already created for the latest upstream revision %s" % (existing_job.id, new_version), level=LogLevel.Info)
            return

        # We didn't, so we'll process it, but first:
        # sanity-check - there should be at most one non-relinquished job, and if it is present, it should be the most recent.
        non_relinquished_jobs = [j for j in all_jobs if not j.relinquished]
        assert len(non_relinquished_jobs) <= 1, "We got more than one non-relinquished job: %s" % non_relinquished_jobs

        most_recent_job = all_jobs[0] if all_jobs else None
        assert most_recent_job is None or 0 == len(non_relinquished_jobs) or (len(non_relinquished_jobs) == 1 and most_recent_job == non_relinquished_jobs[0]), \
            "Most Recent Job is %s, we have %s non-relinquished jobs (%s), and they don't match." % (
            most_recent_job.id if most_recent_job else "nothing",
            len(non_relinquished_jobs), non_relinquished_jobs)

        # Now process it.
        self.logger.log("Processing %s for a new upstream revision %s, the most recent job is %s." % (library.name, new_version, most_recent_job.id if most_recent_job else "(none)"), level=LogLevel.Info)
        self._process_new_job(library, task, new_version, timestamp, most_recent_job)
        VendoringUtilities.reset_for_new_job(self)

    # ====================================================================
    @logEntryExit
    def _create_job_and_file_bug(self, library, task, new_version, timestamp, most_recent_job, start, messages):
        """
        Create the job for a new version that changes something, file its bug, deal
        with the prior job's, and give the commits made since start their messages,
        which need the bug number: messages(job) returns them, oldest first. Any uncommitted changes, from a stage that failed,
        are counted in the bug's description and then discarded.
        """
        created_job = self.dbProvider.create_job(JOBTYPE.VENDORING, library, new_version, JOBSTATUS.CREATED, JOBOUTCOME.PENDING)
        self.logger.set_context(library.name, created_job.id)

        # File the bug ------------------------
        commit_stats = self.mercurialProvider.diff_stats(start)
        license_files = VendoringUtilities.changed_license_files(self, library, start)
        if license_files:
            self.logger.log("This update changes the license files %s." % ", ".join(license_files), level=LogLevel.Info)
        license_note = CommentTemplates.LICENSE_FILES_CHANGED(license_files) if license_files else ""
        try:
            all_upstream_commits, unseen_upstream_commits = self.scmProvider.check_for_update(library, task, new_version, most_recent_job.version if most_recent_job else None)
            if library.should_show_commit_details:
                author_summary = self.scmProvider.build_author_summary(all_upstream_commits)
                commit_chunks = self.scmProvider.build_bug_description(all_upstream_commits, 65534 - len(commit_stats) - len(author_summary) - len(license_note) - 220, library.repo_url, options=task.options, new_commits=unseen_upstream_commits, compare_range=(library.revision, new_version))
            else:
                author_summary = ""
                commit_chunks = [""]
            bug_description = CommentTemplates.UPDATE_DETAILS(len(all_upstream_commits), len(unseen_upstream_commits), commit_stats, commit_chunks[0], author_summary)
        except Exception as e:
            # Listing the upstream commits means cloning the upstream repo, which
            # fails if its host is down. Still file the bug: the job already exists,
            # and without a bug a later run would treat this version as handled.
            self.logger.log("Could not get the upstream commits for %s; filing the bug without them: %s" % (library.name, e), level=LogLevel.Warning)
            commit_chunks = [""]
            bug_description = CommentTemplates.UPDATE_DETAILS_WITHOUT_COMMITS(library, commit_stats, VendoringUtilities.exception_message(e))
        bug_description = license_note + bug_description

        created_job.bugzilla_id = self.bugzillaProvider.file_bug(library, CommentTemplates.UPDATE_SUMMARY(library, new_version, timestamp), bug_description, task.cc, blocks=task.blocking)
        self.dbProvider.update_job_add_bug_id(created_job, created_job.bugzilla_id)
        for chunk in commit_chunks[1:]:
            self.bugzillaProvider.comment_on_bug(created_job.bugzilla_id, chunk)

        # Address any prior bug ---------------
        if most_recent_job and not most_recent_job.relinquished:
            self._process_prior_job(most_recent_job, created_job.bugzilla_id)

        # Reword the commits ------------------
        try:
            self.mercurialProvider.discard_working_directory()
            self.mercurialProvider.reword_commits_since(start, messages(created_job))
        except Exception as e:
            VendoringUtilities.give_up(self, created_job, library, JOBOUTCOME.COULD_NOT_COMMIT, CommentTemplates.COULD_NOT_GENERAL_ERROR("commit the updated library."))
            raise e
        return created_job

    @logEntryExit
    def _ai_fix_stage(self, job, library, stage, index, new_version, msg):
        """
        Ask the AI to fix the patches of a stage that failed with msg. Returns
        whether it committed a fix, after which the library's stages are re-read;
        if not, the job has been given up on.
        """
        gecko_path = self.config['General'].get('gecko-path')
        self.mercurialProvider.discard_working_directory()
        before = self.mercurialProvider.current_revision()
        revision_before = self.libraryProvider.read_revision(gecko_path, library)
        outcome, details = self.aiProvider.resolve_patch_conflicts(
            library, stage, self.vendorProvider.stage_command(library, index, new_version),
            "Bug %s - Update %s local patches to apply cleanly" % (job.bugzilla_id, library.name),
            cwd=gecko_path, job_id=job.id)

        if outcome == "failure":
            VendoringUtilities.give_up(self, job, library, JOBOUTCOME.COULD_NOT_PATCH, CommentTemplates.COULD_NOT_GENERAL_ERROR_WITH_AI(
                "%s." % CommitTemplates.STAGE_TASK_FOR_BUG_COMMENT(stage), initialerrormessage=msg, ai_outcome=outcome, ai_details=details))
            return False
        # Its fix has to be one commit on top of ours: anything uncommitted is discarded,
        # and the Phabricator submission counts on one commit per fix
        ai_commits = self.mercurialProvider.commits_since(before)
        if len(ai_commits) != 1:
            self.logger.log_exception(Exception("The AI reported '%s' for %s's '%s' stage but made %s commits on top of ours, not one." % (outcome, library.name, stage['name'], len(ai_commits))))
            VendoringUtilities.give_up(self, job, library, JOBOUTCOME.COULD_NOT_PATCH, CommentTemplates.AI_DIDNT_COMMIT(CommitTemplates.STAGE_TASK_FOR_BUG_COMMENT(stage), outcome, details))
            return False

        self.mercurialProvider.discard_working_directory()
        try:
            self.libraryProvider.reload_stages(gecko_path, library)
        except Exception as e:
            # The AI may have broken the moz.yaml
            VendoringUtilities.give_up(self, job, library, JOBOUTCOME.COULD_NOT_PATCH, CommentTemplates.COULD_NOT_GENERAL_ERROR(
                "%s even after AI conflict resolution." % CommitTemplates.STAGE_TASK_FOR_BUG_COMMENT(stage), errormessage=VendoringUtilities.exception_message(e)))
            return False
        assert self.libraryProvider.read_revision(gecko_path, library) == revision_before, "The AI's fix for %s's '%s' stage changed the moz.yaml's revision from %s to %s" % (
            library.name, stage['name'], revision_before, self.libraryProvider.read_revision(gecko_path, library))

        self.bugzillaProvider.comment_on_bug(job.bugzilla_id, CommentTemplates.AI_RESOLVED_PATCH_CONFLICTS(outcome, details),
                                             needinfo=library.maintainer_bz if outcome == "uncertain success" else None)
        return True

    # ====================================================================

    @logEntryExit
    def _process_prior_job(self, prior_job, superseceding_bugzilla_id):
        self.logger.log("The prior job id %s is not relinquished, so processing it." % prior_job.id, level=LogLevel.Info)

        if not prior_job.bugzilla_is_open or self.bugzillaProvider.bug_has_landing_link(prior_job.bugzilla_id):
            self.logger.log("The prior job's bugzilla bug is closed or about to be closed, so we only need to relinquish it.", level=LogLevel.Info)
        elif superseceding_bugzilla_id and VendoringUtilities.has_commandeered_revision(self, prior_job):
            # Someone is working on the revision themselves, so it isn't ours to close
            self.logger.log("The prior job's phabricator revision has been commandeered, so we're leaving its bug open.", level=LogLevel.Info)
            self.bugzillaProvider.comment_on_bug(prior_job.bugzilla_id, CommentTemplates.BUG_SUPERSEDED_BUT_COMMANDEERED(superseceding_bugzilla_id))
        elif superseceding_bugzilla_id:
            self.logger.log("The prior job's bugzilla bug is open, marking it as superseded by Bug ID %s ." % superseceding_bugzilla_id, level=LogLevel.Info)

            self.bugzillaProvider.dupe_bug(prior_job.bugzilla_id, CommentTemplates.BUG_SUPERSEDED(), superseceding_bugzilla_id)
            if prior_job.phab_revisions:
                for p in prior_job.phab_revisions:
                    try:
                        self.phabricatorProvider.abandon(p.revision)
                    except Exception as e:
                        self.bugzillaProvider.comment_on_bug(prior_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("abandon the phabricator patch %s." % p.revision))
                        self.logger.log_exception(e)  # We're going to log this exception, but not stop processing the new job

        self.dbProvider.update_job_relinquish(prior_job)

    @logEntryExit
    def _process_new_job(self, library, task, new_version, timestamp, most_recent_job):
        if not self._should_process_new_job(library, task, new_version):
            self.logger.log("Because of the task's frequency restrictions (%s) we are not processing this new revision now." % task.frequency, level=LogLevel.Info)
            return

        if most_recent_job and not most_recent_job.relinquished and most_recent_job.bugzilla_is_open and most_recent_job.bugzilla_id and self.bugzillaProvider.bug_has_landing_link(most_recent_job.bugzilla_id):
            self.logger.log(
                "The most recent bugzilla bug (%s) has a landing link, so we are not creating a new bug." % most_recent_job.bugzilla_id,
                level=LogLevel.Info)
            return

        # The AI's fixes can change the library's stages, which mustn't outlive this job
        library = copy.copy(library)

        # Vendor ------------------------------
        # Each stage is run with `./mach vendor --stage N` and committed, so the next
        # runs on top of it. Until a stage fails, or they've all run and changed
        # something, there's no job or bug, so the commits have temporary messages.
        start = self.mercurialProvider.current_revision()
        commits = []  # ('stage', index) or ('ai', index), oldest first
        created_job = None
        ai_tried = set()  # The AI gets one try at each stage whose patches don't apply

        def final_message(bug_id, index):
            return "Bug %s - %s" % (bug_id, CommitTemplates.STAGE_COMMIT_MESSAGE(library, index, new_version))

        def message(index):
            if not created_job:
                return "Updatebot: vendoring stage %s" % (index + 1)
            return final_message(created_job.bugzilla_id, index)

        def create_job_and_file_bug():
            assert created_job is None, "Already created job %s for %s %s" % (created_job.id, library.name, new_version)
            return self._create_job_and_file_bug(library, task, new_version, timestamp, most_recent_job, start,
                                                 lambda job: [final_message(job.bugzilla_id, i) for (_, i) in commits])

        index = 0
        while index < len(library.stages):
            stage = library.stages[index]
            (result, msg) = self.vendorProvider.vendor_stage(library, index, new_version)

            if result == VendorResult.SPURIOUS_UPDATE:
                # Only mach's old format exits like this, from its first stage
                assert index == 0, "mach reported a spurious update from %s's stage %s, not its first" % (library.name, index + 1)
                self.logger.log("Version %s was a spurious update." % new_version, level=LogLevel.Info)
                self.mercurialProvider.strip_commits_since(start)
                self.mercurialProvider.reset_repository()
                return

            if result in (VendorResult.GENERAL_ERROR, VendorResult.PATCH_CONFLICT) and not created_job:
                # If a stage failed, it will never be a spurious update, so create the bug
                # and we'll be attaching something.
                created_job = create_job_and_file_bug()

            if result == VendorResult.GENERAL_ERROR:
                if index == 0:
                    return VendoringUtilities.give_up(self, created_job, library, JOBOUTCOME.COULD_NOT_VENDOR, CommentTemplates.COULD_NOT_VENDOR(library, new_version, msg))
                return VendoringUtilities.give_up(self, created_job, library, JOBOUTCOME.COULD_NOT_PATCH, CommentTemplates.COULD_NOT_GENERAL_ERROR(
                    "%s (this wasn't a patch conflict, so Updatebot didn't ask its AI assistant to resolve it)" % CommitTemplates.STAGE_TASK_FOR_BUG_COMMENT(stage), errormessage=msg))
            elif result == VendorResult.PATCH_CONFLICT:
                if stage['name'] in ai_tried:
                    # AI Conflict resolution succeeded previously, but the stage still failed.
                    return VendoringUtilities.give_up(self, created_job, library, JOBOUTCOME.COULD_NOT_PATCH, CommentTemplates.COULD_NOT_GENERAL_ERROR(
                        "%s even after AI conflict resolution." % CommitTemplates.STAGE_TASK_FOR_BUG_COMMENT(stage), errormessage=msg))

                if not self._ai_fix_stage(created_job, library, stage, index, new_version, msg):
                    return

                # AI Conflict resolution seemed to work, so mark this stage as tried and record its commit
                ai_tried.add(stage['name'])
                commits.append(('ai', index))

                # We either re-run this stage if it still exists, or move on to the next one
                names = [s['name'] for s in library.stages]
                index = names.index(stage['name']) if stage['name'] in names else index
                continue

            # Commit ------------------------------
            try:
                committed = self.mercurialProvider.commit_stage(library, index, message(index))
            except Exception as e:
                if not created_job:
                    created_job = create_job_and_file_bug()
                commit_msg = "commit the updated library." if index == 0 else "commit after the '%s' vendoring stage." % stage['name']
                VendoringUtilities.give_up(self, created_job, library, JOBOUTCOME.COULD_NOT_COMMIT if index == 0 else JOBOUTCOME.COULD_NOT_COMMIT_PATCHES, CommentTemplates.COULD_NOT_GENERAL_ERROR(commit_msg))
                raise e
            if committed:
                commits.append(('stage', index))
            else:
                self.logger.log("The '%s' stage changed nothing, so there's nothing to commit." % stage['name'], level=LogLevel.Info)

            if result == VendorResult.MOZBUILD_ERROR:
                # The stage ran, so it's committed (before creating the job, which discards
                # uncommitted changes). Comment, but do not abort.
                if not created_job:
                    created_job = create_job_and_file_bug()
                self.bugzillaProvider.comment_on_bug(created_job.bugzilla_id, CommentTemplates.COULD_NOT_VENDOR_ALL_FILES(library, new_version, msg))
            index += 1

        # Check for spurious update -----------
        if not created_job:
            if not self.mercurialProvider.changes_since(start, exclude=[library.yaml_path] + library.generated):
                self.logger.log("Version %s changes nothing once every vendoring stage has run, so it was a spurious update." % new_version, level=LogLevel.Info)
                self.mercurialProvider.strip_commits_since(start)
                self.mercurialProvider.reset_repository()
                return
            created_job = create_job_and_file_bug()

        # The first stage always updates the moz.yaml's revision, so there's a commit to submit
        assert commits, "Job %s for %s %s has no commits to submit" % (created_job.id, library.name, new_version)
        assert len(self.mercurialProvider.commits_since(start)) == len(commits), "Job %s for %s %s made %s commits, but recorded %s" % (
            created_job.id, library.name, new_version, len(self.mercurialProvider.commits_since(start)), len(commits))

        # Submit to Try -----------------------
        try:
            try_revision = self.taskclusterProvider.submit_to_try(library)
            self.dbProvider.add_try_run(created_job, try_revision, 'all platforms')
            self.dbProvider.update_job_status(created_job, newstatus=JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS)
            self.bugzillaProvider.comment_on_bug(created_job.bugzilla_id, CommentTemplates.TRY_RUN_SUBMITTED(try_revision))
        except TryTreeClosedError as e:
            # Not an Updatebot failure: explain on the bug and carry on to Phabricator without a try run.
            self.logger.log(str(e), level=LogLevel.Warning)
            self.dbProvider.update_job_status(created_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY)
            self.bugzillaProvider.comment_on_bug(created_job.bugzilla_id, CommentTemplates.TRY_CLOSED(e.reason, e.try_command), needinfo=library.maintainer_bz)
        except Exception as e:
            VendoringUtilities.give_up(self, created_job, library, JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY, CommentTemplates.COULD_NOT_GENERAL_ERROR("submit to try."))
            raise e

        # Submit Phab Revision ----------------
        try:
            # A commit for each stage that changed something, plus one for each fix
            # from the AI.
            num_commits = len(commits)
            phab_revisions = self.phabricatorProvider.submit_patches(created_job.bugzilla_id, num_commits)
            assert len(phab_revisions) == num_commits, "We don't have the correct number of phabricator patches; we have %s, expected %s" % (len(phab_revisions), num_commits)
            # Revisions come back bottom-up, matching the order the commits were made.
            purposes = [CommitTemplates.PHAB_REVISION_PURPOSE(library, c) for c in commits]
            for revision, purpose in zip(phab_revisions, purposes):
                self.dbProvider.add_phab_revision(created_job, revision, purpose)
        except DiffTooLargeError as e:
            VendoringUtilities.give_up(self, created_job, library, JOBOUTCOME.COULD_NOT_SUBMIT_TO_PHAB, CommentTemplates.COULD_NOT_SUBMIT_DIFF_TOO_LARGE(library, new_version, str(e)))
            self.logger.log(str(e), level=LogLevel.Warning)
        except Exception as e:
            errormessage = str(e) if isinstance(e, ArcNeedsInputError) else None
            VendoringUtilities.give_up(self, created_job, library, JOBOUTCOME.COULD_NOT_SUBMIT_TO_PHAB, CommentTemplates.COULD_NOT_GENERAL_ERROR("submit to phabricator.", errormessage))
            raise e

    # ====================================================================
    # ====================================================================

    @logEntryExit
    def _process_existing_job(self, library, task, existing_job):
        """
        AWAITING_SECOND_PLATFORMS_TRY_RESULTS (the try run, despite the name)
          If we see still-running jobs, keep state as-is, and finish.
          If we see a build failure, comment, set assignee, needinfo, and state to JOB_PROCESSING_DONE. Finish.
          If we see test failures, accumulate them all, then retrigger each TRIGGER_TOTAL-1 times, set state to AWAITING_RETRIGGER_RESULTS. Finish
          If we see a lint failure, add ths note to a comment we will post.
          If we see a failures labeled intermittent, add this note to a comment we will post.
          If we have a comment accumulated, post it, set assignee, needinfo, set reviewer, and set state to JOB_PROCESSING_DONE
          If we have no comment accumulated, post that everything succeeded, set assignee, reviewer, and set state to JOB_PROCESSING_DONE

        AWAITING_RETRIGGER_RESULTS
          For every test failure, find the other failures.
            If every job in this set failed, add this note to a comment we will post.
            If some of the jobs succeeded, add this note to a comment we will post.
          Post the comment, set assignee, needinfo, set reviewr, and set state to JOB_PROCESSING_DONE
        """
        my_ff_version = self.config['General']['ff-version']

        if existing_job.status == JOBSTATUS.CREATED:
            # The job has been created; but for some reason was never set to a final status
            # (This has been observed when the worker the cronjob was running on shut down in the middle)
            self.logger.log("On job id %s for library %s revision %s we encountered an unexpected state." % (
                existing_job.id, existing_job.library_shortname, existing_job.version), level=LogLevel.Warning)
            if existing_job.bugzilla_id:
                self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.UNEXPECTED_JOB_STATE())

            self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.UNEXPECTED_CREATED_STATUS)
            self.dbProvider.update_job_relinquish(existing_job)

            # We also need to address the job _prior_ to this one and relinquish it as well to ensure that there is
            # at most one non-relinquished job and if present, it is the most recent
            if existing_job.prior_job and not existing_job.prior_job.relinquished:
                self._process_prior_job(existing_job.prior_job, existing_job.bugzilla_id)

            raise Exception("Handled a Job with unexpected CREATED status in _process_existing_job")

        elif existing_job.status == JOBSTATUS.DONE:
            assert existing_job.bugzilla_is_open, "We are processing a job %s that is Done and the bugzilla bug is closed" % existing_job.id
            # The job has been completed, but the bugzilla bug is open and we need to double check if it has acknowleged our current FF version

            if my_ff_version in existing_job.ff_versions:
                self.logger.log("We found a job with id %s for revision %s that was already processed for this ff version (%s)." % (
                    existing_job.id, existing_job.version, my_ff_version), level=LogLevel.Info)
                return

            if existing_job.outcome in [JOBOUTCOME.SPURIOUS_UPDATE]:
                self.logger.log("We found a job with id %s for revision %s but its outcome (%s) is not relevant for firefox tracking." % (
                    existing_job.id, existing_job.version, existing_job.outcome.name), level=LogLevel.Info)
                return

            if not existing_job.bugzilla_id:
                raise Exception("We found a job with id %s for revision %s and we should mark a ff version for tracking but it does not have a bugzilla ID." % (
                    existing_job.id, existing_job.version))

            self.logger.log("We found a job with id %s for revision %s but it hasn't been processed for this ff version (%s) yet." % (
                existing_job.id, existing_job.version, my_ff_version), level=LogLevel.Info)
            self.bugzillaProvider.mark_ff_version_affected(existing_job.bugzilla_id, my_ff_version, affected=True)

            self.dbProvider.update_job_ff_versions(existing_job, my_ff_version)
            existing_job.ff_versions.add(my_ff_version)
            return

        elif existing_job.status in (JOBSTATUS.RELINQUISHED, JOBSTATUS.AWAITING_INITIAL_PLATFORM_TRY_RESULTS):
            self.logger.log("Job ID %s has the (obsolete) status %s so I am not going to try to process it." % (existing_job.id, existing_job.status.name), level=LogLevel.Info)
            if not existing_job.bugzilla_is_open:
                # Nothing will ever happen to it, so stop looking at it every run
                self.logger.log("Its bug is closed, so marking it done.", level=LogLevel.Info)
                self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE)
        else:
            assert len(existing_job.try_runs) == 1, "Status is %s, but we have %s try runs, not 1 (%s)." % (existing_job.status.name, len(existing_job.try_runs), existing_job.get_try_run_ids())

            if existing_job.status == JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS:
                self._process_job_details_for_awaiting_second_platform_results(library, task, existing_job)
            elif existing_job.status == JOBSTATUS.AWAITING_RETRIGGER_RESULTS:
                self._process_job_details_for_awaiting_retrigger_results(library, task, existing_job)
            else:
                raise Exception("In _process_job_details for job with try revisions %s got a status %s I don't know how to handle." % (existing_job.get_try_run_ids(), existing_job.status.name))

    # ==================================

    # Returns (no_build_failures, results, comment_lines)
    @logEntryExit
    def _get_comments_on_push(self, library, existing_job):
        # Fetch the job list (and double check its status), and the push health
        try_revision = existing_job.try_runs[0].revision
        try:
            job_list = self.taskclusterProvider.get_job_details(try_revision)
        except TryPushNotFoundError as e:
            # A push old enough to be gone has no jobs left either
            self.logger.log(str(e), level=LogLevel.Info)
            job_list = []

        if not self._job_is_completed_without_build_failures(library, existing_job, job_list):
            return (False, None, None)

        push_health = self.taskclusterProvider.get_push_health(try_revision)

        results = self.taskclusterProvider.determine_jobs_to_retrigger(push_health, job_list)

        def get_failed_summary_string(result_obj, include_task_ids):
            fails_tuple = (len(result_obj.failed()), len(result_obj.all()))
            if len(result_obj.all()) == 1:
                result = "%s of %s failed" % fails_tuple
            elif len(set([j.job_type_name for j in result_obj.all()])) != 1:
                result = "%s of %s failed on different tasks" % fails_tuple
            else:
                result = "%s of %s failed on the same (retriggered) task" % fails_tuple
            if include_task_ids:
                result += " (failed: " + ", ".join([j.task_id for j in result_obj.failed()]) + ")"

            return result

        # Once (Bug 1804797) push health returned an odd name I hadn't seen before
        # this function handles this scenario so the comment is readable
        def handle_multiline_name(s):
            if "\n" not in s:
                return s
            return "> " + s.replace("\n", "\n  > ")

        task_ids_weve_reported = set()

        # The order in which we go through the results matter, and is tied to the priority we want to give to the classifications.
        # For example, if Push Health says something is a New Failure, but Taskcluster says it's NotYourFault.
        # Our Priority List is: NotYourFault, NewFailure, Possible Intermittent

        # First lint failures though.
        lint_lines = ["**Lint Jobs Failed**"]
        for j in job_list:
            if j.result not in ["retry", "success"]:
                if "mozlint" in j.job_type_name:
                    task_ids_weve_reported.add(j.task_id)
                    lint_lines.append("- %s (%s)" % (j.job_type_name, j.task_id))

        # Then Not Your Fault
        not_your_fault_lines = ["**Known Issues**:"]
        for t in results['tasks_by_testname']:
            if not results['tasks_by_testname'][t].failed():
                continue
            if results['tasks_by_testname'][t].classification == Classification.NotYourFault:
                not_your_fault_lines.append("")
                not_your_fault_lines.append("- " + handle_multiline_name(t))
                for j in results['tasks_by_testname'][t].failed():
                    task_ids_weve_reported.add(j.task_id)
                    not_your_fault_lines.append("\t\t- %s (%s)" % (j.job_type_name, j.task_id))

        for t in results['tasks_by_jobname']:
            if not results['tasks_by_jobname'][t].failed():
                continue
            if results['tasks_by_jobname'][t].classification == Classification.NotYourFault:
                if set([j.task_id for j in results['tasks_by_jobname'][t].failed()]) - task_ids_weve_reported:
                    not_your_fault_lines.append("- " + handle_multiline_name(t) + " - " + get_failed_summary_string(results['tasks_by_jobname'][t], True))

        # Then New Failures
        high_priority_lines = ["**Needs Close Investigation**:"]
        for t in results['tasks_by_testname']:
            if not results['tasks_by_testname'][t].failed():
                continue
            if results['tasks_by_testname'][t].classification == Classification.NewFailure:
                high_priority_lines.append("")
                high_priority_lines.append("- " + handle_multiline_name(t))
                if len(results['tasks_by_testname'][t].all()) > 1:
                    high_priority_lines.append("  - " + get_failed_summary_string(results['tasks_by_testname'][t], False))
                for j in results['tasks_by_testname'][t].failed():
                    task_ids_weve_reported.add(j.task_id)
                    high_priority_lines.append("\t\t- %s (%s)" % (j.job_type_name, j.task_id))

        for t in results['tasks_by_jobname']:
            if not results['tasks_by_jobname'][t].failed():
                continue
            if results['tasks_by_jobname'][t].classification == Classification.NewFailure:
                # Only report this group if we haven't reported all the failed tasks already
                if set([j.task_id for j in results['tasks_by_jobname'][t].failed()]) - task_ids_weve_reported:
                    high_priority_lines.append("- " + handle_multiline_name(t) + " - " + get_failed_summary_string(results['tasks_by_jobname'][t], True))

        # Finally intermittents
        intermittent_lines = ["**Needs Investigation (Possible Intermittents)**:"]
        for t in results['tasks_by_testname']:
            if not results['tasks_by_testname'][t].failed():
                continue
            if results['tasks_by_testname'][t].classification == Classification.PossibleIntermittent:
                intermittent_lines.append("")
                intermittent_lines.append("- " + handle_multiline_name(t))
                if len(results['tasks_by_testname'][t].all()) > 1:
                    intermittent_lines.append("  - " + get_failed_summary_string(results['tasks_by_testname'][t], False))
                for j in results['tasks_by_testname'][t].failed():
                    task_ids_weve_reported.add(j.task_id)
                    intermittent_lines.append("\t\t- %s (%s)" % (j.job_type_name, j.task_id))

        for t in results['tasks_by_jobname']:
            if not results['tasks_by_jobname'][t].failed():
                continue
            if results['tasks_by_jobname'][t].classification == Classification.PossibleIntermittent:
                if set([j.task_id for j in results['tasks_by_jobname'][t].failed()]) - task_ids_weve_reported:
                    intermittent_lines.append("- " + handle_multiline_name(t) + " - " + get_failed_summary_string(results['tasks_by_jobname'][t], True))

        comment_lines = list()
        comment_lines.extend((lint_lines + [""]) if len(lint_lines) > 1 else [])
        comment_lines.extend((high_priority_lines + [""]) if len(high_priority_lines) > 1 else [])
        comment_lines.extend((intermittent_lines + [""]) if len(intermittent_lines) > 1 else [])
        comment_lines.extend((not_your_fault_lines + [""]) if len(not_your_fault_lines) > 1 else [])

        results['classifications'] = set()
        results['classifications'].add(Classification.NewFailure if len(high_priority_lines) > 1 else None)
        results['classifications'].add(Classification.PossibleIntermittent if len(intermittent_lines) > 1 else None)
        results['classifications'].add(Classification.NotYourFault if len(not_your_fault_lines) > 1 else None)

        return (True, results, comment_lines)

    @logEntryExitNoArgs
    def _job_is_completed_without_build_failures(self, library, existing_job, job_list):
        # Ignore unscheduled tasks. A build failure can leave the tasks that
        # depended on it in the 'unscheduled' state, where they never run and only
        # expire after ~28 days; counting them as "not yet completed" would keep us
        # waiting on the try run forever.
        job_list = [j for j in job_list if j.state != "unscheduled"]

        if not job_list:
            if not existing_job.bugzilla_is_open and existing_job.created < datetime.now() - timedelta(days=TRY_RESULTS_GONE_DAYS):
                # Treeherder no longer has the try push's results, and the bug is closed,
                # so nothing more can happen to this job. Stop looking at it every run.
                self.logger.log("Try revision had no job results, the job is from %s and its bug is closed, so marking it done." % existing_job.created, level=LogLevel.Info)
                self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE)
            else:
                self.logger.log("Try revision had no job results. Skipping this job.", level=LogLevel.Warning)
            return False

        # If there's only one job, and it's an exception we hit a really bad luck
        # case where the Decision task excepted. Ordinarily we would try to retrigger
        # it, but that will fail, so we should handle this case.
        if len(job_list) == 1 and job_list[0].result in ["exception", "busted"]:
            self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("submit to try. It appears that the Decision task did not succeed."), needinfo=library.maintainer_bz if existing_job.bugzilla_is_open else None)
            self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY)
            return False

        for j in job_list:
            if j.state not in ["completed", "failed", "exception"]:
                self.logger.log("Not all jobs on the try revision are completed, so skipping this job until they are.", level=LogLevel.Info)
                return False

        # First, look for build jobs that failed and never succeeded.
        builds_by_name = defaultdict(list)
        for j in job_list:
            if "build" in j.job_type_name and j.result != "retry":
                builds_by_name[j.job_type_name].append(j)
        failed_builds = [jobs for jobs in builds_by_name.values() if not any(j.result == "success" for j in jobs)]

        # If every failed build failed only once, with a known intermittent, retrigger them
        # once and check back. If the retrigger fails too, it's a build failure. (We only do
        # this for builds; see is_known_intermittent for why it isn't used for tests.)
        if failed_builds and existing_job.bugzilla_is_open:
            intermittent_builds = []
            for jobs in failed_builds:
                if len(jobs) == 1 and self.taskclusterProvider.is_known_intermittent(jobs[0]):
                    intermittent_builds.append(jobs[0])
                else:
                    break
            if len(intermittent_builds) == len(failed_builds):
                # Our retrigger shows up on the push as an 'Action: Retrigger' job. If there's one
                # already, don't retrigger again: if it succeeded the new builds just aren't
                # visible yet, and if it failed we treat it as a build failure. We only retrigger
                # tests once every build has succeeded, so any retrigger we made by now was of
                # builds; retriggers people made are ignored.
                retrigger_actions = [j for j in job_list if j.job_type_name == "Action: Retrigger" and self.taskclusterProvider.retrigger_was_automated(j)]
                if not retrigger_actions:
                    self.logger.log("Retriggering %s build(s) that failed with known intermittents: %s" % (
                        len(intermittent_builds), ", ".join(j.job_type_name for j in intermittent_builds)), level=LogLevel.Info)
                    self.taskclusterProvider.retrigger_jobs(intermittent_builds, times=1)
                    return False
                if all(j.result == "success" for j in retrigger_actions):
                    self.logger.log("We retriggered builds that failed with known intermittents, but the new builds aren't visible yet, so skipping this job until they are.", level=LogLevel.Info)
                    return False
                self.logger.log("The retrigger of builds that failed with known intermittents failed, so treating them as build failures.", level=LogLevel.Warning)

        if failed_builds:
            self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.DONE_BUILD_FAILURE(library, existing_job.version), needinfo=library.maintainer_bz if existing_job.bugzilla_is_open else None)
            if not existing_job.relinquished:
                for p in existing_job.phab_revisions:
                    try:
                        self.phabricatorProvider.abandon(p.revision)
                    except Exception:
                        self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("abandon the phabricator revision %s" % p.revision), needinfo=library.maintainer_bz)
            self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.BUILD_FAILED)
            return False

        return True

    # ==================================

    @logEntryExitNoArgs
    def _process_job_details_for_awaiting_second_platform_results(self, library, task, existing_job):
        try_revision = existing_job.try_runs[0].revision
        self.logger.log("Handling try revision %s in Awaiting Try Results" % try_revision, level=LogLevel.Info)

        # Get the push health and a comment string we may use in the bug.
        # Along the way, confirm that all the jobs have succeeded and there are no build failures
        no_build_failures, results, comment_lines = self._get_comments_on_push(library, existing_job)
        if not no_build_failures:
            return

        # If we need to retrigger jobs
        if results['to_retrigger'] and existing_job.bugzilla_is_open:
            self.logger.log("All jobs completed, we found failures we need to retrigger, going to retrigger %s jobs: " % len(results['to_retrigger']), level=LogLevel.Info)
            for j in results['to_retrigger']:
                self.logger.log(j.job_type_name + " " + j.task_id, level=LogLevel.Debug)
            self.taskclusterProvider.retrigger_jobs(results['to_retrigger'])
            self.dbProvider.update_job_status(existing_job, newstatus=JOBSTATUS.AWAITING_RETRIGGER_RESULTS)
            return
        elif results['to_retrigger']:
            self.logger.log("While there were things we'd retrigger, the bugzilla bug has been closed, so we will only summarize results.", level=LogLevel.Info)

        self._process_job_results(library, task, existing_job, results, comment_lines)

    # ==================================

    @logEntryExitNoArgs
    def _process_job_details_for_awaiting_retrigger_results(self, library, task, existing_job):
        self.logger.log("Handling try runs in Awaiting Retrigger Results")

        # Get the push health and a comment string we will use in the bug
        no_build_failures, results, comment_lines = self._get_comments_on_push(library, existing_job)
        if no_build_failures:
            self._process_job_results(library, task, existing_job, results, comment_lines)

    # ==================================

    @logEntryExitNoArgs
    def _process_job_results(self, library, task, existing_job, results, comment_lines):
        # We don't need to retrigger jobs, but we do have unclassified failures:
        if results['classifications'].intersection(set([Classification.PossibleIntermittent, Classification.NewFailure])):
            self._process_unclassified_failures(library, task, existing_job, comment_lines)

        # We don't need to retrigger and we don't have unclassified failures but we do have failures
        elif results['classifications'].intersection(set([Classification.NotYourFault])):
            self._process_classified_failures(library, task, existing_job, comment_lines)

        # Everything.... succeeded?
        else:
            self._process_success(library, task, existing_job, comment_lines)

    # ==================================

    @logEntryExitNoArgs
    def _process_unclassified_failures(self, library, task, existing_job, comment_lines):
        comment = "The try push is done, we found jobs with unclassified failures.\n\n"
        self.logger.log(comment.strip(), level=LogLevel.Info)

        for c in comment_lines:
            comment += c + "\n"
            self.logger.log(c, level=LogLevel.Debug)

        self.bugzillaProvider.comment_on_bug(
            existing_job.bugzilla_id,
            CommentTemplates.DONE_UNCLASSIFIED_FAILURE(comment, library, existing_job.version),
            needinfo=library.maintainer_bz if existing_job.bugzilla_is_open else None,
            assignee=(existing_job.bugzilla_assignee or library.maintainer_bz) if existing_job.bugzilla_is_open else None)

        self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.UNCLASSIFIED_FAILURES)

    # ==================================

    @logEntryExitNoArgs
    def _process_classified_failures(self, library, task, existing_job, comment_lines):
        comment = "All jobs completed, we found the following issues.\n\n"
        self.logger.log(comment.strip(), level=LogLevel.Info)

        for c in comment_lines:
            self.logger.log(c, level=LogLevel.Debug)
            comment += c + "\n"

        self.bugzillaProvider.comment_on_bug(
            existing_job.bugzilla_id,
            CommentTemplates.DONE_CLASSIFIED_FAILURE(comment, library, existing_job.version),
            assignee=(existing_job.bugzilla_assignee or library.maintainer_bz) if existing_job.bugzilla_is_open else None)

        self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.CLASSIFIED_FAILURES)

        if existing_job.bugzilla_is_open:
            try:
                for p in existing_job.phab_revisions:
                    self.phabricatorProvider.set_reviewer(p.revision, library.maintainer_phab)
            except Exception as e:
                self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_SET_PHAB_REVIEWER)
                self.bugzillaProvider.comment_on_bug(
                    existing_job.bugzilla_id,
                    CommentTemplates.COULD_NOT_GENERAL_ERROR("set you as a reviewer in phabricator."),
                    needinfo=library.maintainer_bz)
                raise e

    # ==================================

    @logEntryExitNoArgs
    def _process_success(self, library, task, existing_job, comment_lines):
        self.logger.log("All jobs completed and we got a clean try run!", level=LogLevel.Info)

        self.bugzillaProvider.comment_on_bug(
            existing_job.bugzilla_id,
            CommentTemplates.DONE_ALL_SUCCESS(),
            assignee=(existing_job.bugzilla_assignee or library.maintainer_bz) if existing_job.bugzilla_is_open else None)

        self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)

        if existing_job.bugzilla_is_open:
            try:
                for p in existing_job.phab_revisions:
                    self.phabricatorProvider.set_reviewer(p.revision, library.maintainer_phab)
            except Exception as e:
                self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_SET_PHAB_REVIEWER)
                self.bugzillaProvider.comment_on_bug(
                    existing_job.bugzilla_id,
                    CommentTemplates.COULD_NOT_GENERAL_ERROR("set you as a reviewer in phabricator."),
                    needinfo=library.maintainer_bz)
                raise e
