"""Типы выбранных проверок; границы подтверждаются собственными JSON Schema."""

from __future__ import annotations
from typing import (
    TYPE_CHECKING,
    Generic,
    Literal,
    NotRequired,
    TypeAlias,
    TypeVar,
    TypedDict,
)

if TYPE_CHECKING:
    from junit_result import JUnitCase, JUnitCounts, RawResult, RawTest


# Draft202012 допускает integral float как integer; целочисленность проверяет схема.
JSONInteger: TypeAlias = int | float


class SelectedFile(TypedDict):
    name: str
    target: str
    data: str


class ReferenceDeclaration(TypedDict):
    name: str
    root: str
    optional: NotRequired[bool]


class SourceProfile(TypedDict):
    mode: Literal["implementation", "student-tests"]
    root: str
    include: list[str]


class ApiPrecheck(TypedDict):
    files: list[str]
    entry: str


class VariantDeclaration(TypedDict):
    correct: list[str]
    mutants: list[str]


CountExpectation = TypedDict(
    "CountExpectation",
    {"at-least": NotRequired[JSONInteger], "exactly": NotRequired[JSONInteger]},
)
ScoreExpectation = TypedDict(
    "ScoreExpectation",
    {
        "at-least": NotRequired[float],
        "exactly": NotRequired[float],
        "less-than": NotRequired[float],
    },
)
Expectations = TypedDict(
    "Expectations",
    {
        "student-compilation": NotRequired[str],
        "job": NotRequired[str],
        "classification": NotRequired[str],
        "required-tests": NotRequired[str],
        "failed-tests": NotRequired[CountExpectation],
        "executed-tests": NotRequired[CountExpectation],
        "test-ids": NotRequired[list[str]],
        "score": NotRequired[ScoreExpectation],
    },
)
JavaOverrides = TypedDict(
    "JavaOverrides",
    {
        "release": NotRequired[JSONInteger],
        "encoding": NotRequired[str],
        "compiler-options": NotRequired[list[str]],
    },
)
LimitOverrides = TypedDict(
    "LimitOverrides",
    {
        "outer-seconds": NotRequired[float],
        "compile-seconds": NotRequired[float],
        "run-seconds": NotRequired[float],
        "networking": NotRequired[bool],
        "max-output-bytes": NotRequired[JSONInteger],
    },
)
DiscoveryOverrides = TypedDict(
    "DiscoveryOverrides",
    {"min-executed": NotRequired[JSONInteger], "allow-skipped": NotRequired[bool]},
)
AdditionalSourceDeclaration = TypedDict(
    "AdditionalSourceDeclaration",
    {
        "archive": str,
        "max-files": JSONInteger,
        "max-file-bytes": JSONInteger,
        "max-total-bytes": JSONInteger,
        "max-archive-bytes": JSONInteger,
        "primary-required": NotRequired[bool],
        "allow-additional": NotRequired[bool],
    },
)
JavaBuildDeclaration = TypedDict(
    "JavaBuildDeclaration",
    {
        "kind": str,
        "artifact": str,
        "main-class": NotRequired[str],
    },
)


class WeightedScoring(TypedDict):
    mode: Literal["weighted"]


class AllPassScoring(TypedDict):
    mode: Literal["all-pass"]


class ScoringGroup(TypedDict):
    id: str
    weight: float
    tests: list[str]


class GroupScoring(TypedDict):
    mode: Literal["contract-groups"]
    groups: list[ScoringGroup]


class ThresholdScoring(TypedDict):
    mode: Literal["threshold"]
    basis: Literal["score", "passed-tests"]
    value: float


Scoring = WeightedScoring | AllPassScoring | GroupScoring | ThresholdScoring


class VerificationExpectations(TypedDict):
    reference: NotRequired[Expectations]
    starter: NotRequired[Expectations]


ProjectCheck = TypedDict(
    "ProjectCheck",
    {
        "runtime": str,
        "profile": NotRequired[str],
        "source-profile": NotRequired[str],
        "sourceProfile": NotRequired[SourceProfile],
        "mode": NotRequired[str],
        "java": NotRequired[JavaOverrides],
        "limits": NotRequired[LimitOverrides],
        "scoring": NotRequired[Scoring],
        "discovery": NotRequired[DiscoveryOverrides],
        "references": NotRequired[list[ReferenceDeclaration]],
        "tests": NotRequired[list[str]],
        "verification-tests": NotRequired[list[str]],
        "contract-cases": NotRequired[str],
        "verification-expectations": NotRequired[VerificationExpectations],
        "variants": NotRequired[VariantDeclaration],
        "api-precheck": NotRequired[ApiPrecheck],
        "verification-api-precheck": NotRequired[ApiPrecheck],
        "additional-java-sources": NotRequired[AdditionalSourceDeclaration],
        "java-build": NotRequired[JavaBuildDeclaration],
    },
)


