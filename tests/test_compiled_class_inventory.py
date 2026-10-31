"""Настоящие binary inventories вместо догадок по Java source: JDK25 и canaries."""

from pathlib import Path
import hashlib, json, subprocess, sys, tempfile, unittest
from gradle_unit_fixtures import unit_platform

ROOT = Path(__file__).resolve().parents[1]
CASES = []


def case(name, **kw):
    CASES.append(dict(name=name, expected="success", api=True, **kw))


# Удаление regex-догадки должно разрешить все эти законные binary inventories.
case(
    "unused-probe-in-api-client-string",
    student={"Probe.java": "public class Probe {CANARY}"},
    apiClient=True,
)
case(
    "name-only-in-trusted-comment",
    student={"CommentOnly.java": "public class CommentOnly {CANARY}"},
    trustedTail="// class CommentOnly {}",
)
case(
    "name-only-in-trusted-string",
    student={"StringOnly.java": "public class StringOnly {CANARY}"},
    trustedBody='static String text="class StringOnly {}";',
)
case(
    "name-only-in-trusted-text-block",
    student={"BlockOnly.java": "public class BlockOnly {CANARY}"},
    trustedBody='static String text="""\nclass BlockOnly {}\n""";',
)
case(
    "fake-reserved-package-in-student-comment",
    student={
        "Extra.java": "/*\npackage org.junit.fake;\n*/public class Extra {CANARY}"
    },
)
case(
    "student-nested-simple-name-distinct-binary",
    student={
        "StudentOuter.java": "public class StudentOuter {CANARY static class Probe{}}"
    },
    testName="Probe",
)
case(
    "trusted-nested-simple-name-distinct-binary",
    student={"Nested.java": "public class Nested {CANARY}"},
    trustedBody="static class Nested{}",
)
case(
    "student-comment-not-trusted-binary",
    student={"Extra.java": "public class Extra{CANARY /* class TrustedTest{} */}"},
)
case(
    "student-string-not-trusted-binary",
    student={
        "Extra.java": 'public class Extra{CANARY static String text="class TrustedTest{}";}'
    },
)
case(
    "student-text-block-not-trusted-binary",
    student={
        "Extra.java": 'public class Extra{CANARY static String text="""\nclass TrustedTest{}\n""";}'
    },
)
# Удаление namespace или binary guard должно сломать эти отрицательные случаи.
for package in [
    "org.junit.shadow",
    "org.prairielearn.shadow",
    "org.json.shadow",
    "javax.custom",
]:
    CASES.append(
        dict(
            name="reserved-" + package.replace(".", "-"),
            expected="unsafe-submission",
            api=True,
            student={
                package.replace(".", "/")
                + "/Evil.java": f"package {package};public class Evil {{CANARY}}"
            },
            trusted="not-run",
            apiRan=False,
        )
    )
