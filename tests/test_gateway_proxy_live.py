"""Проверки native Student ACL с уже выданными cookie; без Bridge results API."""

import http.client
import json
import os
import pathlib
import urllib.request
import urllib.error
import unittest
from typing import ClassVar, TypeGuard, TypedDict


class Student(TypedDict):
    cookieFile: str
    userUid: str
    ownWork: str
    foreignWork: str
    ownPath: str
    foreignPath: str


class StudentFixture(TypedDict):
    privateNativeUrl: str
    host: str
    listPath: str
    students: list[Student]


class Cookie(TypedDict):
    name: str
    value: str


def object_value(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def list_value(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def student_value(value: object) -> TypeGuard[Student]:
    return object_value(value) and all(
        isinstance(value.get(key), str)
        for key in (
            "cookieFile",
            "userUid",
            "ownWork",
            "foreignWork",
            "ownPath",
            "foreignPath",
        )
    )


def student_fixture(value: object) -> TypeGuard[StudentFixture]:
    if not object_value(value) or not all(
        isinstance(value.get(key), str)
        for key in ("privateNativeUrl", "host", "listPath")
    ):
        return False
    students = value.get("students")
    return list_value(students) and all(student_value(student) for student in students)


def cookie_values(value: object) -> TypeGuard[list[Cookie]]:
    return list_value(value) and all(
        object_value(cookie)
        and isinstance(cookie.get("name"), str)
        and isinstance(cookie.get("value"), str)
        for cookie in value
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


@unittest.skipUnless(
    os.environ.get("PL_GATEWAY_STUDENT_FIXTURE"),
    "verified Student fixture not configured",
)
class OrdinaryStudentAcl(unittest.TestCase):
    fixture: ClassVar[StudentFixture]

    @classmethod
    def setUpClass(cls) -> None:
        value: object = json.loads(
            pathlib.Path(os.environ["PL_GATEWAY_STUDENT_FIXTURE"]).read_text()
        )
        if not student_fixture(value):
            raise ValueError("Некорректная verified Student fixture")
        cls.fixture = value

    def native(self, student: Student, path: str) -> tuple[int, str]:
        cookies: object = json.loads(pathlib.Path(student["cookieFile"]).read_text())
        if not cookie_values(cookies):
            raise ValueError("Некорректный файл cookie Student fixture")
        cookie = "; ".join(
            c["name"] + "=" + c["value"]
            for c in cookies
            if c["name"] in ("prairielearn_session", "pl2_session")
        )
        req = urllib.request.Request(
            self.fixture["privateNativeUrl"] + path,
            headers={
                "Cookie": cookie,
                "Host": self.fixture["host"],
                "X-Forwarded-Proto": "https",
            },
        )
        try:
            response: object = urllib.request.build_opener(NoRedirect).open(
                req, timeout=20
            )
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read().decode()
        if not isinstance(response, http.client.HTTPResponse):
            raise TypeError("Ожидался native HTTP response")
        with response:
            return response.status, response.read().decode()

    def test_native_student_list_exposes_only_accessible_work(self) -> None:
        for student in self.fixture["students"]:
            with self.subTest(student=student["userUid"]):
                status, body = self.native(student, self.fixture["listPath"])
                self.assertEqual(status, 200)
                self.assertIn(student["ownWork"], body)
                self.assertNotIn(student["foreignWork"], body)

    def test_native_direct_url_enforces_access_in_existing_student_session(
        self,
    ) -> None:
        for student in self.fixture["students"]:
            with self.subTest(student=student["userUid"]):
                self.assertIn(
                    self.native(student, student["foreignPath"])[0], (403, 404)
                )
                self.assertIn(self.native(student, student["ownPath"])[0], (200, 302))
