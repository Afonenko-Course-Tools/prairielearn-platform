module org.prairielearn.feedback {
  requires org.junit.platform.console.standalone;
  exports org.prairielearn.feedback;
  provides org.junit.jupiter.api.extension.Extension with org.prairielearn.feedback.internal.Scope;
}
