FROM docker.io/prairielearn/grader-java@sha256:dacce5e76d24cf1eaee21bec3e20b3ea40739408afdc89e6607eb542dc6b7a2e
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-jsonschema fish git && rm -rf /var/lib/apt/lists/*
ENV PL_CONTAINMENT=official PYTHONDONTWRITEBYTECODE=1
WORKDIR /platform
COPY .native-toolchain/fish-runtime-profiles.json /platform/runtime-profiles.json
COPY schemas /platform/schemas
COPY runtime/student_feedback.py /platform/runtime/student_feedback.py
COPY runtime/fish-git-v1 /platform/runtime/fish-git-v1
COPY images/fish-git-grader/grade.py /platform/images/fish-git-grader/grade.py
RUN chmod 700 /platform /javagrader
ENTRYPOINT ["python3", "/platform/images/fish-git-grader/grade.py"]
