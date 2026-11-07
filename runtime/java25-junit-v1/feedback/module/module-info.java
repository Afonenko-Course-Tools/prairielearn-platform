@SuppressWarnings("requires-automatic")
module org.prairielearn.feedback {
  requires transitive org.junit.jupiter.api;
  requires transitive org.junit.platform.launcher;
  requires org.junit.platform.reporting;
  requires json.simple;
  uses org.junit.platform.engine.TestEngine;
  exports org.prairielearn.feedback;
  provides org.junit.jupiter.api.extension.Extension with org.prairielearn.feedback.internal.Scope;
}
