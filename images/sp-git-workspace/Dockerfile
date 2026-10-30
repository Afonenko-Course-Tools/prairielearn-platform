FROM docker.io/prairielearn/workspace-vscode-base@sha256:cdad0b1fd89a3e019efca29c66768ffa2f7b4f99dbfe3016e2667f6769b90600
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends fish=3.7.0-1 python3=3.12.3-0ubuntu2.1 \
    && rm -rf /var/lib/apt/lists/*
COPY --chmod=0755 --chown=root:root entrypoint.sh /usr/local/bin/sp-git-workspace
USER coder
WORKDIR /home/coder/workspace
LABEL com.prairielearn.workspace.home="/home/coder/workspace"
LABEL com.prairielearn.workspace.port="8080"
LABEL com.prairielearn.workspace.rewrite-url="true"
ENTRYPOINT ["/usr/bin/pl-gosu-helper.sh", "/usr/local/bin/sp-git-workspace"]