CASES.append(
    dict(
        name="unicode-escaped-reserved-package",
        expected="unsafe-submission",
        api=True,
        student={
            "Evil.java": r"package org.\u006aunit.shadow;public class Evil{CANARY}"
        },
        trusted="not-run",
        apiRan=False,
    )
)
CASES.append(
    dict(
        name="reserved-adapter-prefix",
        expected="unsafe-submission",
        api=True,
        student={
            "PlatformJUnitAdapterHelper.java": "public class PlatformJUnitAdapterHelper{CANARY}"
        },
        trusted="not-run",
        apiRan=False,
    )
)
CASES.append(
    dict(
        name="actual-trusted-binary",
        expected="unsafe-submission",
        api=True,
        student={"TrustedTest.java": "public class TrustedTest{CANARY}"},
        trusted="success",
        apiRan=True,
    )
)
CASES.append(
    dict(
        name="actual-api-binary",
        expected="unsafe-submission",
        api=True,
        student={"PublishedApi.java": "public class PublishedApi{CANARY}"},
        trusted="not-run",
        apiRan=False,
    )
)
CASES.append(
    dict(
        name="unicode-escaped-api-binary",
        expected="unsafe-submission",
        api=True,
        student={"PublishedApi.java": r"public class \u0050ublishedApi{CANARY}"},
        trusted="not-run",
        apiRan=False,
    )
)
CASES.append(
    dict(
        name="unicode-escaped-nested-api-binary",
        expected="unsafe-submission",
        api=True,
        student={"ApiOuter$Inner.java": r"public class \u0041piOuter$Inner{CANARY}"},
        apiExtra="class ApiOuter{static class Inner{}}",
        trusted="not-run",
        apiRan=False,
    )
)
CASES.append(
    dict(
        name="unicode-escaped-trusted-binary",
        expected="unsafe-submission",
        api=True,
        student={"TrustedTest.java": r"public class \u0054rustedTest{CANARY}"},
        trusted="success",
        apiRan=True,
    )
)
CASES.append(
    dict(
        name="compile-failure-not-unsafe",
        expected="student-compilation-failure",
        api=True,
        student={
            "Broken.java": "/* class PublishedApi{} */ public class Broken { this is not Java; }"
        },
        trusted="not-run",
        apiRan=False,
    )
)
# student-tests компилирует trusted fixture первым, guard сохраняет этот факт.
for name, changes in [
    ("student-tests-comment", dict(testTail="// class Impl {}")),
    (
        "student-tests-nested",
        dict(testBody="static class Nested{}", fixtureBody="static class Nested{}"),
    ),
    (
        "student-tests-actual-binary",
        dict(
            expected="unsafe-submission",
            student={
                "Impl.java": "public class Impl{CANARY public static int value(){return 42;}}"
            },
        ),
    ),
    (
        "student-tests-reserved",
        dict(
            expected="unsafe-submission",
            student={
                "org/prairielearn/Evil.java": "package org.prairielearn;public class Evil{CANARY}"
            },
        ),
    ),
    (
        "student-tests-compile-failure",
        dict(
            expected="student-compilation-failure",
            testSource="/* class Impl{} */ public class StudentSuite { this is not Java; }",
        ),
    ),
]:
    CASES.append(
        dict(
            name=name,
            expected=changes.pop("expected", "success"),
            api=False,
            mutation=True,
            trusted="success",
            apiRan=False,
            **changes,
        )
    )


