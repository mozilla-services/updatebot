<h1 align="center">
  Updatebot
</h1>

[![<mozilla-services>](https://img.shields.io/circleci/build/gh/mozilla-services/updatebot?label=tests&style=flat-square)](https://circleci.com/gh/mozilla-services/updatebot)
[![codecov](https://img.shields.io/codecov/c/gh/mozilla-services/updatebot?style=flat-square)](https://codecov.io/gh/mozilla-services/updatebot)

Automated detection, patching, testing, and bug filing for updates in third-party libraries for Firefox.

This project requires [Poetry](https://python-poetry.org/docs/) and a version of [Python](https://www.python.org/downloads/release/python-359/) at least greater than 3.5.

We talk to a database; currently [MySQL](https://www.mysql.com/downloads/) is supported. Copy the local config file with `cp localconfig.py.example localconfig.py` and configure the database connection parameters. Updatebot will automatically create and populate the database with its structure and required data.

To get started developing updatebot, or to run it locally you'll need to run `poetry install` and then `poetry run ./automation.py`

Testing is handled in a single step of `poetry run ./test.py`

For formatting code automatically please use `poetry run autopep8 --in-place --recursive --ignore E501,E402 .`

For linting the codebase run `poetry run flake8 --ignore=E501,E402 .`

Updatebot is currently in early, active development with a lot of churn.

This repo is subject to [our quality standards and practices](https://developer.mozilla.org/en-US/docs/Mozilla/Developer_guide/Committing_Rules_and_Responsibilities) and any interaction here is governed by the [Mozilla Community Participation Guidelines.](https://www.mozilla.org/en-US/about/governance/policies/participation/)
