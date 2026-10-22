"""The tools as a Strands agent sees them: their specs, calls that go through the agent's
tool machinery (input validation, error results), and one full agent loop with a scripted
model in place of a real one."""

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from strands import Agent
from strands.models.model import Model

import strands_comment_scraper
from strands_comment_scraper import (
    comment_export_stats,
    filter_comments,
    get_comment,
    read_comment_export,
)
from tests.unit_tests.helpers import FIXTURES

TOOLS: list[Any] = [read_comment_export, filter_comments, get_comment, comment_export_stats]
CRM = str(FIXTURES / "which-crm.json")


class NoModel(Model):
    """Direct tool calls never reach a model. The default Bedrock model would look up AWS
    settings over the network as soon as it's created, so tests use this one instead."""

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> Any:
        return {}

    def structured_output(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the model was called")

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the model was called")


def agent(tools: list[Any]) -> Agent:
    return Agent(model=NoModel(), tools=tools, callback_handler=None)


def result_text(result: Any) -> str:
    assert len(result["content"]) == 1
    text: str = result["content"][0]["text"]
    return text


def test_tool_specs_describe_every_parameter() -> None:
    expected_required = {
        "read_comment_export": ["path"],
        "filter_comments": ["path"],
        "get_comment": ["path", "comment"],
        "comment_export_stats": ["path"],
    }
    for tool in TOOLS:
        spec = tool.tool_spec
        assert spec["name"] == tool.tool_name
        assert "Comment Scraper" in spec["description"]
        schema = spec["inputSchema"]["json"]
        assert sorted(schema["required"]) == sorted(expected_required[tool.tool_name])
        for name, field in schema["properties"].items():
            assert field["description"] != f"Parameter {name}", f"{tool.tool_name}.{name}"
    sort = filter_comments.tool_spec["inputSchema"]["json"]["properties"]["sort"]
    assert sort["enum"] == ["thread", "score"]


def test_an_agent_registers_the_tools_from_a_list_or_the_module() -> None:
    assert agent(TOOLS).tool_names == [tool.tool_name for tool in TOOLS]
    from_module = agent([strands_comment_scraper]).tool_names
    assert sorted(from_module) == sorted(tool.tool_name for tool in TOOLS)


def test_calls_through_the_agent_return_the_same_text() -> None:
    # The tool caller only holds a weak reference to its agent, so keep the agent in a variable.
    the_agent = agent(TOOLS)
    tools = the_agent.tool
    result = tools.filter_comments(path=CRM, contains="renewal", sort="score")
    assert result["status"] == "success"
    assert result_text(result) == filter_comments(CRM, contains="renewal", sort="score")
    result = tools.comment_export_stats(path=CRM)
    assert result_text(result) == comment_export_stats(CRM)


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda tools: tools.get_comment(path=CRM, comment="c99"), "Numbers run c1 to c8"),
        (lambda tools: tools.read_comment_export(path=CRM, limit=0), "limit must be"),
        (lambda tools: tools.read_comment_export(path="missing.json"), "Can't read"),
        (lambda tools: tools.filter_comments(path=CRM, sort="newest"), "sort"),
    ],
)
def test_mistakes_come_back_to_the_model_as_error_results(call: Any, message: str) -> None:
    the_agent = agent(TOOLS)
    result = call(the_agent.tool)
    assert result["status"] == "error"
    assert message in result_text(result)


class ScriptedModel(NoModel):
    """Asks for one tool call, then answers with fixed text. Keeps what it was sent."""

    def __init__(self, tool_name: str, tool_input: dict[str, Any]) -> None:
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.received: list[Any] = []

    async def stream(self, messages: Any, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        self.received.append(json.loads(json.dumps(messages, default=str)))
        yield {"messageStart": {"role": "assistant"}}
        if len(self.received) == 1:
            yield {
                "contentBlockStart": {
                    "start": {"toolUse": {"toolUseId": "call-1", "name": self.tool_name}}
                }
            }
            yield {
                "contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(self.tool_input)}}}
            }
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": "Renewal pricing, see [c1]."}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}


def test_an_agent_loop_calls_the_tool_and_sends_the_result_back_to_the_model() -> None:
    model = ScriptedModel("filter_comments", {"path": CRM, "contains": "renewal"})
    the_agent = Agent(model=model, tools=TOOLS, callback_handler=None)
    answer = the_agent("What do people complain about in which-crm.json?")
    assert str(answer).strip() == "Renewal pricing, see [c1]."

    # The second request to the model carries the tool's output as the tool result.
    tool_results = [
        block["toolResult"]
        for message in model.received[1]
        for block in message["content"]
        if "toolResult" in block
    ]
    assert len(tool_results) == 1
    assert tool_results[0]["status"] == "success"
    assert tool_results[0]["content"][0]["text"] == filter_comments(CRM, contains="renewal")
