module org.prairielearn.feedback {
  exports org.prairielearn.feedback;
  provides org.junit.jupiter.api.extension.Extension with org.prairielearn.feedback.internal.Scope;
}
