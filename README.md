# Updatebot

[![<mozilla-services>](https://img.shields.io/circleci/build/gh/mozilla-services/updatebot?label=tests&style=flat-square)](https://circleci.com/gh/mozilla-services/updatebot)
[![codecov](https://img.shields.io/codecov/c/gh/mozilla-services/updatebot?style=flat-square)](https://codecov.io/gh/mozilla-services/updatebot)

Automated detection, patching, testing, and bug filing for updates in third-party libraries for Firefox.

## For Mozilla Developers

Updatebot is a bot that looks for upstream updates to a third party dependency (typically a library) and if it detects an update it will:

 - File a bug that an update is available
 - Attempt to automatically vendor it, reporting errors if they occur
 - Send in a try run with the update
 - Submit a phabricator patch of the update
 - Once the try run is complete, look for test failures and retrigger them
 - Once the retriggers are complete, report a summary of the results (what tests failed, how many times, and if they are known issues or not)
 - Flag the dependency's maintainer for review of the patch or send them a needinfo on the bug

Updatebot can be thought of as two halves: the bot that does the above and the in-tree `./mach vendor` component that makes it easy for a library to be updated locally. *We would be happy to help you set up your library for vendoring in Updatebot.*

Updatebot **doesn't have to vendor the update** - it can instead just alert you that there were new commits.  This is good for infrequently updated upstreams that are difficult to automatically vendor.  In the future we intend to add some intelligence to this to let us filter by suspected security issues.

Updatebot has several configurable options:

1. It can look for updates:
   - every run (6 hours) - good for infrequently updated upstreams
   - every N weeks
   - every N commits
   - only upon a new Firefox release (good for frequently updated libraries we bump once-per-FF release)
2. It can track a specific upstream branch, or only look for newly tagged releases
3. It can use `./mach try auto` or `./mach try fuzzy` with a custom query string to send in the try run
4. Through the [moz.yaml format](https://searchfox.org/mozilla-central/source/python/mozbuild/mozbuild/vendor/moz_yaml.py), it can handle more complicated vendoring steps using custom scripts, or more simple vendoring steps using a predefined language.


## Updatebot Development

This project requires [Poetry](https://python-poetry.org/docs/) and a version of [Python](https://www.python.org/downloads/release/python-359/) at least greater than 3.5.

We talk to a database; currently [MySQL](https://www.mysql.com/downloads/) is supported. Copy the local config file with `cp localconfig.py.example localconfig.py` and configure the database connection parameters. Updatebot will automatically create and populate the database with its structure and required data.

To get started developing Updatebot, or to run it locally you'll need to run `poetry install` and then `poetry run ./automation.py`

Testing is handled in a single step of `poetry run ./test.py`

For formatting code automatically please use `poetry run autopep8 --in-place --recursive --ignore E501,E402 .`

For linting the codebase run `poetry run flake8 --ignore=E501,E402 .`

Updatebot is currently in active development with a lot of churn. We welcome patches and bugfixes, but encourage you to reach out to June Wilde or Tom Ritter before spending too much time as we may be already addressing your issue.

### How it works
Updatebot runs as a Linux-based cron job in mozilla-central every 6 hours (defined in [.cron.yml](https://searchfox.org/mozilla-central/source/.cron.yml)).  (There is a windows cron job in development, but ignore it for now.) This job runs in the [Updatebot Docker Image](https://searchfox.org/mozilla-central/source/taskcluster/docker/updatebot).  It will [search](https://github.com/mozilla-services/updatebot/blob/c9133c4f2c15b30438fe6721ef7f490472851de4/components/libraryprovider.py#L122-L129) the mozilla source tree for [moz.yaml files](https://searchfox.org/mozilla-central/search?q=moz.yaml&case=true&path=) that [define an enabled Updatebot task](https://searchfox.org/mozilla-central/rev/83e67336083df9f9a3d1e0c33f2ba19703d57161/media/libdav1d/moz.yaml#40-43).  We will figure out [which task type we are dealing with](https://github.com/mozilla-services/updatebot/blob/c9133c4f2c15b30438fe6721ef7f490472851de4/automation.py#L134-L137).  The more commone one is a [vendoring task](https://github.com/mozilla-services/updatebot/blob/master/tasktypes/vendoring.py) but there is also a [commit alert task](https://github.com/mozilla-services/updatebot/blob/master/tasktypes/commitalert.py).

From here we will look at all of the jobs in the database for this library and task type, and process them to see if there is anything we need to do for them.  We might look at try results and summarize them on the bugzilla bug, trigger new jobs on a try run, or mark an open bugzilla bug as affecting a new Firefox release.  This all happens in `process_task` and `_process_existing_job` in [vendoring.py](https://github.com/mozilla-services/updatebot/blob/master/tasktypes/vendoring.py).

After looking at the prior jobs, we'll see if there is a new upstream revision we don't have a current job for.  If so, we will go into `_process_new_job` in [vendoring.py](https://github.com/mozilla-services/updatebot/blob/master/tasktypes/vendoring.py).  We'll see if we should process the job based on it's request frequency, and if so figure out if it actually changes any files in m-c - if not we consider it a 'spurious update'.  If it passes those checks it goes into the normal updatebot cycle.  This involves creating a bug, creating a patch, submitting to try, submitting to phabricator. An important step here is that we look at the most recent filed bug for this library - if it is still open we will close it as a duplicate, duplicating it forward to our new bug.  We have some logic in there to only do this to a bug _once_ - we don't want Updatebot to get into a bug opening/closing loop with developers.

Updatebot uses a database that lives in Google CloudSQL.  There is a dev and prod database, as well as [dev and prod credentials](https://searchfox.org/mozilla-central/rev/83e67336083df9f9a3d1e0c33f2ba19703d57161/taskcluster/docker/updatebot/run.py#79-84) for those databases, bugzilla, try server, phabricator, sentry, and sql-proxy (which is used to connect to the database).  You can find them in [grants.yml](https://hg.mozilla.org/ci/ci-configuration/file/tip/grants.yml#l644) searching for 'updatebot'.  The dev credentials are granted to holly, which is our reserved development instance because Updatebot can't tested on try safely.  The prod credentials are only available to mozilla-central.


### Architecture
Updatebot's architecture is.... not great.

 - In an effort to make mockable classes for testing and stubbing functionality, nearly all the low-to-medium level logic about 'how to do something' is contained in either a [component class](https://github.com/mozilla-services/updatebot/tree/master/components) or an [api class](https://github.com/mozilla-services/updatebot/tree/master/apis) - both called 'Providers'.  The distinction between the two is not very significant, except the API classes were originally separated to indicate an external API we talk to.
  - We describe two types of Providers: Functionality Providers, and Utility Providers.  Functionality Providers may require and use Utility Providers.  And Utility Providers can include Utility Providers.
  - Concretely, there are two Utility Providers: a Logging Provider and a CommandProvider, the latter of which requires the former.
 - Updatebot takes a [configuration](https://github.com/mozilla-services/updatebot/blob/master/localconfig.py.example), which is a dictionary of dictionaries. A sub-dictionary for each Provider, plus a 'General' dictionary given to every Provider
 - Initialization of the providers is [complex](https://github.com/mozilla-services/updatebot/blob/c9133c4f2c15b30438fe6721ef7f490472851de4/automation.py#L61-L97) because we want to allow tests to define alternate Providers (mocked Providers).  And because Functionality Providers need Utility Providers....
 - __The whole Provider thing is a giant mess and needs to be completely redone.__
 - For each of our two task types, vendoring and commit-alert, we have a [tasktype class](https://github.com/mozilla-services/updatebot/tree/master/tasktypes) that defines the higher-level logic.  This logic is tested in the `functionality_*` tests.  (Those tests themselves need a README explaining how they work.)
 - The entry point is [automation.py](https://github.com/mozilla-services/updatebot/blob/master/automation.py).
 - We have a [dbc layer](https://github.com/mozilla-services/updatebot/blob/master/components/dbc.py) that's intended to support abstracting away to a different database if we ever switch.
 - We have the [db layer](https://github.com/mozilla-services/updatebot/blob/master/components/db.py) which is the only thing that speaks MySQL.
 - Inside the db layer we define the database structure. It will create the database if one does not exist.  When we need to alter the database structure we bump the database revision and [write migration code](https://github.com/mozilla-services/updatebot/blob/c9133c4f2c15b30438fe6721ef7f490472851de4/components/db.py#L217-L349).

There are a few bits of complexity elided in the overview and architecture details above:

 - We support (in theory) doing two try runs: one for linux64 and if that succeeds a follow-up run of everything else. This is to be more mindful of try resources, but presently this doesn't work as intended (on the try side) so we only do one try run.
 - We have the notion of Job States (done or not done) and outcomes (success, failed with known failures, failed with unknown).
 - We have a bit of complexity in how we compare our current in-tree revision with the upstream revision, and code that looks for the commits in between and adds them to bug comments.
 - We have logic to update bugs tracking flags when they are left open for a long period of time

## Fine Print

This repo is subject to [our quality standards and practices](https://developer.mozilla.org/en-US/docs/Mozilla/Developer_guide/Committing_Rules_and_Responsibilities) and any interaction here is governed by the [Mozilla Community Participation Guidelines.](https://www.mozilla.org/en-US/about/governance/policies/participation/)
