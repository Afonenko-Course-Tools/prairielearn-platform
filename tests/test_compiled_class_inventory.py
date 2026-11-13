"""Настоящие binary inventories вместо догадок по Java source: JDK25 и canaries."""

from pathlib import Path
from dataclasses import dataclass, field
from typing import TypedDict
import hashlib, json, subprocess, sys, tempfile, unittest
from gradle_unit_fixtures import unit_platform
from grading_types import JavaGradingDescriptor
from json_boundary import JSONObject, JSONValue, json_object

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class InventoryCase:
    name: str
    expected: str = "success"
    api: bool = True
    student: dict[str, str] = field(default_factory=dict[str, str])
    apiClient: bool = False
    trustedTail: str = ""
    trustedBody: str = ""
    testName: str = "TrustedTest"
    trusted: str = "not-run"
    apiRan: bool | None = None
    apiExtra: str = ""
    mutation: bool = False
    testTail: str = ""
    testBody: str = ""
    fixtureBody: str = ""
    testSource: str | None = None


class InventoryReport(TypedDict):
    name: str
    expected: str
    classification: JSONValue
    passed: bool
    errors: list[str]
    exitCode: int
    argv: list[str]
    stdout: str
    stderr: str
    receipt: str
    studentCanary: bool
    apiCanary: bool
    junitCanary: bool
    sourceHashes: dict[str, str]


CASES: list[InventoryCase] = []


