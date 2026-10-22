# Закрытый контекст содержит только заранее аутентифицированные toolchain inputs.
# .native-toolchain готовится оператором; во время build/runtime загрузок нет.
FROM ghcr.io/afonenko-course-tools/java25-grader@sha256:6052b077f7d5fabaedbd2deb829eed15e9911beafaf78f29c90083ff917b8c17
ENV PL_CONTAINMENT=official
ENV JAVA_HOME=/usr/lib/jvm/java-25-openjdk-amd64
ENV PATH=/usr/lib/jvm/java-25-openjdk-amd64/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
WORKDIR /platform
COPY runtime /platform/runtime
COPY tools/prepare_native_jdk.py /platform/tools/prepare_native_jdk.py
COPY images/java25-grader/grade.py /platform/images/java25-grader/grade.py
# Generated dependency-only baked view: image отсутствует, три profile runner pins.
COPY .native-toolchain/runtime-profiles.json /platform/runtime-profiles.json
COPY .native-toolchain/operator/ /operator/
COPY .native-toolchain/gradle-9.8.0-bin.zip /toolchain/gradle-9.8.0-bin.zip
COPY .native-toolchain/landlock_sandbox /usr/local/bin/landlock_sandbox
RUN chmod 700 /platform /operator /javagrader && chmod 755 /usr/local/bin/landlock_sandbox && python3 -I -B /operator/install-native.py
ENTRYPOINT ["python3", "/platform/images/java25-grader/grade.py"]
CMD []