class SelectedReference(TypedDict):
    name: str
    root: str
    optional: bool
    available: bool
    group: str
    targets: list[str]
    sources: list[SelectedFile]


class Readiness(TypedDict):
    ready: bool
    missing: list[str]


class ArtifactPolicy(TypedDict):
    student: NotRequired[str]
    full: str
    conditions: bool


class CommonFile(TypedDict):
    source: str
    target: str
    audience: str


class Materialization(TypedDict):
    commonFiles: list[CommonFile]
    includeGit: NotRequired[bool]


class NativeProject(TypedDict):
    qualifiedId: str
    projectRoot: str
    source: str
    exerciseId: str
    check: ProjectCheck
    sources: list[SelectedFile]
    trustedTests: list[SelectedFile]
    verificationTests: list[SelectedFile]
    references: list[SelectedReference]
    contractFixtures: list[SelectedFile]
    readiness: Readiness
    apiPrecheck: NotRequired[ApiPrecheck]
    verificationApiPrecheck: NotRequired[ApiPrecheck]
    contractCases: NotRequired[SelectedFile]
    bankMember: NotRequired[bool]
    purpose: NotRequired[str]
    statementVisibility: NotRequired[str]
    artifactPolicy: NotRequired[ArtifactPolicy]
    materialization: NotRequired[Materialization]


class NativeChecks(TypedDict):
    schemaVersion: JSONInteger
    courseId: str
    bookRoot: str
    projects: list[NativeProject]


class ContractSource(TypedDict):
    fixture: str
    submission: str


class ContractCase(TypedDict):
    id: str
    sources: list[ContractSource]
    expected: Expectations


class ContractCases(TypedDict):
    schemaVersion: JSONInteger
    cases: list[ContractCase]


class Scenario(TypedDict):
    qualifiedId: str
    scenario: str
    optional: bool


JavaConfig = TypedDict(
    "JavaConfig",
    {
        "release": JSONInteger,
        "encoding": str,
        "compiler-options": list[str],
    },
)
RunLimits = TypedDict(
    "RunLimits",
    {
        "outer-seconds": float,
        "compile-seconds": float,
        "run-seconds": float,
        "networking": bool,
        "max-output-bytes": JSONInteger,
    },
)
Discovery = TypedDict("Discovery", {"min-executed": JSONInteger, "allow-skipped": bool})


class AdditionalSourcePolicy(TypedDict):
    archive: str
    maxFiles: JSONInteger
    maxFileBytes: JSONInteger
    maxTotalBytes: JSONInteger
    maxArchiveBytes: JSONInteger
    primaryRequired: NotRequired[bool]
    allowAdditional: NotRequired[bool]


class JavaBuild(TypedDict):
    kind: str
    artifact: str
    mainClass: NotRequired[str]


class GradingDescriptorBase(TypedDict):
    schemaVersion: JSONInteger
    sourceFiles: list[str]
    testFiles: list[str]
    mode: str
    limits: RunLimits
    scoring: Scoring
    discovery: Discovery
    variants: NotRequired[VariantDeclaration]
    apiPrecheck: NotRequired[ApiPrecheck]
    additionalJavaSources: NotRequired[AdditionalSourcePolicy]
    javaBuild: NotRequired[JavaBuild]


class JavaGradingDescriptor(GradingDescriptorBase):
    runtime: Literal["java25-junit-v1", "java25-mutation-v1", "java25-gradle-junit-v1"]
    java: JavaConfig


class FishGradingDescriptor(GradingDescriptorBase):
    runtime: Literal["fish-git-v1"]


GradingDescriptor = JavaGradingDescriptor | FishGradingDescriptor


class ArtifactEvidence(TypedDict):
    path: str
    bytes: JSONInteger


class AdditionalSourcesEvidence(TypedDict):
    archive: str
    files: list[ArtifactEvidence]


class BuildEvidence(TypedDict):
    schemaVersion: JSONInteger
    kind: str
    status: str
    durationSeconds: NotRequired[float]
    artifact: NotRequired[ArtifactEvidence]
    reason: NotRequired[str]


class ApiDiagnostic(TypedDict):
    expected: str
    observed: str


CountsT = TypeVar("CountsT")


