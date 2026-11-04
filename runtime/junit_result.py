"""Единая проверка событий JUnit на границах исполнителя и квитанции."""


def unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


CHECK_FIELDS = {
    "site",
    "property",
    "availability",
    "expected",
    "actual",
    "delta",
    "differenceIndex",
    "differenceExpected",
    "differenceActual",
    "differenceLine",
    "differenceColumn",
    "delegated",
}


def validate_checks(checks):
    """Одна точная публичная форма; private authority/audit не принимаются."""
    import re

    if not isinstance(checks, list) or len(checks) > 64:
        raise ValueError("Invalid assertion check bound")
    for check in checks:
        if (
            not isinstance(check, dict)
            or set(check) - CHECK_FIELDS
            or not {
                "site",
                "property",
                "availability",
                "expected",
                "actual",
                "delegated",
            }
            <= set(check)
            or any(
                not isinstance(v, str) or len(v) > 8192 or len(v.encode("utf-8")) > 8192
                for v in check.values()
            )
            or not re.fullmatch(r"[\w$.-]+\.java:[0-9]+:[0-9]+", check["site"])
            or check["delegated"] not in ("returned", "threw", "unknown")
            or not (
                check["availability"] == "complete"
                or check["availability"].startswith("incomplete: ")
            )
            or (check["delegated"] == "unknown" and check["availability"] == "complete")
            or any(
                k in check and not re.fullmatch(r"[0-9]+", check[k])
                for k in ("differenceIndex", "differenceLine", "differenceColumn")
            )
        ):
            raise ValueError("Invalid assertion check feedback")


def validate_counts(counts, require_cases=True):
    """Проверить завершённый набор фактических событий до вычисления оценки."""
    if not isinstance(counts, dict):
        raise ValueError("Invalid JUnit event report")
    numeric = (
        "discovered",
        "executed",
        "passed",
        "failed",
        "skipped",
        "aborted",
        "containerFailures",
        "eventErrors",
    )
    if any(type(counts.get(key)) is not int or counts[key] < 0 for key in numeric):
        raise ValueError("Invalid JUnit event counts")
    outcomes = counts.get("outcomes")
    registered, started = counts.get("registered"), counts.get("started")
    if (
        counts.get("complete") is not True
        or counts["eventErrors"]
        or not isinstance(outcomes, dict)
        or any(
            not isinstance(key, str)
            or not key
            or status not in ("successful", "failed", "skipped", "aborted")
            for key, status in outcomes.items()
        )
    ):
        raise ValueError("Incomplete JUnit event report")
    if any(
        not isinstance(ids, list)
        or any(not isinstance(key, str) or not key for key in ids)
        or len(ids) != len(set(ids))
        for ids in (registered, started)
    ):
        raise ValueError("Missing or duplicate JUnit identity")
    if (
        set(registered) != set(outcomes)
        or counts["discovered"] != len(registered)
        or counts["executed"] != len(started)
        or set(started)
        != {key for key, status in outcomes.items() if status != "skipped"}
        or any(
            counts[key] != sum(value == status for value in outcomes.values())
            for key, status in (
                ("passed", "successful"),
                ("failed", "failed"),
                ("skipped", "skipped"),
                ("aborted", "aborted"),
            )
        )
    ):
        raise ValueError("Inconsistent JUnit discovery/execution outcomes")
    failures = counts.get("failureKinds")
    if (
        not isinstance(failures, dict)
        or set(failures)
        != {key for key, status in outcomes.items() if status == "failed"}
        or any(
            kind
            not in (
                "wrong-answer",
                "runtime",
                "timeout",
                "output-limit",
                "infrastructure",
            )
            for kind in failures.values()
        )
    ):
        raise ValueError("Inconsistent JUnit failure evidence")
    cases = counts.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Missing JUnit case report")
    protocol = counts.get("feedbackProtocolVersion", 1)
    if type(protocol) is not int or protocol not in (1, 2):
        raise ValueError("Invalid assertion feedback protocol")
    ids = []
    for case in cases:
        if (
            not isinstance(case, dict)
            or set(case) - {"id", "name", "status", "expected", "actual", "checks", "test"}
            or not {"id", "name", "status"} <= set(case)
            or any(
                not isinstance(value, str) or len(value) > 8192
                for key, value in case.items()
                if key != "checks"
            )
            or ("test" in case and not case["test"])
            or case["id"] not in outcomes
            or case["status"]
            != ("passed" if outcomes[case["id"]] == "successful" else "failed")
        ):
            raise ValueError("Invalid JUnit case feedback")
        if protocol == 2:
            if "checks" not in case:
                raise ValueError("Missing assertion check sequence")
            validate_checks(case["checks"])
        elif "checks" in case:
            raise ValueError("Checks require assertion protocol2")
        ids.append(case["id"])
    if (
        len(ids) != len(set(ids))
        or (require_cases or cases)
        and set(ids) != set(started)
    ):
        raise ValueError("Incomplete JUnit case feedback")


