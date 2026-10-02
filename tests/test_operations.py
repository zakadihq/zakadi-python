"""The operation methods against ``openapi/openapi.yaml``, the document they follow.

Each operation's method, path, parameters, request body, success answer and problem
answers come from the document (``spec/02-api.md`` 2.12, D84); ``METHODS`` only names
the client method that calls it. Path parameters go positionally, query and body
members by keyword under the API's names (``from_`` for ``from``), the policy as one
argument.
"""

import json
import unittest
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import parse_qsl, quote

import yaml
from fake_api import API_KEY, FakeApi, Reply, empty, ok, problem

from zakadi import ApiError, ResultPending, Zakadi

DOCUMENT = Path(__file__).resolve().parents[1] / "openapi" / "openapi.yaml"
ID = "id/../with ?#"  # one path segment only once encoded
ENCODED = quote(ID, safe="")

METHODS: dict[str, Callable[[Zakadi], Callable[..., Any]]] = {
    "getSession": lambda c: c.sessions.get,
    "listSessions": lambda c: c.sessions.list,
    "cancelSession": lambda c: c.sessions.cancel,
    "getEvidence": lambda c: c.sessions.evidence,
    "purgeSession": lambda c: c.sessions.purge,
    "purgeSubject": lambda c: c.subjects.purge,
    "getJob": lambda c: c.jobs.get,
    "createWebhook": lambda c: c.webhooks.create,
    "listWebhooks": lambda c: c.webhooks.list,
    "getWebhook": lambda c: c.webhooks.get,
    "updateWebhook": lambda c: c.webhooks.update,
    "deleteWebhook": lambda c: c.webhooks.delete,
    "listWebhookDeliveries": lambda c: c.webhooks.deliveries,
    "getPolicy": lambda c: c.tenants.policy,
    "updatePolicy": lambda c: c.tenants.update_policy,
    "getUsage": lambda c: c.tenants.usage,
}
NOT_RETRIED = {"cancelSession", "purgeSubject"}
# sessions.create, sessions.result and results.verify_token call the first three; the
# client has no method for the SDK-facing and health operations.
ELSEWHERE = {"createSession", "getResult", "getJwks"}
WITHOUT_METHOD = {"getSdkConfig", "sendTelemetry", "getHealth", "getIngestHealth"}


@dataclass
class Operation:
    id: str
    method: str
    path: str  # the template, {id} unfilled
    parameters: list[dict[str, Any]]
    body: Any  # the request body's example, None without a body
    responses: dict[str, dict[str, Any]]

    def target(self) -> str:
        return self.path.replace("{id}", ENCODED)

    def query(self) -> dict[str, str]:
        return {
            p["name"]: str(p["example"]) for p in self.parameters if p["in"] == "query"
        }

    def success(self) -> tuple[int, Any]:
        """The 2xx status and its body's example, None for an answer without one."""
        (code,) = [c for c in self.responses if c.startswith("2")]
        content = self.responses[code].get("content")
        return int(code), content["application/json"]["example"] if content else None

    def problems(self) -> list[dict[str, Any]]:
        """The example problems of every 4xx answer but 429, which is retried."""
        found = []
        for code, response in self.responses.items():
            if code.startswith("4") and code != "429":
                content = response["content"]["application/problem+json"]
                if "example" in content:
                    found.append(content["example"])
                found.extend(e["value"] for e in content.get("examples", {}).values())
        return found


def _load() -> dict[str, Operation]:
    document = yaml.safe_load(DOCUMENT.read_text(encoding="utf-8"))

    def resolve(node: Any) -> Any:
        while isinstance(node, dict) and "$ref" in node:
            target = document
            for part in node["$ref"].removeprefix("#/").split("/"):
                target = target[part]
            node = target
        return node

    operations = {}
    for path, item in document["paths"].items():
        for method in ("get", "put", "post", "delete", "patch"):
            if method not in item:
                continue
            op = item[method]
            parameters = item.get("parameters", []) + op.get("parameters", [])
            body = resolve(op.get("requestBody"))
            operations[op["operationId"]] = Operation(
                op["operationId"],
                method.upper(),
                path,
                [resolve(p) for p in parameters],
                body["content"]["application/json"]["example"] if body else None,
                {code: resolve(r) for code, r in op["responses"].items()},
            )
    return operations


