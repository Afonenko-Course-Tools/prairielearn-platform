"""Checks2/Job2: реальные files/JDK25, fictional unit images, без OCI claim."""
import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import grading_job as jobs
from gradle_unit_fixtures import registry

class NativeOrigins(unittest.TestCase):
 def setUp(self):
  self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup);self.root=Path(self.temporary.name);self.book=self.root/"tasks";self.project=self.book/"projects/p"
  self.files={"projects/p/starter/Main.java":"public class Main {public static int value(){return 0;}}", "projects/p/reference/Main.java":"public class Main {public static int value(){return Helper.value();}}", "projects/p/reference/Helper.java":"public class Helper {public static int value(){return 42;}}", "shared/name:api/Api.java":"public class Api {public static int expected(){return 42;}}", "projects/p/checks/OfficialTest.java":"import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; public class OfficialTest {@Test void result(){assertEquals(Api.expected(),Main.value());}}"}
  for name,text in self.files.items():p=self.book/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
  def selection(path,name,owner=False):return {"ownerRelativePath" if owner else "projectRelativePath":path if owner else str(Path(path).relative_to("projects/p")),"submissionRelativePath":name,"sha256":hashlib.sha256((self.book/path).read_bytes()).hexdigest()}
  self.select=selection
  ref={"name":"lawful","root":"author/example/src/main/java","optional":False}
  extra={"archive":"additional.zip","max-files":128,"max-file-bytes":1048576,"max-total-bytes":4194304,"max-archive-bytes":2097152}
  check={"profile":"native","runtime":"java25-junit-v1","source-profile":"main","sourceProfile":{"mode":"implementation","root":"src/main/java","include":["**/*.java"]},"tests":["src/api/java/**/*.java","src/test/java/**/*.java"],"references":[ref],"additional-java-sources":extra,"scoring":{"mode":"weighted"}}
  sources=[selection("projects/p/starter/Main.java","Main.java")];trusted=[selection("shared/name:api/Api.java","Api.java",True),selection("projects/p/checks/OfficialTest.java","OfficialTest.java")];references=[selection("projects/p/reference/Main.java","Main.java"),selection("projects/p/reference/Helper.java","Helper.java")]
  self.p={"exerciseId":"exr-p","source":"bank.qmd","projectRoot":"projects/p","bankMember":True,"statementVisibility":"open","artifactPolicy":{"student":"starter","full":"full","conditions":True},"qualifiedId":"native/exr-p","check":check,"selectionOriginVersion":2,"nativePlanGroups":["example"],"sources":sources,"trustedTests":trusted,"verificationTests":[],"references":[{**ref,"available":True,"group":"example","targets":[ref["root"]+"/"+s["submissionRelativePath"] for s in references],"sources":references}],"contractFixtures":[],"readiness":{"ready":True,"missing":[]}}
  self.scope={"schema":"pl-native-selected-checks-v1","identity":{"operation":"12345678-1234-4123-8123-123456789abc","projection":"author","runtime":"quarto-1.11.5","profiles":["full"]},"assessments":[{"source":"bank.qmd","id":"sec-work"}],"sources":[{"source":"bank.qmd","sha256":"c"*64}],"automaticIds":["native/exr-p"]}
  self.manifest={"schemaVersion":2,"selectionScope":self.scope,"courseId":"native","bookRoot":"tasks","sourceSnapshotHash":"a"*64,"inventoryHash":"b"*64,"projects":[self.p]}
 def seal(self,manifest):
  manifest["selectionScopeHash"]=jobs.digest(manifest["selectionScope"])
  normalized=[jobs._legacy_check_project(p) for p in manifest["projects"]]
  manifest["inventoryHash"]=jobs.digest(normalized);manifest["sourceSnapshotHash"]=jobs.digest({"sources":manifest["selectionScope"]["sources"],"projects":normalized})
  return manifest
 def prepare(self,scenario="reference:lawful",manifest=None):
  self.seal(self.manifest)
  job=jobs.prepare_job(manifest or self.manifest,self.root,"native/exr-p",scenario,registry=registry());self.addCleanup(shutil.rmtree,job.root);return job
 def test_reference_live_targets_shared_helper_and_actual_jdk_maps(self):
  self.assertFalse((self.project/self.p["check"]["references"][0]["root"]).exists())
  job=self.prepare();self.assertEqual(job["schemaVersion"],2);self.assertIn("owner:shared/name:api/Api.java",job["testsHashes"]);self.assertIn("project:reference/Helper.java",job["sourceHashes"]);self.assertIn("$generated/additional.zip",job["sourceHashes"])
  result=jobs.run_job(job,"host",registry());self.assertEqual(result["score"],1);self.assertEqual(result["schemaVersion"],1)
  self.assertEqual(result["nativeSelectionScopeHash"],self.manifest["selectionScopeHash"])
  for key in ["sourceHashes","testsHashes"]:self.assertEqual(job[key],result[key])
  expected={(job["qualifiedId"],job["scenario"]):{**{k:job[k] for k in ["sourceHashes","testsHashes"]},"jobSchemaVersion":2,"nativeSelectionScopeHash":job["nativeSelectionScopeHash"]}}
  receipt=jobs.verify_results([result],{},[{"qualifiedId":"native/exr-p","scenario":"reference:lawful","optional":False}],[],registry(),expected)
  report=json.loads(json.dumps({"results":[result],"receipt":receipt}));self.assertEqual(report["results"][0]["sourceHashes"],job["sourceHashes"]);self.assertNotIn("sourceHashes",receipt)
  tampered=copy.deepcopy(result);tampered["sourceHashes"][next(iter(tampered["sourceHashes"]))]="f"*64
  with self.assertRaisesRegex(jobs.JobError,"opaque maps"):jobs.verify_results([tampered],{},registry=registry(),expected_jobs=expected)
  job["testsHashes"]["owner:shared/name:api/Api.java"]="f"*64
  with self.assertRaisesRegex(jobs.JobError,"opaque.*maps"):jobs.run_job(job,"host",registry())
 def test_reference_negative_availability_group_target_and_optional_absence(self):
  mutations=[lambda p:p["references"][0].update(group="other"),lambda p:p["references"][0].update(name="fabricated"),lambda p:p["references"][0]["targets"].__setitem__(0,"author/other/Main.java"),lambda p:p["references"][0].update(available=False),lambda p:p["references"][0].update(sources=[],targets=[]),lambda p:p.update(nativePlanGroups=[])]
  for mutate in mutations:
   manifest=copy.deepcopy(self.manifest);mutate(manifest["projects"][0]);self.seal(manifest)
   with self.assertRaises(jobs.JobError):self.prepare(manifest=manifest)
  self.p["nativePlanGroups"]=[];self.p["check"]["references"][0]["optional"]=True;self.p["references"][0].update(optional=True,available=False,sources=[],targets=[])
  with self.assertRaisesRegex(jobs.JobError,"reference-unavailable:lawful"):self.prepare()
  self.p["references"][0]["available"]=True
  with self.assertRaisesRegex(jobs.JobError,"Fabricated"):self.prepare()
 def test_origin_xor_unknown_downgrade_alias_stale_and_exact_keys(self):
  for version in [0,3,1]:
   manifest=copy.deepcopy(self.manifest);manifest["schemaVersion"]=version
   with self.assertRaises(jobs.JobError):self.prepare(manifest=manifest)
  for mutate in [lambda s:s.update(ownerRelativePath="shared/file"),lambda s:s.update(projectRelativePath="../bad"),lambda s:s.update(sha256="c"*64),lambda s:s.update(extra=True)]:
   manifest=copy.deepcopy(self.manifest);mutate(manifest["projects"][0]["sources"][0]);self.seal(manifest)
   with self.assertRaises(jobs.JobError):self.prepare(manifest=manifest)
  shared=self.book/"shared/name:api/Api.java";actual=shared.read_bytes();shared.write_bytes(actual+b" ")
  with self.assertRaisesRegex(jobs.JobError,"snapshot changed"):self.prepare()
  shared.write_bytes(actual);alias=self.book/"alias";alias.symlink_to(self.book/"shared",target_is_directory=True);self.p["trustedTests"][0]["ownerRelativePath"]="alias/name:api/Api.java"
  with self.assertRaisesRegex(jobs.JobError,"Symlink"):self.prepare()
  records=[{"projectRelativePath":"$generated/a:b.java","sha256":"a"*64},{"ownerRelativePath":"$generated/a:b.java","sha256":"b"*64}];self.assertEqual(set(jobs._origin_hashes(records,2)),{"project:$generated/a:b.java","owner:$generated/a:b.java"});self.assertEqual(len(jobs._origin_hashes([records[0],records[0]],2)),1)
  with self.assertRaisesRegex(jobs.JobError,"Conflicting SHA"):jobs._origin_hashes([records[0],dict(records[0],sha256="c"*64)],2)
 def test_contract_cases_and_fixtures_use_logical_targets_with_physical_origins(self):
  cases={"schemaVersion":1,"cases":[{"id":"replacement","sources":[{"fixture":"tests/fixtures/Main.java","submission":"Main.java"}],"expected":{"job":"complete"}}]};casefile=self.book/"shared/cases.json";casefile.write_text(json.dumps(cases));fixture=self.book/"shared/fixture.java";fixture.write_text("public class Main {}")
  self.p["check"]["contract-cases"]="tests/cases.json";self.p["contractCasesHash"]={"ownerRelativePath":"shared/cases.json","logicalTarget":"tests/cases.json","sha256":hashlib.sha256(casefile.read_bytes()).hexdigest()};self.p["contractFixtures"]=[{"ownerRelativePath":"shared/fixture.java","logicalTarget":"tests/fixtures/Main.java","submissionRelativePath":"Main.java","sha256":hashlib.sha256(fixture.read_bytes()).hexdigest()}]
  self.seal(self.manifest);scenarios=jobs.scenario_inventory(self.manifest,self.root);self.assertIn("contract:replacement",[x["scenario"] for x in scenarios]);job=self.prepare("contract:replacement");self.assertIn("owner:shared/fixture.java",job["sourceHashes"]);self.assertEqual((job.root/"student/Main.java").read_bytes(),fixture.read_bytes())
  self.p["contractFixtures"][0]["logicalTarget"]="tests/fixtures/Other.java"
  with self.assertRaisesRegex(jobs.JobError,"fixture inventory missing"):self.prepare("contract:replacement")

 def test_public_verification_and_generated_marker_scope_cannot_be_dropped(self):
  self.p["verificationTests"]=copy.deepcopy(self.p["trustedTests"])
  job=self.prepare();result=jobs.run_job(job,"host",registry());self.assertEqual(result["publicResult"]["score"],1);self.assertNotIn("nativeSelectionScopeHash",result["publicResult"])
  expected={(job["qualifiedId"],job["scenario"]):{**{k:job[k] for k in ["sourceHashes","testsHashes"]},"jobSchemaVersion":2,"nativeSelectionScopeHash":job["nativeSelectionScopeHash"]}}
  downgraded=copy.deepcopy(result);del downgraded["jobSchemaVersion"];del downgraded["nativeSelectionScopeHash"]
  with self.assertRaisesRegex(jobs.JobError,"opaque maps"):jobs.verify_results([downgraded],{},registry=registry(),expected_jobs=expected)
  del job["sourceHashes"]["$generated/additional.zip"]
  with self.assertRaisesRegex(jobs.JobError,"opaque.*maps"):jobs.run_job(job,"host",registry())
 def test_selected_subset_full_and_scope_tampering(self):
  self.seal(self.manifest);jobs.inventory(self.manifest)
  for change in [lambda m:m["selectionScope"]["automaticIds"].append("native/exr-extra"),lambda m:m["selectionScope"].update(automaticIds=[]),lambda m:m["projects"].append(copy.deepcopy(m["projects"][0])),lambda m:m["selectionScope"]["assessments"].append({"source":"other.qmd","id":"sec-other"}),lambda m:m.update(inventoryHash="e"*64)]:
   m=copy.deepcopy(self.manifest);change(m)
   with self.assertRaises(jobs.JobError):jobs.inventory(m)
  old_hash=self.manifest["sourceSnapshotHash"];other=copy.deepcopy(self.manifest);other["selectionScope"]["assessments"].append({"source":"bank.qmd","id":"sec-second"});self.seal(other);self.assertEqual(old_hash,other["sourceSnapshotHash"]);self.assertNotEqual(other["selectionScopeHash"],self.manifest["selectionScopeHash"])
  full=copy.deepcopy(self.manifest);second=copy.deepcopy(self.p);second.update(exerciseId="exr-other",qualifiedId="native/exr-other",source="other.qmd");full["projects"].append(second);full["projects"].sort(key=lambda p:p["qualifiedId"]);full["selectionScope"]["automaticIds"]=[p["qualifiedId"] for p in full["projects"]];full["selectionScope"]["assessments"].append({"source":"other.qmd","id":"sec-other"});self.seal(full);self.assertEqual(len(jobs.inventory(full)),2)

if __name__=="__main__":unittest.main()
