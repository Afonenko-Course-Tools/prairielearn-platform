# Поставка JDK и Gradle принадлежит обычным Docker images.
FROM eclipse-temurin:25-jdk-noble AS jdk
FROM gradle:9.8.2-jdk25-noble AS gradle
FROM docker.io/prairielearn/grader-java@sha256:dacce5e76d24cf1eaee21bec3e20b3ea40739408afdc89e6607eb542dc6b7a2e
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-jsonschema gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY --from=jdk /opt/java/openjdk /opt/native-jdk
COPY --from=gradle /opt/gradle /opt/gradle
RUN groupadd --system nativebuild && useradd --system --gid nativebuild --shell /usr/sbin/nologin nativebuild \
    && mkdir -p /usr/lib/jvm/java-25-openjdk-amd64 \
    && cp -a /opt/native-jdk/. /usr/lib/jvm/java-25-openjdk-amd64/ \
    && rm -f /usr/lib/jvm/java-25-openjdk-amd64/lib/libmanagement.so /usr/lib/jvm/java-25-openjdk-amd64/lib/libmanagement_ext.so /usr/lib/jvm/java-25-openjdk-amd64/lib/libmanagement_agent.so \
    && chown -R root:nativebuild /opt/native-jdk && chmod -R g+rX,o-rwx /opt/native-jdk && chmod 750 /opt/native-jdk
COPY images/java25-grader/landlock/sandbox.c /tmp/landlock-sandbox.c
RUN gcc -O2 -Wall -Wextra /tmp/landlock-sandbox.c -o /usr/local/bin/landlock_sandbox && chmod 755 /usr/local/bin/landlock_sandbox && rm /tmp/landlock-sandbox.c
ENV PL_CONTAINMENT=official PYTHONDONTWRITEBYTECODE=1
ENV JAVA_HOME=/usr/lib/jvm/java-25-openjdk-amd64
ENV PATH=/usr/lib/jvm/java-25-openjdk-amd64/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
WORKDIR /platform
COPY runtime /platform/runtime
COPY runtime-profiles.json /platform/runtime-profiles.json
COPY images/java25-grader/grade.py /platform/images/java25-grader/grade.py
RUN chmod 700 /platform /javagrader
ENTRYPOINT ["python3", "/platform/images/java25-grader/grade.py"]
CMD []