OPERATIONS = _load()


def call(client: Zakadi, op: Operation) -> Any:
    """Call the operation's method with the document's examples as arguments."""
    args: list[Any] = [ID for p in op.parameters if p["in"] == "path"]
    kwargs = {
        "from_" if p["name"] == "from" else p["name"]: p["example"]
        for p in op.parameters
        if p["in"] == "query"
    }
    if op.id == "updatePolicy":
        args.append(op.body)
    elif op.body is not None:
        kwargs.update(op.body)
    return METHODS[op.id](client)(*args, **kwargs)


def answer(op: Operation) -> Reply:
    status, body = op.success()
    return empty(status) if body is None else ok(body, status)


class OperationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeApi()
        self.addCleanup(self.api.close)
        self.client = Zakadi(api_key=API_KEY, base_url=self.api.base_url)
        sleep = mock.patch("time.sleep")  # retries record their delays instead
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def reset(self) -> None:
        self.api.received.clear()
        self.sleep.reset_mock()

    def slept(self) -> list[float]:
        return [c.args[0] for c in self.sleep.call_args_list]


class DocumentTests(unittest.TestCase):
    def test_every_operation_has_a_method_or_none_by_design(self) -> None:
        self.assertEqual(set(OPERATIONS), set(METHODS) | ELSEWHERE | WITHOUT_METHOD)
        self.assertEqual(set(METHODS) & (ELSEWHERE | WITHOUT_METHOD), set())

    def test_the_bodiless_answers_are_a_202_and_a_204(self) -> None:
        bodiless = {
            i: OPERATIONS[i].success()[0]
            for i in METHODS
            if OPERATIONS[i].success()[1] is None
        }
        self.assertEqual(bodiless, {"purgeSession": 202, "deleteWebhook": 204})


class RequestTests(OperationTestCase):
    def test_each_method_sends_its_operation_and_returns_the_body(self) -> None:
        for op in (OPERATIONS[i] for i in METHODS):
            with self.subTest(op.id):
                self.reset()
                self.api.reply(op.method, op.target(), answer(op))
                returned = call(self.client, op)
                (sent,) = self.api.received
                self.assertEqual((sent.method, sent.path), (op.method, op.target()))
                self.assertEqual(dict(parse_qsl(sent.query)), op.query())
                self.assertEqual(sent.headers["authorization"], f"Bearer {API_KEY}")
                if op.body is None:
                    self.assertEqual(sent.body, b"")
                else:
                    self.assertEqual(sent.headers["content-type"], "application/json")
                    self.assertEqual(json.loads(sent.body), op.body)
                self.assertEqual(
                    "idempotency-key" in sent.headers, op.id == "createWebhook"
                )
                self.assertEqual(returned, op.success()[1])

    def test_none_arguments_are_left_out_of_the_query(self) -> None:
        self.api.reply("GET", "/v1/sessions", ok({"data": [], "next_cursor": None}))
        self.client.sessions.list(status="passed", limit=None)
        (sent,) = self.api.received
        self.assertEqual(sent.query, "status=passed")

    def test_a_body_answer_without_a_body_raises_api_error(self) -> None:
        self.api.reply("GET", "/v1/jobs/job_1", empty(200))
        with self.assertRaises(ApiError) as caught:
            self.client.jobs.get("job_1")
        self.assertEqual((caught.exception.status, caught.exception.code), (200, None))