def case(
    name: str,
    *,
    student: dict[str, str],
    apiClient: bool = False,
    trustedTail: str = "",
    trustedBody: str = "",
    testName: str = "TrustedTest",
) -> None:
    CASES.append(
        InventoryCase(
            name=name,
            student=student,
            apiClient=apiClient,
            trustedTail=trustedTail,
            trustedBody=trustedBody,
            testName=testName,
        )
    )


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
        InventoryCase(
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
    InventoryCase(
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
    InventoryCase(
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
    InventoryCase(
        name="actual-trusted-binary",
        expected="unsafe-submission",
        api=True,
        student={"TrustedTest.java": "public class TrustedTest{CANARY}"},
        trusted="success",
        apiRan=True,
    )
)
CASES.append(
    InventoryCase(
        name="actual-api-binary",
        expected="unsafe-submission",
        api=True,
        student={"PublishedApi.java": "public class PublishedApi{CANARY}"},
        trusted="not-run",
        apiRan=False,
    )
)
CASES.append(
    InventoryCase(
        name="unicode-escaped-api-binary",
        expected="unsafe-submission",
        api=True,
        student={"PublishedApi.java": r"public class \u0050ublishedApi{CANARY}"},
        trusted="not-run",
        apiRan=False,
    )
)
CASES.append(
    InventoryCase(
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
    InventoryCase(
        name="unicode-escaped-trusted-binary",
        expected="unsafe-submission",
        api=True,
        student={"TrustedTest.java": r"public class \u0054rustedTest{CANARY}"},
        trusted="success",
        apiRan=True,
    )
)
CASES.append(
    InventoryCase(
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
CASES.extend(
    [
        InventoryCase(
            "student-tests-comment",
            api=False,
            mutation=True,
            trusted="success",
            apiRan=False,
            testTail="// class Impl {}",
        ),
        InventoryCase(
            "student-tests-nested",
            api=False,
            mutation=True,
            trusted="success",
            apiRan=False,
            testBody="static class Nested{}",
            fixtureBody="static class Nested{}",
        ),
        InventoryCase(
            "student-tests-actual-binary",
            expected="unsafe-submission",
            api=False,
            mutation=True,
            trusted="success",
            apiRan=False,
            student={
                "Impl.java": "public class Impl{CANARY public static int value(){return 42;}}"
            },
        ),
        InventoryCase(
            "student-tests-reserved",
            expected="unsafe-submission",
            api=False,
            mutation=True,
            trusted="success",
            apiRan=False,
            student={
                "org/prairielearn/Evil.java": "package org.prairielearn;public class Evil{CANARY}"
            },
        ),
        InventoryCase(
            "student-tests-compile-failure",
            expected="student-compilation-failure",
            api=False,
            mutation=True,
            trusted="success",
            apiRan=False,
            testSource="/* class Impl{} */ public class StudentSuite { this is not Java; }",
        ),
    ]
)


def execute(c: InventoryCase, platform: Path, output: Path) -> InventoryReport:
    job = output / c.name
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
    tests: dict[str, str] = {}
    mode = "student-tests" if c.mutation else "implementation"
    if c.mutation:
        source = {
            "StudentSuite.java": c.testSource
            if c.testSource is not None
            else (
                "import org.junit.jupiter.api.Test;import static org.junit.jupiter.api.Assertions.*;public class StudentSuite{"
                + c.testBody
                + "@Test void actual(){assertEquals(42,Impl.value());}}"
                + c.testTail
            )
        }
        for key, value in [("correct", 42), ("wrong", 41)]:
            tests[f"variants/{key}/Impl.java"] = (
                "public class Impl{"
                + c.fixtureBody
                + f"public static int value(){{return {value};}}"
                + "}"
            )
    else:
        n = c.testName
        tests[n + ".java"] = (
            "import org.junit.jupiter.api.Test;import static org.junit.jupiter.api.Assertions.*;public class "
            + n
            + "{static{try{java.nio.file.Files.writeString(java.nio.file.Path.of("
            + json.dumps(str(junitMarker))
            + '),"RUN");}catch(java.io.IOException e){throw new AssertionError(e);}}'
            + c.trustedBody
            + "@Test void actual(){assertTrue(true);}}"
            + c.trustedTail
        )
        if c.api:
            tests["PublishedApi.java"] = (
                "import org.prairielearn.api.PlatformApiPrecheck;public class PublishedApi{static{try{java.nio.file.Files.writeString(java.nio.file.Path.of("
                + json.dumps(str(apiMarker))
                + '),"RUN");}catch(java.io.IOException e){throw new AssertionError(e);}}public static void check(PlatformApiPrecheck.Api api)throws Exception{api.type("Answer");'
                + ('api.compiles("Probe","class Probe{}",true);' if c.apiClient else "")
                + "}}"
                + c.apiExtra
            )
    source.update(c.student)
    for root, files in [(job / "student", source), (job / "tests", tests)]:
        for name, body in files.items():
            f = root / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body.replace("CANARY", canary))
    cfg: JavaGradingDescriptor = {
        "schemaVersion": 1,
        "sourceFiles": list(source),
        "testFiles": list(tests),
        "mode": mode,
        "runtime": "java25-mutation-v1" if c.mutation else "java25-junit-v1",
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
    if c.api:
        cfg["apiPrecheck"] = {"files": ["PublishedApi.java"], "entry": "PublishedApi"}
    if c.mutation:
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
    r: JSONObject = {}
    if rp.exists():
        decoded: object = json.loads(rp.read_text())
        r = json_object(decoded)
    errors: list[str] = []
    if r.get("classification") != c.expected:
        errors.append(
            "classification expected "
            + c.expected
            + " observed "
            + str(r.get("classification"))
        )
    if c.expected == "success":
        if r.get("score") != 1 or not r.get("gradable"):
            errors.append("expected gradable score1")
    else:
        if c.expected == "student-compilation-failure":
            if r.get("gradable") is not True or r.get("score") != 0:
                errors.append(
                    "Собственная некомпиляция должна дать ноль текущей попытки"
                )
        elif r.get("gradable") or "score" in r:
            errors.append("Защитный отказ остаётся без оценки")
        if r.get("studentCompilation") != (
            "failure" if c.expected == "student-compilation-failure" else "success"
        ):
            errors.append("wrong studentCompilation stage")
        if r.get("trustedCompilation") != c.trusted:
            errors.append("wrong trustedCompilation stage")
        durations = r.get("durations", {})
        if not isinstance(durations, dict):
            raise ValueError("Некорректная форма durations в результате grader")
        if "execution" in durations:
            errors.append("behavior ran before rejection")
        if c.api and r.get("apiPrecheck") != ("success" if c.apiRan else "not-run"):
            errors.append("wrong API execution stage")
        if c.api and r.get("dependentExecution") != "not-run":
            errors.append("dependent execution must be not-run")
    if studentMarker.exists():
        errors.append("student static initializer executed")
    if c.api:
        want = c.apiRan if c.apiRan is not None else c.expected == "success"
        if apiMarker.exists() != want:
            errors.append("wrong actual API canary execution")
        if c.apiRan and r.get("apiContainment") != "host-diagnostic":
            errors.append("completed API phase lost actual host containment")
        if c.expected == "unsafe-submission" and not c.apiRan and "apiContainment" in r:
            errors.append("containment claimed for API phase not executed")
    if c.expected != "success" and junitMarker.exists():
        errors.append("JUnit executed before rejection")
    row: InventoryReport = {
        "name": c.name,
        "expected": c.expected,
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
        c.name,
        r.get("classification"),
        "; ".join(errors),
        flush=True,
    )
    return row


class CompiledClassInventoryTests(unittest.TestCase):
    output: Path

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)


def install_case(case: InventoryCase) -> None:
    def check(self: CompiledClassInventoryTests) -> None:
        result = execute(case, unit_platform(self), self.output)
        self.assertTrue(
            result["passed"], json.dumps(result, ensure_ascii=False, indent=2)
        )

    check.__doc__ = case.name
    setattr(CompiledClassInventoryTests, "test_" + case.name.replace("-", "_"), check)


for item in CASES:
    install_case(item)

if __name__ == "__main__":
    unittest.main()
