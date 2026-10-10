FROM docker.io/prairielearn/prairielearn@sha256:60c675a42055a430f9ad7298c7dfd2f37119aa471f806e21e2c929de28435f63
# Official Community build corresponds to pinned source 92584fe426ececb84bc2d09de9975c7056c0c5f6.
COPY images/prairielearn/patch-localhost-cookies.py /tmp/patch-localhost-cookies.py
RUN python3 /tmp/patch-localhost-cookies.py /PrairieLearn/apps/prairielearn/src/lib/config.ts /PrairieLearn/apps/prairielearn/dist/lib/config.js && rm /tmp/patch-localhost-cookies.py
COPY bridge /PrairieLearn/apps/prairielearn/bridge
COPY images/prairielearn/start-bridge.sh /PrairieLearn/scripts/start-gateway-bridge.sh
CMD ["/PrairieLearn/scripts/start-gateway-bridge.sh"]