def validate_outcome(value, *, student_tests=False):
    """Принять тот же полный набор и долю после файловой/процессной границы."""
    if "counts" in value:
        counts = value["counts"]
        validate_counts(counts, require_cases=not student_tests)
        if value.get("classification") != "student-test-quality-failure":
            if not counts["executed"] or any(
                counts[key] for key in ("skipped", "aborted", "containerFailures")
            ):
                raise ValueError("Incomplete scored JUnit outcome")
            if "infrastructure" in counts["failureKinds"].values():
                raise ValueError("Trusted failure cannot be a scored outcome")
            if (
                value.get("scoring", {}).get("mode") == "weighted"
                and value.get("score") != counts["passed"] / counts["executed"]
            ):
                raise ValueError(
                    "Weighted score differs from equal completed case fraction"
                )
    elif (
        value.get("infrastructure") == "complete"
        and value.get("classification")
        in (
            "success",
            "behavior-failure",
            "student-runtime-failure",
            "student-timeout",
            "student-output-overflow",
            "student-test-quality-failure",
        )
        and "variants" not in value
    ):
        raise ValueError("Missing complete JUnit outcome")
    if "publicResult" in value:
        validate_outcome(value["publicResult"], student_tests=student_tests)
    for variant in value.get("variants", {}).values():
        validate_outcome(variant, student_tests=True)


