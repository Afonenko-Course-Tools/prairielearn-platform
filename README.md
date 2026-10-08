# PrairieLearn platform

Shared platform for native PrairieLearn courses, with a Java 25 grader.
Implementation is in progress; no deployment or authentication acceptance is claimed.

Java courses require JDK 25 or newer. The reference grader uses a pinned JDK 25.
Runtime credentials, identities, jobs and OpenTofu state belong outside this checkout.
The current pilot excludes backup and restore workflows.

Local verification:

```sh
JAVA_HOME=/usr/lib/jvm/java-25-openjdk PATH=/usr/lib/jvm/java-25-openjdk/bin:$PATH python3 -m unittest discover -s tests -v
```
