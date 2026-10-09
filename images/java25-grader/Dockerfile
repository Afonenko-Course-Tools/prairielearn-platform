FROM docker.io/prairielearn/grader-java@sha256:dacce5e76d24cf1eaee21bec3e20b3ea40739408afdc89e6607eb542dc6b7a2e
RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*
ENV PL_CONTAINMENT=official
WORKDIR /platform
COPY runtime-profiles.json /platform/runtime-profiles.json
COPY runtime /platform/runtime
COPY images/java25-grader/grade.py /platform/images/java25-grader/grade.py
RUN chmod 700 /platform /javagrader
ENTRYPOINT ["python3", "/platform/images/java25-grader/grade.py"]