def execute(c, platform, output):
    job = output / c["name"]
    (job / "student").mkdir(parents=True)
    (job / "tests").mkdir()
    studentMarker = job / "student-initialized"
    apiMarker = job / "api-executed"
    junitMarker = job / "junit-executed"
    canary = (
        "static{try{java.nio.file.Files.writeString(java.nio.file.Path.of("
        + json.dumps(str(studentMarker))
        + '),"INITIALIZED");}catch(java.io.IOException e){throw new AssertionError(e);}}'
    )
    source = {"Answer.java": "public class Answer{CANARY}"}
    tests = {}
    mode = "student-tests" if c.get("mutation") else "implementation"
    if c.get("mutation"):
        source = {
            "StudentSuite.java": c.get(
                "testSource",
                "import org.junit.jupiter.api.Test;import static org.junit.jupiter.api.Assertions.*;public class StudentSuite{"
                + c.get("testBody", "")
                + "@Test void actual(){assertEquals(42,Impl.value());}}"
                + c.get("testTail", ""),
            )
        }
        for key, value in [("correct", 42), ("wrong", 41)]:
            tests[f"variants/{key}/Impl.java"] = (
                "public class Impl{"
                + c.get("fixtureBody", "")
                + f"public static int value(){{return {value};}}"
                + "}"
            )
    else:
        n = c.get("testName", "TrustedTest")
        tests[n + ".java"] = (
            "import org.junit.jupiter.api.Test;import static org.junit.jupiter.api.Assertions.*;public class "
            + n
            + "{static{try{java.nio.file.Files.writeString(java.nio.file.Path.of("
            + json.dumps(str(junitMarker))
            + '),"RUN");}catch(java.io.IOException e){throw new AssertionError(e);}}'
            + c.get("trustedBody", "")
            + "@Test void actual(){assertTrue(true);}}"
            + c.get("trustedTail", "")
        )
        if c.get("api"):
            tests["PublishedApi.java"] = (
                "import org.prairielearn.api.PlatformApiPrecheck;public class PublishedApi{static{try{java.nio.file.Files.writeString(java.nio.file.Path.of("
                + json.dumps(str(apiMarker))
                + '),"RUN");}catch(java.io.IOException e){throw new AssertionError(e);}}public static void check(PlatformApiPrecheck.Api api)throws Exception{api.type("Answer");'
                + (
                    'api.compiles("Probe","class Probe{}",true);'
                    if c.get("apiClient")
                    else ""
                )
                + "}}"
                + c.get("apiExtra", "")
            )
    source.update(c.get("student", {}))
    for root, files in [(job / "student", source), (job / "tests", tests)]:
        for name, body in files.items():
            f = root / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body.replace("CANARY", canary))
    cfg = {
        "schemaVersion": 1,
        "sourceFiles": list(source),
        "testFiles": list(tests),
        "mode": mode,
        "runtime": "java25-mutation-v1" if c.get("mutation") else "java25-junit-v1",
        "java": {
            "release": 25,
            "encoding": "UTF-8",
            "compiler-options": ["-proc:none", "-Xmaxerrs", "5"],
        },
        "limits": {
            "outer-seconds": 30,
            "compile-seconds": 15,
            "run-seconds": 5,
            "max-output-bytes": 65536,
            "networking": False,
        },
        "scoring": {"mode": "all-pass"},
        "discovery": {"min-executed": 1, "allow-skipped": False},
    }
    if c.get("api"):
        cfg["apiPrecheck"] = {"files": ["PublishedApi.java"], "entry": "PublishedApi"}
    if c.get("mutation"):
        cfg["variants"] = {"correct": ["correct"], "mutants": ["wrong"]}
    (job / "tests/grading-job.json").write_text(json.dumps(cfg))
    argv = [
        sys.executable,
        str(platform / "images/java25-grader/grade.py"),
        "--job-dir",
        str(job),
        "--verification",
    ]
    run = subprocess.run(argv, capture_output=True, text=True, timeout=90)
    rp = job / "results/results.json"
    r = json.loads(rp.read_text()) if rp.exists() else {}
    errors = []
    if r.get("classification") != c["expected"]:
        errors.append(
            "classification expected "
            + c["expected"]
            + " observed "
            + str(r.get("classification"))
        )
    if c["expected"] == "success":
        if r.get("score") != 1 or not r.get("gradable"):
            errors.append("expected gradable score1")
    else:
        if c["expected"] == "student-compilation-failure":
            if r.get("gradable") is not True or r.get("score") != 0:
                errors.append(
                    "Собственная некомпиляция должна дать ноль текущей попытки"
                )
        elif r.get("gradable") or "score" in r:
            errors.append("Защитный отказ остаётся без оценки")
        if r.get("studentCompilation") != (
            "failure" if c["expected"] == "student-compilation-failure" else "success"
        ):
            errors.append("wrong studentCompilation stage")
        if r.get("trustedCompilation") != c["trusted"]:
            errors.append("wrong trustedCompilation stage")
        if "execution" in r.get("durations", {}):
            errors.append("behavior ran before rejection")
        if c.get("api") and r.get("apiPrecheck") != (
            "success" if c.get("apiRan") else "not-run"
        ):
            errors.append("wrong API execution stage")
        if c.get("api") and r.get("dependentExecution") != "not-run":
            errors.append("dependent execution must be not-run")
    if studentMarker.exists():
        errors.append("student static initializer executed")
    if c.get("api"):
        want = c.get("apiRan", c["expected"] == "success")
        if apiMarker.exists() != want:
            errors.append("wrong actual API canary execution")
        if c.get("apiRan") and r.get("apiContainment") != "host-diagnostic":
            errors.append("completed API phase lost actual host containment")
        if (
            c["expected"] == "unsafe-submission"
            and not c.get("apiRan")
            and "apiContainment" in r
        ):
            errors.append("containment claimed for API phase not executed")
    if c["expected"] != "success" and junitMarker.exists():
        errors.append("JUnit executed before rejection")
    row = {
        "name": c["name"],
        "expected": c["expected"],
        "classification": r.get("classification"),
        "passed": not errors,
        "errors": errors,
        "exitCode": run.returncode,
        "argv": argv,
        "stdout": run.stdout,
        "stderr": run.stderr,
        "receipt": str(rp),
        "studentCanary": studentMarker.exists(),
        "apiCanary": apiMarker.exists(),
        "junitCanary": junitMarker.exists(),
        "sourceHashes": {
            str(p.relative_to(job)): hashlib.sha256(p.read_bytes()).hexdigest()
            for root in [job / "student", job / "tests"]
            for p in root.rglob("*")
            if p.is_file()
        },
    }
    print(
        "PASS" if not errors else "FAIL",
        c["name"],
        r.get("classification"),
        "; ".join(errors),
        flush=True,
    )
    return row


class CompiledClassInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)


def install_case(case):
    def check(self):
        result = execute(case, unit_platform(self), self.output)
        self.assertTrue(
            result["passed"], json.dumps(result, ensure_ascii=False, indent=2)
        )

    check.__doc__ = case["name"]
    setattr(
        CompiledClassInventoryTests, "test_" + case["name"].replace("-", "_"), check
    )


for item in CASES:
    install_case(item)

if __name__ == "__main__":
    unittest.main()
