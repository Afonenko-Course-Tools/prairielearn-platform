package org.prairielearn.feedback;
/** Техническая граница generated bridge; не API учебной задачи. */
public interface ProjectionAccess {
  Object $pl$c3$component(int ordinal);
  static void require(Object value) {
    org.prairielearn.feedback.internal.State.requireProjection(value);
  }
}
