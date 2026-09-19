from __future__ import annotations

import json
import os
from typing import Any

import boto3

from backend.workflow.models import Node


class SageMakerAgentRunner:
    """Agent runner backed by a deployed SageMaker AI inference endpoint.

    The endpoint can be a standard JSON inference endpoint or an endpoint
    exposing an OpenAI-compatible chat payload through its serving container.
    Configure SPECL00M_SAGEMAKER_ENDPOINT_NAME in the runtime environment.
    """

    def __init__(self, endpoint_name: str | None = None) -> None:
        self.endpoint_name = endpoint_name or os.getenv("SPECL00M_SAGEMAKER_ENDPOINT_NAME")
        if not self.endpoint_name:
            raise RuntimeError("SPECL00M_SAGEMAKER_ENDPOINT_NAME is required for SageMaker runtime mode")
        self.client = boto3.client("sagemaker-runtime")

    def __call__(self, node: Node, payload: Any) -> Any:
        role = str(node.config.get("role", node.name))
        instructions = str(node.config.get("instructions", ""))
        prompt = (
            "You are an execution agent inside Specloom.\n"
            f"Role: {role}\n"
            f"Instructions: {instructions}\n"
            "Return JSON when possible.\n"
            f"Input: {json.dumps(payload, default=str)}"
        )
        request = {
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        response = self.client.invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType="application/json",
            Body=json.dumps(request).encode("utf-8"),
        )
        raw = response["Body"].read().decode("utf-8")
        return {
            "agent": node.id,
            "role": role,
            "response": self._parse_response(raw),
            "status": "completed",
        }

    @staticmethod
    def _parse_response(raw: str) -> Any:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
