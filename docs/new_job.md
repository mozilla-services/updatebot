```mermaid
graph TD
    Done[Done]

    A[New Revision Upstream]
    A --> FrequencyCheck
    
    FrequencyCheck{Should process <br />according to <br/>frequency rules?}
    FrequencyCheck -->|Yes| RunStage
    FrequencyCheck -->|No| Done

    RunStage[Run the next vendoring stage<br />with ./mach vendor --stage N]
    RunStage --> StageOutcome

    StageOutcome{How did the stage go?}
    StageOutcome --> |It ran| CommitStage
    StageOutcome --> |It couldn't<br />update a moz.build| FileBugForStage
    StageOutcome --> |It failed| FileBugForFailure

    FileBugForStage[Create the job and file the bug,<br />if that isn't done yet]
    FileBugForStage --> CommentMozBuild[Comment on the bug about it] --> CommitStage

    FileBugForFailure[Create the job and file the bug,<br />if that isn't done yet]
    FileBugForFailure --> PatchConflict

    PatchConflict{Did a patch not apply,<br />and the AI not try this stage yet?}
    PatchConflict --> |No| X2[Update job status to done<br />comment on bugzilla it failed.] --> Done
    PatchConflict --> |Yes| AskAI

    AskAI[Ask the AI to fix the stage's patches,<br />and commit the fix before the stage]
    AskAI --> AIOutcome

    AIOutcome{Did the AI succeed,<br />and commit its fix?}
    AIOutcome --> |No| X2
    AIOutcome --> |Yes| RunStage

    CommitStage[Commit it, if it changed anything,<br />with the bug number if there's a bug yet]
    CommitStage --> MoreStages

    MoreStages{Another stage?}
    MoreStages --> |Yes| RunStage
    MoreStages --> |No| HaveBug

    HaveBug{Is there a bug yet?}
    HaveBug --> |Yes| PushToTry
    HaveBug --> |No| SpuriousCheck

    SpuriousCheck{Do the commits change anything<br />but the moz.yaml and generated files?}
    SpuriousCheck -->|Yes| FileBug
    SpuriousCheck -->|No: a spurious update| X1[Strip the commits] --> Done

    FileBug[Create the job and file the bug]
    FileBug --> PushToTry

    PushToTry[Push to try]
    PushToTry --> CommentOnBug

    CommentOnBug[Comment on bug]
    CommentOnBug --> SubmitPhab

    SubmitPhab[Submit a revision to phabricator<br />for each commit]
    SubmitPhab --> Done
```

Creating the job and filing the bug also deals with any prior job's bug (duping it
to the new one, and abandoning its revisions), and gives the commits made so far
their messages, with the bug number.