def _read_junit_xml(directory, feedback_file):
    """Статус и оценка из штатных отчётов; JSON содержит только feedback/origin."""
    import json
    import math
    import re
    import xml.etree.ElementTree as ET
    from pathlib import Path

    feedback = json.loads(Path(feedback_file).read_text(), object_pairs_hook=unique_json_object)
    if feedback.get('complete') is not True:
        raise ValueError('Incomplete JUnit execution')
    reports = sorted(Path(directory).glob('TEST-*.xml'))
    if not reports:
        raise ValueError('Missing JUnit XML report')
    cases_by_id = {case['id']: case for case in feedback['cases']}
    if len(cases_by_id) != len(feedback['cases']):
        raise ValueError('Duplicate feedback case')
    outcomes, cases, failures = {}, [], {}
    container_failures = feedback.get('containerFailures', 0)
    try:
        for report in reports:
            data = report.read_bytes()
            if len(data) > 8 * 1024 * 1024 or b'<!DOCTYPE' in data or b'<!ENTITY' in data:
                raise ValueError('Unsafe or oversized JUnit XML')
            suite = ET.fromstring(data)
            if suite.tag != 'testsuite':
                raise ValueError('Expected JUnit testsuite')
            rows = suite.findall('testcase')
            if int(suite.attrib['tests']) != len(rows):
                raise ValueError('Inconsistent JUnit XML test count')
            for counter, tag in (('failures','failure'),('errors','error'),('skipped','skipped')):
                if int(suite.attrib[counter]) != sum(row.find(tag) is not None for row in rows):
                    raise ValueError('Inconsistent JUnit XML aggregate ' + counter)
            for row in rows:
                if sum(row.find(tag) is not None for tag in ('skipped','failure','error')) > 1:
                    raise ValueError('Contradictory JUnit XML case status')
                output = '\n'.join(node.text or '' for node in row.findall('system-out'))
                match = re.search(r'^unique-id: (.+)$', output, re.M)
                if match is None:
                    raise ValueError('Missing JUnit unique-id')
                uid = match[1].strip()
                if uid in outcomes:
                    raise ValueError('Duplicate JUnit case')
                skipped = row.find('skipped') is not None
                failed = row.find('failure') is not None or row.find('error') is not None
                # Legacy XML also emits successful childless non-test containers.
                if (uid not in cases_by_id and not skipped and not failed
                        and uid in feedback.get('successfulContainers', [])):
                    continue
                status = ('aborted' if uid in cases_by_id else 'skipped') if skipped else 'failed' if failed else 'successful'
                # Legacy XML includes a synthetic testcase for a failed container.
                if uid not in cases_by_id and failed:
                    container_failures = max(container_failures, 1)
                    continue
                outcomes[uid] = status
                if not skipped:
                    case = dict(cases_by_id.get(uid, {}))
                    if not case or case.get('status') != ('passed' if status == 'successful' else 'failed'):
                        raise ValueError('JUnit XML and feedback differ')
                    cases.append(case)
                if failed:
                    if uid not in feedback['failureKinds']:
                        raise ValueError('Missing exception origin feedback')
                    failures[uid] = feedback['failureKinds'][uid]
    except (ET.ParseError, KeyError, TypeError) as error:
        raise ValueError('Invalid JUnit XML report') from error
    if outcomes != feedback['verifiedOutcomes']:
        raise ValueError('JUnit XML differs from authenticated engine outcomes')
    executed = [uid for uid, status in outcomes.items() if status != 'skipped']
    if set(cases_by_id) != set(executed):
        raise ValueError('Incomplete JUnit XML testcase set')
    counts = dict(
        complete=True, eventErrors=0, feedbackProtocolVersion=feedback['feedbackProtocolVersion'],
        discovered=len(outcomes), executed=len(executed),
        registered=list(outcomes), started=executed, outcomes=outcomes,
        passed=sum(s == 'successful' for s in outcomes.values()),
        failed=sum(s == 'failed' for s in outcomes.values()),
        skipped=sum(s == 'skipped' for s in outcomes.values()),
        aborted=sum(s == 'aborted' for s in outcomes.values()),
        containerFailures=container_failures, failureKinds=failures,
        cases=cases if feedback['feedbackProtocolVersion'] == 2 else [],
        publicCaseObservations=feedback.get('publicCaseObservations', []),
    )
    grading = feedback.get('grading', {})
    if set(grading) != set(outcomes):
        raise ValueError('Incomplete JUnit grading metadata')
    totals, points = {}, 0
    tests = []
    for uid, status in outcomes.items():
        metadata = grading[uid]
        weight = metadata['weight']
        if type(weight) not in (int,float) or not math.isfinite(weight) or weight < 0:
            raise ValueError('Invalid JUnit grading weight')
        if any(not isinstance(metadata[field],str) for field in ('name','description','owner')):
            raise ValueError('Invalid JUnit grading metadata')
        owner = metadata['owner']
        totals[owner] = totals.get(owner, 0) + weight
        achieved = weight if status == 'successful' else 0
        points += achieved
        if not math.isfinite(totals[owner]) or not math.isfinite(points):
            raise ValueError('JUnit grading points overflow')
        tests.append(dict(name=metadata['name'], description=metadata['description'],
                          message='', output='', points=achieved, max_points=weight))
    for owner, maximum in feedback.get('classMaximums', {}).items():
        if type(maximum) not in (int,float) or not math.isfinite(maximum) or maximum < 0:
            raise ValueError('Invalid JUnit class maximum')
        totals[owner] = maximum
    total = sum(totals.values())
    if not math.isfinite(total):
        raise ValueError('JUnit grading maximum overflow')
    raw = dict(gradable=True, tests=tests, score=min(points / total, 1) if total else 0,
               points=min(points, total), max_points=total, message='', output='')
    return raw, counts


def read_junit_xml(directory, feedback_file, *, report_key=None):
    """Единственная граница разбора недоверенной выдачи дочернего процесса."""
    try:
        if report_key is not None:
            import hashlib
            import hmac
            from pathlib import Path
            payload = Path(feedback_file).read_bytes()
            expected = hmac.digest(bytes.fromhex(report_key), payload, 'sha256').hex()
            actual = Path(str(feedback_file) + '.signature').read_text().strip()
            if not hmac.compare_digest(actual, expected):
                raise ValueError('Invalid JUnit result authentication')
        return _read_junit_xml(directory, feedback_file)
    except (AttributeError, KeyError, TypeError, OverflowError) as error:
        raise ValueError('Invalid JUnit generated report shape') from error
