#!/bin/bash
# restrict to running on non-main branches
if [ $CIRCLE_BRANCH != "master" ]
then
  # extract PR number from CircleCI environment variable and append to API url
  curl --request POST "https://api.github.com/repos/metalcanine/pythonci/issues/${CIRCLE_PULL_REQUEST##*/}/comments" \
  -u $GH_USER:$GH_TOKEN \
  --header 'Accept: application/vnd.github.v3+json' \
  --data-raw "{\"body\": ${COMMAND_OUTPUT}}"
fi
