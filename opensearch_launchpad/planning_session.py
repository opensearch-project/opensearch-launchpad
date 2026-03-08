"""Turn-based wrapper around the planner agent for MCP use.

Provides a ``PlanningSession`` class that exposes the same planning logic
as the interactive ``solution_planning_assistant`` tool, but without
terminal I/O.  Each call to ``start()``, ``send()``, or ``finalize()``
performs one agent turn and returns the response immediately.
"""

import inspect
import re
from collections.abc import Callable
from typing import Any

from opensearch_launchpad.solution_planning_assistant import (
    _create_planner_agent,
    _extract_canonical_capability_ids,
    _extract_localhost_source_index_name,
    _extract_sample_doc_json,
    _extract_source_local_file,
    _filter_search_capabilities_block,
    _has_three_method_hybrid,
    _inject_localhost_recreate_policy,
    _normalize_capability_id,
    _append_capability_precheck_notes,
    _build_capability_precheck_feedback,
    _looks_like_planner_confirmation,
)
from opensearch_launchpad.opensearch_ops_tools import preview_cap_driven_verification
from opensearch_launchpad.shared import looks_like_new_request, looks_like_execution_intent


class PlanningSession:
    """Turn-based planner session for MCP integration.

    Usage::

        session = PlanningSession()
        result = session.start(context)       # first agent turn
        result = session.send(user_feedback)  # refinement turns
        result = session.finalize()           # force finalization

    Every method returns a dict::

        {
            "response": str,       # agent response text
            "is_complete": bool,   # True when plan is finalized
            "result": dict | None  # structured result when complete
        }
    """

    def __init__(self, agent: Callable[[str], Any] | None = None) -> None:
        self._agent = agent or _create_planner_agent()
        self._agent_factory = _create_planner_agent if agent is None else None
        self._initial_context: str = ""
        self._confirmation_received = False
        self._internal_retry_limit = 8
        self._finalization_retry_count = 0
        self._finalization_retry_limit = 2
        self._hybrid_method_retry_count = 0
        self._hybrid_method_retry_limit = 1
        self._capability_precheck_retry_count = 0
        self._capability_precheck_retry_limit = 1
        self._result: dict | None = None

    def start(self, context: str) -> dict:
        """Send initial context to the planner agent and return its first proposal."""
        self._initial_context = context
        return self._process_turn(self._build_initial_input(context))

    async def astart(self, context: str) -> dict:
        """Async variant of ``start`` for async-backed planner callables."""
        self._initial_context = context
        return await self._process_turn_async(self._build_initial_input(context))

    def send(self, user_input: str) -> dict:
        """Send user feedback and return the planner's next response."""
        if self._result is not None:
            return {"response": "", "is_complete": True, "result": self._result}

        return self._process_turn(self._build_turn_input(user_input))

    async def asend(self, user_input: str) -> dict:
        """Async variant of ``send`` for async-backed planner callables."""
        if self._result is not None:
            return {"response": "", "is_complete": True, "result": self._result}
        return await self._process_turn_async(self._build_turn_input(user_input))

    def finalize(self) -> dict:
        """Force the planner to finalize and return the structured result."""
        if self._result is not None:
            return {"response": "", "is_complete": True, "result": self._result}
        self._confirmation_received = True
        return self._process_turn(self._build_finalize_input())

    async def afinalize(self) -> dict:
        """Async variant of ``finalize`` for async-backed planner callables."""
        if self._result is not None:
            return {"response": "", "is_complete": True, "result": self._result}
        self._confirmation_received = True
        return await self._process_turn_async(self._build_finalize_input())

    def _build_initial_input(self, context: str) -> str:
        return (
            "Here is the user context:\n"
            f"{context}\n\n"
            "System note: confirmation behavior:\n"
            "- Ask exactly one concise confirmation prompt before finalization.\n"
            "- Do not require any fixed reply keyword (for example, do not require 'proceed').\n"
            "- In that same prompt, make clear the user can raise concerns/questions and you will refine first.\n"
            "- Avoid long, generic alignment-template confirmation wording.\n"
            "- Do not ask extra confirmation checklists.\n"
            "- Only finalize with <planning_complete> after clear proceed intent from the user."
        )

    def _build_finalize_input(self) -> str:
        return (
            "The user explicitly confirmed to proceed with setup/implementation.\n"
            "Finalize now using <planning_complete>."
        )

    def _build_turn_input(self, user_input: str) -> str:
        if looks_like_new_request(user_input):
            self._reset_agent_for_new_request()
            self._confirmation_received = False
            return (
                "The user started a new request. Ignore previous planning context "
                "and treat this as a new conversation.\n"
                f"New request: {user_input}\n"
                "Please provide a technical recommendation."
            )
        if looks_like_execution_intent(user_input) or _looks_like_planner_confirmation(user_input):
            self._confirmation_received = True
            return (
                "The user explicitly confirmed to proceed with setup/implementation.\n"
                f"User message: {user_input}\n"
                "Finalize now using <planning_complete>."
            )
        return user_input

    def _reset_agent_for_new_request(self) -> None:
        if self._agent_factory is not None:
            self._agent = self._agent_factory()
            return
        reset_fn = getattr(self._agent, "reset", None)
        if callable(reset_fn):
            reset_fn()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _process_turn(self, agent_input: str) -> dict:
        """Call the agent and process the response, retrying internally when needed."""
        current_input = agent_input
        for _ in range(self._internal_retry_limit):
            response_text = self._invoke_agent_sync(current_input)

            match = re.search(
                r"<planning_complete>(.*?)</planning_complete>",
                response_text,
                re.DOTALL,
            )
            if match:
                retry_input = self._try_extract_result(match)
                if retry_input is not None:
                    current_input = retry_input
                    continue
                return {
                    "response": response_text,
                    "is_complete": True,
                    "result": self._result,
                }

            return {"response": response_text, "is_complete": False, "result": None}

        return {
            "response": (
                "Planner internal retry limit reached while regenerating planning output. "
                "Please continue with refine_plan(), or explicitly confirm and call finalize_plan()."
            ),
            "is_complete": False,
            "result": None,
        }

    async def _process_turn_async(self, agent_input: str) -> dict:
        """Async turn processor that supports both sync and async planner callables."""
        current_input = agent_input
        for _ in range(self._internal_retry_limit):
            response_text = await self._invoke_agent_async(current_input)

            match = re.search(
                r"<planning_complete>(.*?)</planning_complete>",
                response_text,
                re.DOTALL,
            )
            if match:
                retry_input = self._try_extract_result(match)
                if retry_input is not None:
                    current_input = retry_input
                    continue
                return {
                    "response": response_text,
                    "is_complete": True,
                    "result": self._result,
                }

            return {"response": response_text, "is_complete": False, "result": None}

        return {
            "response": (
                "Planner internal retry limit reached while regenerating planning output. "
                "Please continue with refine_plan(), or explicitly confirm and call finalize_plan()."
            ),
            "is_complete": False,
            "result": None,
        }

    def _invoke_agent_sync(self, prompt: str) -> str:
        response = self._agent(prompt)
        if inspect.isawaitable(response):
            raise RuntimeError(
                "Async planner callable detected in sync PlanningSession path. "
                "Use astart()/asend()/afinalize() for this planner backend."
            )
        return str(response)

    async def _invoke_agent_async(self, prompt: str) -> str:
        response = self._agent(prompt)
        if inspect.isawaitable(response):
            response = await response
        return str(response)

    def _try_extract_result(self, match: re.Match) -> str | None:
        """Process a ``<planning_complete>`` match.

        Returns a retry prompt string when the output is invalid and
        should be regenerated, or ``None`` when processing is done
        (``self._result`` is set in that case).
        """
        if not self._confirmation_received:
            return (
                "You finalized too early.\n"
                "Do NOT output <planning_complete> yet.\n"
                "Present the recommendation and ask exactly one concise confirmation prompt.\n"
                "Do not require a fixed reply keyword.\n"
                "Use a prompt that allows either proceed intent or user concerns in one turn.\n"
                "Avoid long, generic alignment-template confirmation wording.\n"
                "Do not ask any additional confirmation checklist questions."
            )

        content = match.group(1)

        solution_match = re.search(r"<solution>(.*?)</solution>", content, re.DOTALL)
        capabilities_match = re.search(
            r"<search_capabilities>(.*?)</search_capabilities>", content, re.DOTALL
        )
        keynote_match = re.search(r"<keynote>(.*?)</keynote>", content, re.DOTALL)

        solution = solution_match.group(1).strip() if solution_match else "No solution parsed."
        search_capabilities = capabilities_match.group(1).strip() if capabilities_match else ""
        keynote = keynote_match.group(1).strip() if keynote_match else "No keynote provided."
        solution = _inject_localhost_recreate_policy(solution, self._initial_context)

        # --- Three-method hybrid guard ---
        if _has_three_method_hybrid(solution):
            if self._hybrid_method_retry_count < self._hybrid_method_retry_limit:
                self._hybrid_method_retry_count += 1
                return (
                    "Your previous <planning_complete> proposed a three-method hybrid retrieval."
                    " Regenerate the full <planning_complete> block now.\n"
                    "Requirement: hybrid retrieval must use at most two methods."
                    " Do NOT combine BM25/lexical + dense + sparse in one retrieval strategy.\n"
                    "If hybrid is needed, choose one pair only (for example dense+sparse or BM25+dense)."
                )
            self._result = {
                "solution": "INVALID_PLANNING_COMPLETE",
                "search_capabilities": "",
                "keynote": (
                    "Planner proposed a three-method hybrid retrieval after retry. "
                    "Hybrid retrieval must be limited to two methods."
                ),
            }
            return None

        # --- Capability precheck ---
        capability_ids = _extract_canonical_capability_ids(search_capabilities)
        if search_capabilities and capability_ids:
            capability_block_for_precheck = f"## Search Capabilities\n{search_capabilities}\n"
            sample_doc_json = _extract_sample_doc_json(self._initial_context)
            source_local_file = _extract_source_local_file(self._initial_context)
            source_index_name = _extract_localhost_source_index_name(self._initial_context)
            try:
                preview_result = preview_cap_driven_verification(
                    worker_output=capability_block_for_precheck,
                    count=10,
                    sample_doc_json=sample_doc_json,
                    source_local_file=source_local_file,
                    source_index_name=source_index_name,
                )
            except Exception as exc:
                preview_result = {
                    "capabilities": capability_ids,
                    "applicable_capabilities": [],
                    "skipped_capabilities": [],
                    "suggestion_meta": [],
                    "selected_doc_count": 0,
                    "notes": [f"capability precheck failed: {exc}"],
                }

            applicable_ids = [
                _normalize_capability_id(item)
                for item in preview_result.get("applicable_capabilities", [])
                if _normalize_capability_id(item)
            ]
            filtered_search_capabilities = _filter_search_capabilities_block(
                search_capabilities, applicable_ids
            )
            if filtered_search_capabilities:
                keynote_with_precheck = _append_capability_precheck_notes(
                    keynote, preview_result.get("skipped_capabilities", [])
                )
                self._result = {
                    "solution": solution,
                    "search_capabilities": filtered_search_capabilities,
                    "keynote": keynote_with_precheck,
                }
                return None

            precheck_feedback = _build_capability_precheck_feedback(
                notes=preview_result.get("notes", []),
                skipped_capabilities=preview_result.get("skipped_capabilities", []),
            )
            if self._capability_precheck_retry_count < self._capability_precheck_retry_limit:
                self._capability_precheck_retry_count += 1
                return (
                    "Your previous <planning_complete> output has no sample-verified applicable capabilities.\n"
                    "Regenerate the full <planning_complete> block now.\n"
                    "Use only capabilities that can be demonstrated by the available sample data/schema context.\n"
                    f"Precheck feedback: {precheck_feedback}\n"
                    "Requirements:\n"
                    "- Include <solution>, <search_capabilities>, and <keynote>.\n"
                    "- Keep <search_capabilities> canonical with prefixes Exact:/Semantic:/Structured:/Combined:/Autocomplete:/Fuzzy:.\n"
                    "- Include only applicable capability bullets.\n"
                )

            self._result = {
                "solution": "INVALID_PLANNING_COMPLETE",
                "search_capabilities": "",
                "keynote": (
                    "Planner capability precheck found no applicable canonical capabilities after retry. "
                    f"Precheck feedback: {precheck_feedback}"
                ),
            }
            return None

        # --- Missing or non-canonical search_capabilities ---
        if self._finalization_retry_count < self._finalization_retry_limit:
            self._finalization_retry_count += 1
            return (
                "Your previous <planning_complete> output is invalid because <search_capabilities> is missing or not canonical.\n"
                "Regenerate the full <planning_complete> block now.\n"
                "Requirements:\n"
                "- Include <solution>, <search_capabilities>, and <keynote>.\n"
                "- If retrieval method is hybrid lexical+semantic, include in <solution> exactly one line in this format: "
                "'Hybrid Weight Profile: semantic-heavy|balanced|lexical-heavy'.\n"
                "- If retrieval method is hybrid, use at most two methods. Do NOT combine BM25/lexical + dense + sparse.\n"
                "- In <search_capabilities>, include only applicable capability bullets.\n"
                "- Every capability bullet MUST start with one canonical prefix: "
                "Exact:, Semantic:, Structured:, Combined:, Autocomplete:, or Fuzzy:.\n"
                "- Do not use any other capability bullet prefixes.\n"
            )

        self._result = {
            "solution": "INVALID_PLANNING_COMPLETE",
            "search_capabilities": "",
            "keynote": (
                "Planner failed to produce canonical <search_capabilities> after retries. "
                "Expected canonical prefixes: Exact/Semantic/Structured/Combined/Autocomplete/Fuzzy."
            ),
        }
        return None