class RetryTests(OperationTestCase):
    def test_only_the_methods_marked_retried_retry_429_and_5xx(self) -> None:
        for op in (OPERATIONS[i] for i in METHODS):
            with self.subTest(op.id):
                self.reset()
                self.api.reply(
                    op.method,
                    op.target(),
                    problem(429, "rate_limited", **{"Retry-After": "3"}),
                    problem(503, "internal_error"),
                    answer(op),
                )
                if op.id in NOT_RETRIED:
                    with self.assertRaises(ApiError) as caught:
                        call(self.client, op)
                    self.assertEqual(caught.exception.code, "rate_limited")
                    self.assertEqual(len(self.api.received), 1)
                    self.assertEqual(self.slept(), [])
                    continue
                self.assertEqual(call(self.client, op), op.success()[1])
                self.assertEqual(len(self.api.received), 3)
                waited, backoff = self.slept()
                self.assertEqual(waited, 3.0)  # Retry-After
                self.assertTrue(0.5 <= backoff <= 1.0, backoff)

    def test_retries_stop_at_the_cap(self) -> None:
        for op in (OPERATIONS[i] for i in METHODS):
            with self.subTest(op.id):
                self.reset()
                self.api.reply(op.method, op.target(), problem(502, "internal_error"))
                with self.assertRaises(ApiError) as caught:
                    call(self.client, op)
                self.assertEqual(caught.exception.status, 502)
                attempts = 1 if op.id in NOT_RETRIED else 3
                self.assertEqual(len(self.api.received), attempts)

    def test_create_webhook_keeps_the_given_idempotency_key(self) -> None:
        op = OPERATIONS["createWebhook"]
        self.api.reply(
            "POST",
            "/v1/webhooks",
            problem(503, "internal_error"),
            problem(429, "rate_limited"),
            answer(op),
        )
        self.client.webhooks.create(**op.body, idempotency_key="wh-88213-1")
        sent = self.api.received
        self.assertEqual(len(sent), 3)
        self.assertEqual({s.headers["idempotency-key"] for s in sent}, {"wh-88213-1"})
        self.assertEqual(len({s.body for s in sent}), 1)

    def test_create_webhook_keeps_a_generated_idempotency_key(self) -> None:
        op = OPERATIONS["createWebhook"]
        self.api.reply(
            "POST", "/v1/webhooks", problem(502, "internal_error"), answer(op)
        )
        self.client.webhooks.create(**op.body)
        first, second = self.api.received
        key = first.headers["idempotency-key"]
        self.assertEqual(second.headers["idempotency-key"], key)
        self.assertEqual(str(uuid.UUID(key)), key)
        self.reset()
        self.client.webhooks.create(**op.body)
        (third,) = self.api.received
        self.assertNotEqual(third.headers["idempotency-key"], key)


class ProblemTests(OperationTestCase):
    def test_every_documented_problem_raises_api_error(self) -> None:
        for op in (OPERATIONS[i] for i in METHODS):
            for body in op.problems():
                with self.subTest(op.id, code=body["code"]):
                    self.reset()
                    reply = Reply(
                        body["status"],
                        body,
                        {"Content-Type": "application/problem+json"},
                    )
                    self.api.reply(op.method, op.target(), reply)
                    with self.assertRaises(ApiError) as caught:
                        call(self.client, op)
                    error = caught.exception
                    self.assertEqual(
                        (error.status, error.code, error.request_id),
                        (body["status"], body["code"], body["request_id"]),
                    )
                    self.assertEqual(len(self.api.received), 1)

    def test_webhook_not_found(self) -> None:
        path = f"/v1/webhooks/{ENCODED}"
        for method, run in (
            ("GET", lambda: self.client.webhooks.get(ID)),
            ("DELETE", lambda: self.client.webhooks.delete(ID)),
        ):
            with self.subTest(method):
                self.api.reply(method, path, problem(404, "webhook_not_found", "req_4"))
                with self.assertRaises(ApiError) as caught:
                    run()
                self.assertIs(type(caught.exception), ApiError)
                self.assertEqual(caught.exception.status, 404)
                self.assertEqual(caught.exception.code, "webhook_not_found")
                self.assertEqual(caught.exception.request_id, "req_4")

    def test_evidence_and_purge_raise_result_pending_before_the_verdict(self) -> None:
        path = f"/v1/sessions/{ENCODED}"
        self.api.reply("GET", f"{path}/evidence", problem(404, "result_pending"))
        self.api.reply("DELETE", path, problem(404, "result_pending"))
        for run in (
            lambda: self.client.sessions.evidence(ID),
            lambda: self.client.sessions.purge(ID),
        ):
            with self.assertRaises(ResultPending):
                run()


if __name__ == "__main__":
    unittest.main()
