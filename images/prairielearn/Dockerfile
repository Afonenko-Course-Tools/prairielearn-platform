FROM docker.io/prairielearn/prairielearn@sha256:60c675a42055a430f9ad7298c7dfd2f37119aa471f806e21e2c929de28435f63
# Official Community build corresponds to pinned source 92584fe426ececb84bc2d09de9975c7056c0c5f6.
COPY tools/integer-manual-points.mjs tools/integer-manual-points.d.mts /PrairieLearn/apps/prairielearn/tools/
COPY images/prairielearn/patch-integer-manual-points.py /tmp/patch-integer-manual-points.py
COPY images/prairielearn/patch-integer-point-display.py /tmp/patch-integer-point-display.py
# Compile the opt-in schema, server and hydrated client before the existing src/dist hooks.
RUN python3 -B /tmp/patch-integer-manual-points.py /PrairieLearn/apps/prairielearn && python3 -B /tmp/patch-integer-point-display.py /PrairieLearn/apps/prairielearn && npm --prefix /PrairieLearn/apps/prairielearn run build && rm /tmp/patch-integer-manual-points.py /tmp/patch-integer-point-display.py
COPY images/prairielearn/patch-localhost-cookies.py /tmp/patch-localhost-cookies.py
RUN python3 -B /tmp/patch-localhost-cookies.py /PrairieLearn/apps/prairielearn/src/lib/config.ts /PrairieLearn/apps/prairielearn/dist/lib/config.js && rm /tmp/patch-localhost-cookies.py
COPY images/prairielearn/patch-local-grader.py /tmp/patch-local-grader.py
RUN python3 -B /tmp/patch-local-grader.py /PrairieLearn/apps/prairielearn/src/lib/externalGraderLocal.ts /PrairieLearn/apps/prairielearn/dist/lib/externalGraderLocal.js && rm /tmp/patch-local-grader.py
COPY images/prairielearn/patch-gateway-name.py /tmp/patch-gateway-name.py
RUN python3 -B /tmp/patch-gateway-name.py /PrairieLearn/apps/prairielearn/src/pages/authCallbackShib/authCallbackShib.ts /PrairieLearn/apps/prairielearn/dist/pages/authCallbackShib/authCallbackShib.js && rm /tmp/patch-gateway-name.py
COPY images/prairielearn/patch-recognized-credit.py /tmp/patch-recognized-credit.py
RUN python3 -B /tmp/patch-recognized-credit.py /PrairieLearn/apps/prairielearn && rm /tmp/patch-recognized-credit.py
COPY bridge /PrairieLearn/apps/prairielearn/bridge
COPY tools/sync-native-course.mjs tools/course-sync-policy.mjs tools/institution-bootstrap.mjs tools/bootstrap-native-course.mjs tools/native-course-payload.mjs tools/recognize-credit.mjs tools/recognized-credit-files.mjs /PrairieLearn/apps/prairielearn/tools/
COPY config/institutions.json /PrairieLearn/apps/prairielearn/config/institutions.json
COPY images/prairielearn/start-bridge.sh /PrairieLearn/scripts/start-gateway-bridge.sh
CMD ["/PrairieLearn/scripts/start-gateway-bridge.sh"]
