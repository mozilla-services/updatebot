1. Ensure there are no modified or untracked files in the repository.  If there are, revert them or remove them.
2. Review the moz.yaml file located at {{ moz_yaml_path }} and specifically the list of patches specified
3. Run `./mach vendor --patch-mode only {{ moz_yaml_path }}` and observe its output
4. Ensure there are no modified or untracked files in the repository.  If there are, revert them or remove them.
5. Iterally attempt to apply the patches specified in the moz.yaml using the same technique that was observed from `./mach vendor`.  The source code for this process lives in import_local_patches inside python/mozbuild/mozbuild/vendor/vendor_manifest.py in the firefox source directory
6. When you encounter a patch that does not apply, review its contents.  Follow the instructions in 'Conflict Resolution Process' below.  If you are instructed to continue, do so, continuing steps 5 and 6 for all patches listed in the moz.yaml
7. If any conflict resolution process indicated that the outcome should be failure; make that the `outcome`.  If any conflict resolution process indicates that it can be either `uncertain success` or `failure`, then the outcome is `uncertain success`.  If you otherwise applied everything simply and successfully the outcome should be `trivial success`.  
8. When you have completed, commit _only_ the updates you made to the .patch files and (if applicable) moz.yaml.  The commit message for this commit should be "{{ patch_fix_commit_message }}" and it should append the `details` you have been keeping track of.
9. Write the json file with the `outcome` and the `details` array.
