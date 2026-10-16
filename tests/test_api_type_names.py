"""Discovery имён — реальные compiled classes, без загрузки и исполнения."""
from pathlib import Path
import unittest
import test_grading_job as fixture

class ApiTypeNamesTests(unittest.TestCase):
    setUp=fixture.JUnitJob.setUp
    def source(self,path,code):
        target=self.job/'student'/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(code);self.cfg['sourceFiles'].append(path)
    def precheck(self,body):
        self.cfg['testFiles'].append('Names.java');self.cfg['apiPrecheck']={'files':['Names.java'],'entry':'Names'}
        (self.job/'tests/Names.java').write_text('import org.prairielearn.api.PlatformApiPrecheck;public class Names {public static void check(PlatformApiPrecheck.Api api)throws Exception {'+body+'}}')
        try:return fixture.JUnitJob.run_job(self)
        except fixture.grader.GraderError as error:self.fail(str(error))
    def test_sorted_immutable_default_named_and_nested_names_without_initialization(self):
        self.source('GenericQueue.java','public class GenericQueue {static {System.setProperty("queue.initialized","yes");}}')
        self.source('z/Holder.java','package z; public class Holder {public static class GenericQueue {static {System.setProperty("queue.initialized","yes");}}}')
        self.source('a/GenericQueue.java','package a; public class GenericQueue {static {System.setProperty("queue.initialized","yes");}}')
        result=self.precheck('''var names=api.typeNames("GenericQueue");api.expect(names.equals(java.util.List.of("GenericQueue","a.GenericQueue","z.Holder$GenericQueue")),"все compiled binary names в сортировке",names.toString());try{names.add("changed");throw new AssertionError("mutable");}catch(UnsupportedOperationException expected){}for(String name:names)api.type(name);api.expect(System.getProperty("queue.initialized")==null,"без инициализации","инициализирован");''')
        self.assertEqual('success',result['classification'])
    def test_only_exact_simple_name_and_public_selection_is_left_to_course(self):
        self.source('p/Types.java','package p; class Types {private static class GenericQueue {}} class GenericQueueHelper {}')
        result=self.precheck('var names=api.typeNames("GenericQueue");api.expect(names.equals(java.util.List.of("p.Types$GenericQueue")),"точное имя, включая nonpublic кандидата",names.toString());api.expect(api.typeNames("Absent").isEmpty(),"пустой список","непустой");')
        self.assertEqual('success',result['classification'])
    def test_names_are_available_even_when_matching_helper_cannot_link(self):
        self.source('unlinked/GenericQueue.java','package unlinked; public class GenericQueue extends org.junit.jupiter.api.extension.ParameterResolutionException {public GenericQueue(){super("compile-only dependency");}}')
        result=self.precheck('api.expect(api.typeNames("GenericQueue").equals(java.util.List.of("unlinked.GenericQueue")),"binary name без loading","нет имени");try{api.type("unlinked.GenericQueue");throw new AssertionError("dependency unexpectedly linked");}catch(PlatformApiPrecheck.Mismatch expected){}')
        self.assertEqual('success',result['classification'])
    def test_simple_name_argument_cannot_select_paths_packages_or_keywords(self):
        result=self.precheck('for(String name:new String[]{"","../Secret","a.b","x/y","String[]","class",null}){try{api.typeNames(name);throw new AssertionError("invalid name accepted");}catch(IllegalArgumentException expected){}}')
        self.assertEqual('success',result['classification'])

if __name__=='__main__':unittest.main()