class Outcome(TypedDict, Generic[CountsT]):
    classification: str
    infrastructure: str
    gradable: bool
    grading_error: NotRequired[bool]
    studentCompilation: NotRequired[str]
    trustedCompilation: NotRequired[str]
    dependentExecution: NotRequired[str]
    apiPrecheck: NotRequired[str]
    apiContainment: NotRequired[str]
    apiDiagnostic: NotRequired[ApiDiagnostic]
    counts: NotRequired[CountsT]
    score: NotRequired[float]
    maxPoints: NotRequired[float]
    rawResult: NotRequired[RawResult]
    durations: NotRequired[dict[str, float]]
    diagnostics: NotRequired[dict[str, str]]
    toolchain: NotRequired[str]
    scoring: NotRequired[Scoring]
    output: NotRequired[str]
    message: NotRequired[str]
    format_errors: NotRequired[str]
    timed_out: NotRequired[bool]
    output_limited: NotRequired[bool]
    containment: NotRequired[str]
    tests: NotRequired[list[RawTest]]
    variants: NotRequired[dict[str, Outcome[CountsT]]]
    publicResult: NotRequired[Outcome[CountsT]]
    additionalSources: NotRequired[AdditionalSourcesEvidence]
    buildEvidence: NotRequired[BuildEvidence]
    reportFormat: NotRequired[str]


class JavaOutcome(Outcome["JUnitCounts"]):
    pass


class ResultCounts(TypedDict):
    discovered: JSONInteger
    executed: JSONInteger
    passed: JSONInteger
    failed: JSONInteger
    skipped: JSONInteger
    aborted: JSONInteger
    containerFailures: JSONInteger
    outcomes: dict[str, str]
    failureKinds: NotRequired[dict[str, str]]
    complete: NotRequired[bool]
    eventErrors: NotRequired[JSONInteger]
    registered: NotRequired[list[str]]
    started: NotRequired[list[str]]
    cases: NotRequired[list[JUnitCase]]
    feedbackProtocolVersion: NotRequired[JSONInteger]


class JobBindings(TypedDict):
    scope: str
    qualifiedId: str
    scenario: str
    runtime: str
    imageDigest: str | None


class GradingJobPayload(JobBindings):
    schemaVersion: JSONInteger
    sources: list[SelectedFile]
    trustedTests: list[SelectedFile]
    grading: GradingDescriptor
    verificationTests: NotRequired[list[SelectedFile]]
    expectations: NotRequired[Expectations]


class CheckResult(Outcome[ResultCounts], JobBindings):
    schemaVersion: JSONInteger
    backend: str


class UnavailableReference(TypedDict):
    qualifiedId: str
    scenario: str
    status: NotRequired[str]


class QuestionBinding(TypedDict):
    qualifiedId: str
    runtime: str
    imageDigest: str | None


class ExpectationResult(TypedDict):
    qualifiedId: str
    scenario: str
    matched: bool
    reason: str


class BuildStageFacts(TypedDict, total=False):
    classification: str
    infrastructure: str
    studentCompilation: str
    trustedCompilation: str
    apiPrecheck: str
    dependentExecution: str


class BuildReceipt(BuildEvidence):
    qualifiedId: str
    scenario: str
    outcome: BuildStageFacts


class VerificationReceipt(TypedDict):
    schemaVersion: int
    toolVersion: str
    backend: str
    scope: str
    status: str
    exitCode: int
    coverage: str
    scenarios: list[Scenario]
    unavailableReferences: list[UnavailableReference]
    checkedIds: list[str]
    questionBindings: list[QuestionBinding]
    runtimes: dict[str, str | None]
    expectations: list[ExpectationResult]
    buildEvidence: NotRequired[list[BuildReceipt]]


class PublicCase(TypedDict):
    name: str
    status: str
    expected: NotRequired[str]
    actual: NotRequired[str]
    message: NotRequired[str]
    exceptionType: NotRequired[str]
    stackTrace: NotRequired[str]


class CompileError(TypedDict):
    file: str
    line: int
    reason: str
    message: NotRequired[str]


class PublicApi(TypedDict):
    expected: str
    actual: str


class PublicFeedback(TypedDict):
    kind: str
    reason: str
    observed: str
    whatCheck: str
    cases: NotRequired[list[PublicCase]]
    compileErrors: NotRequired[list[CompileError]]
    api: NotRequired[PublicApi]


class PublicTest(TypedDict):
    name: str
    description: str
    message: str
    points: int
    max_points: int


class StudentResult(TypedDict):
    gradable: bool
    classification: str
    feedback: PublicFeedback
    message: str
    output: NotRequired[str]
    score: NotRequired[float]
    format_errors: NotRequired[str]
    grading_error: NotRequired[bool]
    tests: NotRequired[list[PublicTest]]


class RuntimeProfile(TypedDict):
    bundle: str
    mode: str
    image: str | None
    runner: NotRequired[str]
    javaRelease: NotRequired[int]
    assertionFeedbackProtocol: NotRequired[int]
    baseImage: NotRequired[str]
    upstreamCommit: NotRequired[str]
    sourceExtensions: NotRequired[list[str]]


class RuntimeRegistry(TypedDict):
    schemaVersion: int
    profiles: dict[str, RuntimeProfile]
    workspaceImages: NotRequired[dict[str, dict[str, str]]]
