## Google Cloud SQL

We use the cloud sql proxy for connecting to the database securely. Because this
creates a local listener for us to connect to, in run.py we rewrite the database
server to be 127.0.0.1.

We need to set up a Service Account for this. The account needs to be given the
Cloud SQL Editor permission. (Cloud SQL Instance User is not sufficient.)

## Sentry

We have a Sentry project for logging. There are no critical settings for this
account, I don't think.