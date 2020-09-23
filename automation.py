#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys
from components.logging import LoggingProvider, SimpleLogger, LogLevel, SimpleLoggerConfig, logEntryExit, logEntryExitNoArgs
from components.commandprovider import CommandProvider
from components.dbc import DatabaseProvider
from components.dbmodels import JOBSTATUS, JOBOUTCOME
from components.mach_vendor import VendorProvider
from components.bugzilla import BugzillaProvider, CommentTemplates
from components.hg import MercurialProvider
from apis.taskcluster import TaskclusterProvider, TRIGGER_TOTAL
from apis.phabricator import PhabricatorProvider

DEFAULT_OBJECTS = {
    'Command': CommandProvider,
    'Logging': LoggingProvider,
    'Database': DatabaseProvider,
    'Vendor': VendorProvider,
    'Bugzilla': BugzillaProvider,
    'Mercurial': MercurialProvider,
    'Taskcluster': TaskclusterProvider,
    'Phabricator': PhabricatorProvider,
}


class Updatebot:
    def __init__(self, config_dictionary={}, object_dictionary={}):
        def _getOrImpl(dictionary, name, default):
            return dictionary[name] if name in dictionary else default

        def _getObjOr(name):
            assert(name in DEFAULT_OBJECTS)
            return _getOrImpl(object_dictionary, name, DEFAULT_OBJECTS[name])

        def _getConfigOr(name):
            result = _getOrImpl(config_dictionary, name, {})
            result.update({'General': config_dictionary['General']})
            return result

        def getOr(name):
            return _getObjOr(name)(_getConfigOr(name))

        # Pre-initialize this with a print-based logger for validation error output.
        self.logger = SimpleLogger()
        self.config_dictionary = config_dictionary
        self._validate(config_dictionary)

        """
        Provider initialization is complicated.

        Any provider may inherit from one or more INeeds interfaces. These interfaces
        provide access to other providers (called 'utility providers'.)

        If a utility provider never needed access to any other utility provider, it would
        be simple - but a utility provider may need access to other utility providers.
        And if the graph of utility provider dependencies had no cycles, it would also be
        simple. But we want to support that. So we do a phased initialization.

        Step 1: Instantiate the utility providers, passing them their configuration data
        Step 2: Create an additional_config that contains all the information any utility
                provider may need
        Step 3: Call update_config on all utility providers. For utility providers that
                subclass an INeeds class, this will populate their needed information.

        At this point we have set up all the utility providers and populated any cyclic
        dependencies.

        Step 4: Set up the logger, so we can capture exceptions
        Step 5: Instantiate the other providers (we call them functionality providers.)
                These providers should never depend on each other.
        Step 6: Call update_config on them as well to populate their INeeds superclasses.

        We store all providers in a provider_dictionary so its easy to iterate over them,
        but we also turn them into member variables for easier access (Step 7)
        """
        # Step 1
        self.provider_dictionary = {
            'cmdProvider': getOr('Command'),
            'loggingProvider': getOr('Logging')
        }
        # Step 2
        additional_config = {
            'LoggingProvider': self.provider_dictionary['loggingProvider'],
            'CommandProvider': self.provider_dictionary['cmdProvider']
        }
        # Step 3
        self.runOnProviders(lambda x: x.update_config(additional_config))

        # Step 4
        self.logger = self.provider_dictionary['loggingProvider']

        try:
            # Step 5
            self.provider_dictionary.update({
                'dbProvider': getOr('Database'),
                'vendorProvider': getOr('Vendor'),
                'bugzillaProvider': getOr('Bugzilla'),
                'mercurialProvider': getOr('Mercurial'),
                'taskclusterProvider': getOr('Taskcluster'),
                'phabricatorProvider': getOr('Phabricator'),
            })
            # Step 6
            self.runOnProviders(lambda x: x.update_config(additional_config))
            # Step 7
            self.__dict__.update(self.provider_dictionary)
            # And check the database
            self.dbProvider.check_database()
        except Exception as e:
            self.logger.log_exception(e)
            raise(e)

    def runOnProviders(self, func):
        for v in self.provider_dictionary.values():
            func(v)

    def _validate(self, config_dictionary):
        if 'General' not in config_dictionary:
            self.logger.log("'General' is a required config dictionary to supply.", level=LogLevel.Fatal)
            sys.exit(1)
        if 'gecko-path' not in config_dictionary['General']:
            self.logger.log("['General']['gecko-path'] probably should be defined in the config dictionary.", level=LogLevel.Warning)
        if 'env' not in config_dictionary['General']:
            self.logger.log("['General']['env'] must be defined in the config dictionary with a value of prod or dev.", level=LogLevel.Fatal)
            sys.exit(1)

    def run(self, library_filter=""):
        try:
            if 'gecko-path' in self.config_dictionary['General']:
                os.chdir(self.config_dictionary['General']['gecko-path'])

            libraries = self.dbProvider.get_libraries()
            for l in libraries:
                if library_filter and library_filter not in l.shortname:
                    self.logger.log("Skipping %s because it doesn't meet the filter '%s'" % (l.shortname, library_filter), level=LogLevel.Info)
                    continue
                try:
                    self._process_library(l)
                except Exception as e:
                    self.logger.log("Caught an exception while processing a library.", level=LogLevel.Error)
                    self.logger.log_exception(e)
        except Exception as e:
            self.logger.log_exception(e)
            raise(e)

    # ====================================================================

    def _process_library(self, library):
        new_version, timestamp = self.vendorProvider.check_for_update(library)
        if not new_version:
            self.logger.log("Processing %s but no new version was found." % library.shortname, level=LogLevel.Info)
            return

        self.logger.log("Processing %s for an upstream revision %s." % (library.shortname, new_version), level=LogLevel.Info)
        existing_job = self.dbProvider.get_job(library, new_version)
        if existing_job:
            self.logger.log("%s has an existing job with try revision %s and status %s" % (new_version, existing_job.try_revision, existing_job.status), level=LogLevel.Info)
            self._process_existing_job(library, existing_job)
        else:
            self.logger.log("%s is a brand new revision to updatebot." % (new_version), level=LogLevel.Info)
            self._process_new_job(library, new_version, timestamp)

    # ====================================================================

    @logEntryExit
    def _process_new_job(self, library, new_version, timestamp):
        see_also = []

        # First, we need to see if there was a previously active job for this library.
        # If so, we need to close that job out.
        active_jobs = self.dbProvider.get_all_active_jobs_for_library(library)
        assert len(active_jobs) <= 1, "Got more than one active job for library %s" % (library.shortname)
        self.logger.log("Found %i active jobs for this library" % len(active_jobs), level=LogLevel.Info)
        if len(active_jobs) == 1:
            active_job = active_jobs[0]
            self.bugzillaProvider.close_bug(active_job.bugzilla_id, CommentTemplates.BUG_SUPERSEDED())
            self.phabricatorProvider.abandon(active_job.phab_revision)
            active_job.status = JOBSTATUS.DONE
            active_job.outcome = JOBOUTCOME.ABORTED
            self.dbProvider.update_job_status(active_job)
            see_also.append(active_job.bugzilla_id)

        # Now we can process the new job
        bugzilla_id = self.bugzillaProvider.file_bug(library, new_version, timestamp, see_also)

        try:
            self.vendorProvider.vendor(library)
        except Exception:
            # Handle `./mach vendor` failing
            self.dbProvider.create_job(library, new_version, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_VENDOR, bugzilla_id, phab_revision=None)
            self.bugzillaProvider.comment_on_bug(bugzilla_id, CommentTemplates.COULD_NOT_VENDOR(""))  # TODO, put error message
            return

        self.mercurialProvider.commit(library, bugzilla_id, new_version)
        try_revision = self.taskclusterProvider.submit_to_try(library)

        self.bugzillaProvider.comment_on_bug(bugzilla_id, CommentTemplates.TRY_RUN_SUBMITTED(try_revision))
        phab_revision = self.phabricatorProvider.submit_patch()
        self.dbProvider.create_job(library, new_version, JOBSTATUS.AWAITING_TRY_RESULTS, JOBOUTCOME.PENDING, bugzilla_id, phab_revision, try_revision)

    # ====================================================================
    # ====================================================================

    @logEntryExit
    def _process_existing_job(self, library, existing_job):
        if existing_job.status == JOBSTATUS.DONE:
            self.logger.log("This job has already been completed")
            return

        try_run_results = self.taskclusterProvider.get_job_details(existing_job.try_revision)
        if not try_run_results:
            self.logger.log("Try revision %s has no job results. Skipping this job." % existing_job.try_revision, level=LogLevel.Warning)
            return

        self._process_job_details(library, existing_job, try_run_results)

    # ==================================

    @logEntryExitNoArgs
    def _process_job_details(self, library, existing_job, job_list):
        """
        AWAITING_TRY_RESULTS
          If we see a build failure, comment, set assignee, needinfo, and state to JOB_PROCESSING_DONE. Finish.
          If we see still-running jobs, keep state as-is, and finish.
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
        assert existing_job.status != JOBSTATUS.DONE
        for j in job_list:
            if j.state not in ["completed", "failed", "exception"]:
                self.logger.log("Not all jobs on try revision %s are completed, so skipping this job until they are." % existing_job.try_revision, level=LogLevel.Info)
                return

        if existing_job.status == JOBSTATUS.AWAITING_TRY_RESULTS:
            self._process_job_details_for_awaiting_try_results(library, existing_job, job_list)
        elif existing_job.status == JOBSTATUS.AWAITING_RETRIGGER_RESULTS:
            self._process_job_details_for_awaiting_retrigger_results(library, existing_job, job_list)
        else:
            raise Exception("In _process_job_details for job with try revision %s got a status %s I don't know how to handle." % (existing_job.try_revision, existing_job.status))

    # ==================================

    @logEntryExitNoArgs
    def _process_job_details_for_awaiting_try_results(self, library, existing_job, job_list):
        self.logger.log("Handling revision %s in Awaiting Try Results" % existing_job.try_revision)

        def handle_build_failure():
            self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.DONE_BUILD_FAILURE(library), needinfo=library.maintainer)
            self.phabricatorProvider.abandon(existing_job.phab_revision)
            existing_job.status = JOBSTATUS.DONE
            existing_job.outcome = JOBOUTCOME.BUILD_FAILED
            self.dbProvider.update_job_status(existing_job)
            return

        retriggers = []
        comment_bullets = []
        for j in job_list:
            if j.result not in ["retry", "success"]:
                classification = self.taskclusterProvider.failure_classifications[j.failure_classification_id]
                self.logger.log("  Job %s (%i) Failed, Classification: %s" % (j.job_type_name, j.id, classification), level=LogLevel.Debug)

                if classification == "not classified":
                    if "build" in j.job_type_name:
                        return handle_build_failure()
                    elif "mozlint" in j.job_type_name:
                        comment_bullets.append("lint job failed: %s" % j.job_type_name)
                    else:
                        retriggers.append(j)
                else:
                    comment_bullets.append("failure classified '%s': %s" % (classification, j.job_type_name))

        if retriggers:
            self.logger.log("All jobs completed, we found the following unclassified failures, going to retrigger %s jobs. " % len(retriggers), level=LogLevel.Info)
            self.taskclusterProvider.retrigger_jobs(job_list, retriggers)
            existing_job.status = JOBSTATUS.AWAITING_RETRIGGER_RESULTS
            self.dbProvider.update_job_status(existing_job)
            return

        if comment_bullets:
            comment = "All jobs completed, we found %i classified failures.\n" % len(comment_bullets)
            self.logger.log(comment, level=LogLevel.Info)
            existing_job.outcome = JOBOUTCOME.CLASSIFIED_FAILURES
            for c in comment_bullets:
                comment_line = "  - %s\n" % c

                comment += comment_line
                self.logger.log(comment_line.strip(), level=LogLevel.Debug)
            self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.DONE_CLASSIFIED_FAILURE(comment, library), needinfo=library.maintainer, assignee=library.maintainer)
            self.phabricatorProvider.set_reviewer(existing_job.phab_revision, library.maintainer_phab)
        else:
            self.logger.log("All jobs completed and we got a clean try run!", level=LogLevel.Info)
            existing_job.outcome = JOBOUTCOME.ALL_SUCCESS
            self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.DONE_ALL_SUCCESS(), assignee=library.maintainer)
            self.phabricatorProvider.set_reviewer(existing_job.phab_revision, library.maintainer_phab)

        existing_job.status = JOBSTATUS.DONE
        self.dbProvider.update_job_status(existing_job)

    # ==================================

    @logEntryExitNoArgs
    def _process_job_details_for_awaiting_retrigger_results(self, library, existing_job, job_list):
        self.logger.log("Handling revision %s in Awaiting Retrigger Results" % existing_job.try_revision)
        job_groups = {}

        # Group all the jobs into a list of the runs for each type
        for j in job_list:
            if j.job_type_name in job_groups:
                job_groups[j.job_type_name].append(j)
            else:
                job_groups[j.job_type_name] = [j]

        # Filter that list to only groups containing failures
        job_groups_with_failures = {k: v for (k, v) in job_groups.items() if any([j.result != "success" for j in v])}
        job_group_to_unclassified_failure_count = {k: 0 for k, v in job_groups_with_failures.items()}

        # Populate the mapping of job group to number of *unclassified* failures
        # (The unclassified bit is why this is a little more complicated than a one-liner, also I want the log output)
        for job_name in job_groups_with_failures:
            for job in job_groups_with_failures[job_name]:
                if job.result == "success":
                    continue

                classification = self.taskclusterProvider.failure_classifications[job.failure_classification_id]
                self.logger.log("  Job %s (%i) Failed, Classification: %s" % (job.job_type_name, job.id, classification), level=LogLevel.Debug)

                if classification == "not classified":
                    job_group_to_unclassified_failure_count[job.job_type_name] += 1

        # Comment on the bug
        comment_bullets = []
        for job_name in job_groups_with_failures:
            num_jobs_ran = len(job_groups_with_failures[job_name])

            if num_jobs_ran != TRIGGER_TOTAL and "mozlint" not in job_name:
                self.logger.log("Job Group %s has %i entries, doesn't match %i triggers." % (job_name, num_jobs_ran, TRIGGER_TOTAL), level=LogLevel.Error)

            comment_bullets.append("%i of %i jobs were unclassified failures in %s" % (job_group_to_unclassified_failure_count[job_name], len(job_groups_with_failures[job_name]), job_name))

        comment = "The try push is done, we found %i jobs with unclassified failures.\n" % len(comment_bullets)
        self.logger.log(comment.strip(), level=LogLevel.Info)
        for c in comment_bullets:
            comment_line = "  - %s\n" % c

            comment += comment_line
            self.logger.log(comment_line.strip(), level=LogLevel.Debug)

        self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.DONE_UNCLASSIFIED_FAILURE(comment, library), needinfo=library.maintainer)
        self.phabricatorProvider.abandon(existing_job.phab_revision)
        existing_job.outcome = JOBOUTCOME.UNCLASSIFIED_FAILURES
        existing_job.status = JOBSTATUS.DONE
        self.dbProvider.update_job_status(existing_job)


# ====================================================================
# ====================================================================

if __name__ == "__main__":
    import argparse
    try:
        from localconfig import localconfig
    except ImportError as e:
        print("Execution requires a local configuration to be defined.")
        print(e)
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument('--check-database',
                        help="Check the config level of the database",
                        action="store_true")
    parser.add_argument('--print-database',
                        help="Print the database", action="store_true")
    parser.add_argument('--delete-database',
                        help="Delete the database", action="store_true")
    args = parser.parse_args()

    if args.print_database:
        db = DatabaseProvider(localconfig['Database'])
        db.update_config(SimpleLoggerConfig)
        db.print()
    elif args.delete_database:
        db = DatabaseProvider(localconfig['Database'])
        db.update_config(SimpleLoggerConfig)
        db.delete_database()
    elif args.check_database:
        db = DatabaseProvider(localconfig['Database'])
        db.update_config(SimpleLoggerConfig)
        db.check_database()
    else:
        u = Updatebot(localconfig)
        u.run()
