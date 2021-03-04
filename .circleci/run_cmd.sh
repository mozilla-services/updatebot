# CircleCI halts as soon as any command returns a non-zero value.
# So anything that might needs to be in an if statement.
#
# This ensures that the pr_comment script is run regardless of if our
# command fails.
#
# We run the test and capture the output (stdout and stderr) in a text
# file, because the output may be too large to pass on the command line.
#
# If github returns an error to our initial request, we try to grab it
# and post the error instead of the test output. Obviously this would only
# catch it if e.g. the test results were too large and not in
# authentication failed.

sudo apt-get install jq git
cp localconfig.py.example localconfig.py
if $(eval "poetry run $1 > test_output.txt 2>&1"); then
  cat test_output.txt
else
  cat test_output.txt

  if [ $CIRCLE_BRANCH = "master" ]; then
    exit 1
  fi

  sed -i '1s;^;<pre>;' test_output.txt
  echo "</pre>" >> test_output.txt

  jq -Rs '{"body": .}' test_output.txt > json_output.txt

  if [ $(. .circleci/pr_comment.sh 2> curl_output.txt) = "201" ]; then
    echo "Sent the comment to Github successfully."
    cat curl_output.txt
    false
  else
    echo "Did not send the comment to Github successfully!!!"
    cat curl_output.txt

    sed -i '1s;^;<pre>curl failed.  The response from Github was:\n;' curl_output.txt
    echo "</pre>" >> curl_output.txt

    jq -Rs '{"body": .}' curl_output.txt > json_output.txt
    . .circleci/pr_comment.sh
    false
  fi
fi
