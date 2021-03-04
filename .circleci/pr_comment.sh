#!/bin/bash

set +vex

# extract PR number from CircleCI environment variable and append to API url
curl \
--request POST "https://api.github.com/repos/mozilla-services/updatebot/issues/${CIRCLE_PULL_REQUEST##*/}/comments" \
-u $GH_USER:$GH_TOKEN \
--header 'Accept: application/vnd.github.v3+json' \
--data-binary @json_output.txt \
-o /dev/stderr \
-w "%{http_code}"
