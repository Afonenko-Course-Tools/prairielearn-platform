# Working rules

- Keep this platform independent of any particular course.
- Use synthetic identities and files in tests; keep credentials and runtime data outside Git.
- Java grading must compile and run on an actual JDK 25, with `--release 25`.
- Student errors and grader failures are different outcomes; never report a harness failure as score 0.
- Test locally first. Actual Moodle tests belong to the final integration stage.
- Backup/restore workflows are outside the current scope.
- Preserve exact source commits and image digests; never claim integration based only on generated files.
