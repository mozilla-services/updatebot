Some third party dependencies have local patches Mozilla applies after vendoring in the third party library.  Sometimes those patches do not apply cleanly.  This is where you come in.  Updatebot has called you into help resolve these conflicts.  You should take the following steps.  

At the end you will wrote out a file called conflict_resolution_result.json.  It will contain a dictionary with two fields.  "outcome" should have a value of "trivial success", "uncertain success", or "failure".  "details" will contain an array of strings, where each string is a sentence or paragraph.

{{ conflict_resolution_instructions }}

### Conflict Resolution Process

When a patch does not apply cleanly, for each rejection in the patch:

1. Determine if the hunk does not apply because the surrounding context has moved or changed, but the intent and general location of the patch relative to other code remains the same.  If so, update the .patch file to apply correctly for this hunk, and continue to the next hunk.
2. Determine if the hunk does not apply because it seems like the hunk has already been applied.  This can indicate that the patch was upstreamed and it is no longer necessary for this library.  Make a note that think hunk is no longer valid and continue trying apply hunks.
3. Finally, if the hunk does not apply cleanly because something has changed in the code that is a non-trivial change, use local tools such as git to understand what change was made upstream, what the intention of the local patch was, and how you can reconcile them. If you are able to do this, continue to the next hunk.  In this situation, the final `outcome` value must be either `uncertain success` or `failure`.
4. If you have attempted to understand the problem and are uncertain of how to process, you should stop attempting hunks, and patches, and append a summary of your confusion to the `details` array, and you must return an outcome of `failure`.

If, at the end, no hunks were applied, this is a good indication the patch was upstreamed.  In this case remove the patch file from the repo with `hg rm` or `git rm`, and remove it from the moz.yaml patch list. Make a note of this in the `details` array.  Continue to the next patch.

Alternately, if all the hunks have been updated and applies successfully, make a note of this in the `details` array, and continue to the next patch.
