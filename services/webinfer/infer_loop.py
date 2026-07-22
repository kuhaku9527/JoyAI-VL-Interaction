"""Main inference-loop mixin: chat endpoints, frame parsing, and main-model call.

Defines :class:`InferLoopMixin`, which carries the primary推理 loop:
``handle_text_chat`` / ``handle_chat_completions`` / ``_handle_chat_payload``
(including its five cohesive ``_chat_payload_*`` sub-steps), ``_handle_text_payload``,
frame reference parsing, and the main-model call previously on ``StreamingInferAdapter``.
"""

from __future__ import annotations

import copy
import logging
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from adapter_types import SessionState
from aiohttp import web
from config import reset_chunk_state
from openai import AsyncOpenAI
from prompt_building import (
    _compute_prompt_guard_max_chars,
    _estimate_messages_chars,
    _trim_messages_to_ctx,
)
from request_parsing import (
    _extract_all_image_refs,
    _extract_time_range_from_request,
    _extract_time_ranges_from_request,
    _extract_user_prompt_text,
    _read_json,
    _request_session_id,
)
from response_format import (
    _chat_completion_response,
    _openai_error_response,
    _parse_decision_tokens,
    _short,
    archive_chunk_response_records,
    build_model_input_record,
    extract_response_payload,
    normalize_model_output,
    parse_model_decision,
)
from time_ranges import (
    _extract_time_range_from_text,
    _format_turn_time_range,
    _parse_start_second,
    _strip_time_range_from_text,
)

LOGGER = logging.getLogger("streaming_infer_adapter")


class InferLoopMixin:
    """Main inference loop: chat endpoints, frame parsing, model call."""

    def _resolve_backend(self, model_name: str | None = None) -> tuple[AsyncOpenAI, str]:
        if model_name and model_name in self.main_clients:
            return self.main_clients[model_name]
        return self.main_client, self.config.main_model

    async def handle_text_chat(self, request: web.Request) -> web.Response:
        # v3.37 single-LLM-gateway: text-only chat-completion endpoint that
        # runs the same system-prompt + memory + token-guard + decision-token
        # parsing pipeline as the multimodal path, but rejects any image_url
        # content so voice-dialog callers cannot smuggle frames through.
        try:
            payload = await _read_json(request)
        except Exception as exc:
            return _openai_error_response(f"invalid JSON body: {exc}", status=400)

        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            return _openai_error_response("messages must be a non-empty list", status=400)
        valid_roles = {"system", "user", "assistant"}
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                return _openai_error_response(f"messages[{index}] must be a dict", status=400)
            role = message.get("role")
            if role not in valid_roles:
                return _openai_error_response(
                    f"messages[{index}].role must be one of {sorted(valid_roles)}, got {role!r}",
                    status=400,
                )
            content = message.get("content")
            if isinstance(content, list):
                for _, part in enumerate(content):
                    if isinstance(part, dict) and part.get("type") in {
                        "image_url",
                        "image",
                    }:
                        return _openai_error_response(
                            "image content not allowed on /v1/text/chat; use /v1/chat/completions for multimodal",
                            status=400,
                        )
            elif isinstance(content, str):
                if "data:image/" in content and ";base64," in content:
                    return _openai_error_response(
                        "inline base64 image not allowed on /v1/text/chat",
                        status=400,
                    )
            elif content is None:
                return _openai_error_response(
                    f"messages[{index}].content must not be null", status=400
                )
            else:
                return _openai_error_response(
                    f"messages[{index}].content must be str or list, got {type(content).__name__}",
                    status=400,
                )

        session_id = _request_session_id(request, payload)
        requested_model = payload.get("model")
        client, model_name = self._resolve_backend(requested_model)
        state = self.get_session(session_id)
        async with state.lock:
            try:
                result = await self._handle_text_payload(
                    state, payload, client=client, model_name=model_name
                )
            except web.HTTPException:
                raise
            except Exception as exc:
                LOGGER.exception("text chat completion failed")
                return _openai_error_response(str(exc), status=502)
        return web.json_response(result)

    async def _handle_text_payload(
        self,
        state: SessionState,
        payload: dict[str, Any],
        *,
        client: AsyncOpenAI | None = None,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        # Single-LLM-gateway text path. Composes the system prompt
        # (character profile + [Local Wiki]), runs the v3.34 prompt
        # token guard, forwards to the main model, parses decision
        # tokens, and records the turn in qa_history so the next call
        # sees the same conversation context as the video path.
        client = client or self.main_client
        model_name = model_name or self.config.main_model

        # Slice 2: warm up memory blocks (fire-and-forget, fail-soft) so the
        # system prompt picks up recent persisted knowledge.
        if self.memory_store is not None and getattr(self.memory_store, "is_enabled", False):
            try:
                blocks = await self.memory_store.warmup(state.session_id)
                if blocks:
                    state._memory_block_cache = list(blocks)
                    state._memory_warmed.set()
            except Exception:
                LOGGER.debug("memory-store warmup failed for %s", state.session_id)

        api_messages = list(payload.get("messages") or [])
        composed_system = (self._build_memory_prompt(state) or "").strip()

        # Resolve any caller-supplied system message into a flat list.
        caller_messages = [dict(m) for m in api_messages if m.get("role") != "system"]
        if composed_system:
            http_messages = [{"role": "system", "content": composed_system}] + caller_messages
        else:
            http_messages = caller_messages

        # v3.34 prompt guard runs LAST so it sees the full assembled
        # messages list (system + turns).
        max_total_chars = _compute_prompt_guard_max_chars(self.config.main_ctx_tokens)
        if max_total_chars > 0:
            http_messages, removed = _trim_messages_to_ctx(
                [dict(m) for m in http_messages], max_total_chars
            )
        else:
            removed = 0

        generation_kwargs = self._main_generation_kwargs(payload)
        response = await client.chat.completions.create(
            model=model_name,
            messages=http_messages,
            **generation_kwargs,
        )
        raw_text = response.choices[0].message.content if response.choices else ""
        usage = response.usage.model_dump() if getattr(response, "usage", None) else None

        decision, clean_text, delegation_question = _parse_decision_tokens(raw_text or "")

        # Update qa_history so the NEXT call sees this turn as context,
        # matching what the multimodal path does for video sessions.
        self._update_text_qa_history(state, api_messages, clean_text, decision)

        memory_chars = len(composed_system)
        qa_history_len = len(state.memory_state.get("qa_history", []))
        prompt_chars = _estimate_messages_chars(http_messages)

        return _chat_completion_response(
            model=self.config.adapter_model,
            content=clean_text,
            usage=usage,
            raw_model=model_name,
            raw_text=raw_text or "",
            decision=decision,
            delegation_question=delegation_question,
            memory_chars=memory_chars,
            qa_history_len=qa_history_len,
            prompt_chars=prompt_chars,
            trimmed_turns=removed,
        )

    async def handle_chat_completions(self, request: web.Request) -> web.Response:
        payload = await _read_json(request)
        session_id = _request_session_id(request, payload)
        requested_model = payload.get("model")
        client, model_name = self._resolve_backend(requested_model)
        state = self.get_session(session_id)
        async with state.lock:
            try:
                result = await self._handle_chat_payload(
                    state, payload, request, client=client, model_name=model_name
                )
            except web.HTTPException:
                raise
            except Exception as exc:
                LOGGER.exception("chat completion failed")
                return _openai_error_response(str(exc), status=502)
        return web.json_response(result)

    async def _handle_chat_payload(
        self,
        state: SessionState,
        payload: dict[str, Any],
        request: web.Request,
        *,
        client: AsyncOpenAI | None = None,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        client = client or self.main_client
        model_name = model_name or self.config.main_model
        t_start = time.perf_counter()
        messages = payload.get("messages") or []
        if not isinstance(messages, list):
            raise web.HTTPBadRequest(text="messages must be a list")

        ctx = SimpleNamespace()
        ctx.t_start = t_start
        await self._chat_payload_resolve_frames(
            state, request, payload, messages, client, model_name, ctx
        )
        if ctx.forward_result is not None:
            return ctx.forward_result

        await self._chat_payload_advance_chunk(state, ctx)
        self._chat_payload_append_turn(state, ctx)
        await self._chat_payload_build_and_infer(state, payload, client, model_name, messages, ctx)
        return self._chat_payload_finalize(state, model_name, ctx)

    async def _chat_payload_resolve_frames(
        self,
        state: SessionState,
        request: web.Request,
        payload: dict[str, Any],
        messages: list[dict[str, Any]],
        client: AsyncOpenAI,
        model_name: str,
        ctx: SimpleNamespace,
    ) -> None:
        """Resolve image references -> frame paths and parse/format time ranges."""
        image_refs = _extract_all_image_refs(messages, request, payload)
        if not image_refs:
            ctx.forward_result = await self._forward_text_only(
                payload, client=client, model_name=model_name
            )
            return

        turn_count = len(state.predictions) + 1
        raw_prompt_text = _extract_user_prompt_text(messages)
        prompt_text = _strip_time_range_from_text(raw_prompt_text)

        # Resolve time ranges for all images
        incoming_time_ranges = _extract_time_ranges_from_request(request, payload)
        if not incoming_time_ranges:
            single = _extract_time_range_from_request(request, payload)
            if single is None:
                single = _extract_time_range_from_text(raw_prompt_text)
            if single:
                incoming_time_ranges = [single]
        time_ranges: list[str] = []
        for i in range(len(image_refs)):
            if i < len(incoming_time_ranges) and incoming_time_ranges[i]:
                time_ranges.append(incoming_time_ranges[i])
            else:
                time_ranges.append(self._time_range_for_frame(state.frame_count + i))
        time_range = _format_turn_time_range(time_ranges)

        image_paths = [self._resolve_frame_ref(ref, state) for ref in image_refs]
        LOGGER.info(
            "[%s] turn=%d frames=%d(+%d) chunk=%d time=%s prompt=%r",
            state.session_id,
            turn_count,
            state.frame_count,
            len(image_refs),
            state.chunk_index,
            time_range,
            _short(prompt_text, 80),
        )

        query_text = self._update_query_state(state, prompt_text, time_ranges[0])

        ctx.turn_count = turn_count
        ctx.time_ranges = time_ranges
        ctx.time_range = time_range
        ctx.image_paths = image_paths
        ctx.query_text = query_text
        ctx.forward_result = None

    async def _chat_payload_advance_chunk(self, state: SessionState, ctx: SimpleNamespace) -> None:
        """Commit due async summaries, then handle chunk boundary / qa archive / flush / carry-over."""
        await self._commit_required_async_summaries(
            state,
            state.turn_count,
            non_blocking=True,
        )

        if self.config.chunk > 0 and state.current_chunk["turn_count"] >= self.config.chunk:
            self._execute_pending_qa_archive(state)
            carry_response_records = []
            if self.config.keep_qa_history and state.current_query_text:
                qa_cutoff = float("inf")
                if (
                    self._async_summary_enabled()
                    and state.async_summary_segment["frame_time_ranges"]
                ):
                    qa_cutoff = _parse_start_second(
                        state.async_summary_segment["frame_time_ranges"][0]
                    )
                    carry_response_records = [
                        (tr, payload)
                        for tr, payload in state.current_chunk["response_records"]
                        if _parse_start_second(tr) >= qa_cutoff
                    ]
                archive_chunk_response_records(
                    state.current_chunk,
                    state.memory_state,
                    state.current_query_text,
                    state.query_start_time,
                    chunk_index=state.chunk_index,
                    before_time_sec=qa_cutoff,
                )
            await self._flush_chunk(state, use_async_summary=self._async_summary_enabled())
            if self._async_summary_enabled() and state.async_summary_segment["turn_count"] > 0:
                carry = copy.deepcopy(state.async_summary_segment)
                carry_frames = carry["frame_count"]
                carry_turns = carry["turn_count"]
                carry["frame_count"] = 0
                carry["turn_count"] = 0
                carry["response_records"] = carry_response_records
                carry["api_msg_cache"] = []
                state.current_chunk = carry
                LOGGER.info(
                    "[%s] carried over %d unsummarized turn(s), %d frame(s) to new chunk",
                    state.session_id,
                    carry_turns,
                    carry_frames,
                )
            else:
                state.current_chunk = reset_chunk_state()
            state.chunk_index += 1
            state.query_in_current_chunk = bool(ctx.query_text)

    def _chat_payload_append_turn(self, state: SessionState, ctx: SimpleNamespace) -> None:
        """Append frames to the chunk, bump counters, and append user/async-summary messages."""
        for tr, ip in zip(ctx.time_ranges, ctx.image_paths):
            state.frame_count += 1
            state.current_chunk["image_paths"].append(str(ip))
            state.current_chunk["frame_time_ranges"].append(tr)
            state.current_chunk["summarizer_frame_cache"].append({"path": str(ip)})
            state.current_chunk["frame_count"] += 1

        state.turn_count += 1
        state.current_chunk["turn_count"] += 1

        user_message = self._build_internal_user_message(
            time_ranges=ctx.time_ranges,
            image_paths=[str(ip) for ip in ctx.image_paths],
            query_text=ctx.query_text,
        )
        state.current_chunk["messages"].append(user_message)
        if self._async_summary_enabled():
            self._append_async_summary_user_message(
                state,
                time_ranges=ctx.time_ranges,
                image_paths=[str(ip) for ip in ctx.image_paths],
                query_text=ctx.query_text,
            )
        ctx.user_message = user_message

    async def _chat_payload_build_and_infer(
        self,
        state: SessionState,
        payload: dict[str, Any],
        client: AsyncOpenAI,
        model_name: str,
        messages: list[dict[str, Any]],
        ctx: SimpleNamespace,
    ) -> None:
        """Assemble the model input and run the main-model call (incl. forced-silence branch)."""
        turn_input_record = {
            "source_message": messages[-1] if messages else None,
            "vllm_message": ctx.user_message,
            "chunk_index": state.chunk_index,
            "has_image": True,
            "image_path": str(ctx.image_paths[-1]),
            "image_paths_batch": [str(ip) for ip in ctx.image_paths],
            "num_chunk_turns": state.current_chunk["turn_count"],
            "num_chunk_frames": state.current_chunk["frame_count"],
            "image_paths": list(state.current_chunk["image_paths"]),
            "frame_time_ranges": list(state.current_chunk["frame_time_ranges"]),
        }

        is_forced_silence = self.config.force_silence_before_query and not state.current_query_text
        inference_start = None
        inference_time = 0.0
        chunk_start_model_input_path = None
        turn_model_input_record = None
        model_input_record = None
        t_prompt_build_start = 0.0
        t_prompt_build_end = 0.0
        t_inference_end = 0.0

        if is_forced_silence:
            generated_text = "</silence>"
            raw_text = ""
            usage = None
            turn_model_input_record = build_model_input_record(
                chunk_index=state.chunk_index,
                messages=state.current_chunk["messages"],
                frame_count=state.current_chunk["frame_count"],
                inference_skipped=True,
                skip_reason="force_silence_before_query",
                image_paths=state.current_chunk["image_paths"],
                frame_time_ranges=state.current_chunk["frame_time_ranges"],
            )
            if self.config.save_model_inputs:
                model_input_record = turn_model_input_record
        else:
            t_prompt_build_start = time.perf_counter()
            internal_messages, prefix_content = self._build_main_internal_messages(state)
            api_messages = self._build_cached_api_messages(state, internal_messages)
            generation_kwargs = self._main_generation_kwargs(payload)
            http_messages = self._build_main_http_messages(api_messages, session_state=state)
            # DEBUG v0.2: print first message roles + system content length
            try:
                roles = [m.get("role") for m in http_messages]
                sys_lens = [
                    len(m.get("content") or "") for m in http_messages if m.get("role") == "system"
                ]
                LOGGER.info(
                    "DEBUG v0.2 http_messages roles=%s sys_content_lengths=%s",
                    roles,
                    sys_lens,
                )
                if state._memory_block_cache:
                    LOGGER.info(
                        "DEBUG v0.2 cache blocks=%d first_id=%s",
                        len(state._memory_block_cache),
                        state._memory_block_cache[0].get("block_id"),
                    )
                else:
                    LOGGER.info(
                        "DEBUG v0.2 cache empty (warmed=%s)",
                        state._memory_warmed.is_set(),
                    )
            except Exception as e:
                LOGGER.warning("DEBUG v0.2 failed: %s", e)
            turn_model_input_record = build_model_input_record(
                chunk_index=state.chunk_index,
                messages=http_messages,
                frame_count=state.current_chunk["frame_count"],
                model=model_name,
                generation_kwargs=generation_kwargs,
                image_paths=state.current_chunk["image_paths"],
                frame_time_ranges=state.current_chunk["frame_time_ranges"],
                prefix_content=prefix_content,
            )
            if self.config.save_model_inputs:
                model_input_record = turn_model_input_record
            chunk_start_model_input_path = self._maybe_save_chunk_start_model_input(
                state,
                ctx.turn_count,
                ctx.time_range,
                turn_model_input_record,
            )
            t_prompt_build_end = time.perf_counter()
            inference_start = time.time()
            raw_text, usage = await self._call_main_model(
                payload,
                api_messages,
                client=client,
                model_name=model_name,
                session_state=state,
                generation_kwargs=generation_kwargs,
                http_messages=http_messages,
            )
            inference_time = time.time() - inference_start
            t_inference_end = time.perf_counter()
            generated_text = (
                normalize_model_output(raw_text)
                if self.config.normalize_output
                else (raw_text or "").strip()
            )

        ctx.turn_input_record = turn_input_record
        ctx.is_forced_silence = is_forced_silence
        ctx.inference_time = inference_time
        ctx.chunk_start_model_input_path = chunk_start_model_input_path
        ctx.turn_model_input_record = turn_model_input_record
        ctx.model_input_record = model_input_record
        ctx.generated_text = generated_text
        ctx.raw_text = raw_text
        ctx.usage = usage
        ctx.t_prompt_build_start = t_prompt_build_start
        ctx.t_prompt_build_end = t_prompt_build_end
        ctx.t_inference_end = t_inference_end

    def _chat_payload_finalize(
        self, state: SessionState, model_name: str, ctx: SimpleNamespace
    ) -> dict[str, Any]:
        """Parse response, assemble prediction/timing, and package the final result."""
        self._execute_pending_qa_archive(state)

        response_payload = extract_response_payload(ctx.generated_text)
        if response_payload and state.current_query_text:
            state.current_chunk["response_records"].append((ctx.time_range, response_payload))

        state.current_chunk["messages"].append({"role": "assistant", "content": ctx.generated_text})
        if self._async_summary_enabled():
            state.async_summary_segment["messages"].append(
                {"role": "assistant", "content": ctx.generated_text}
            )
            self._submit_async_summary_if_needed(state)

        turn_output_record = {}
        if ctx.is_forced_silence:
            turn_output_record["inference_skipped"] = True
            turn_output_record["skip_reason"] = "force_silence_before_query"

        t_end = time.perf_counter()
        total_time = t_end - ctx.t_start

        prediction = {
            "turn": ctx.turn_count,
            "time_range": ctx.time_range,
            "query": ctx.query_text,
            "input": ctx.turn_input_record,
            "output": turn_output_record,
            "prediction": ctx.generated_text,
            "total_time": round(total_time, 3),
            "inference_time": round(ctx.inference_time, 3),
        }
        if ctx.model_input_record is not None:
            ctx.turn_input_record["model_input"] = ctx.model_input_record
        if ctx.chunk_start_model_input_path:
            prediction["chunk_start_model_input_path"] = ctx.chunk_start_model_input_path
        if ctx.raw_text and ctx.raw_text.strip() != ctx.generated_text:
            prediction["raw_prediction"] = ctx.raw_text
        state.predictions.append(prediction)

        t_end = time.perf_counter()
        adapter_timing = {
            "adapter_total_ms": round((t_end - ctx.t_start) * 1000, 1),
        }
        if not ctx.is_forced_silence:
            adapter_timing["prompt_build_ms"] = round(
                (ctx.t_prompt_build_end - ctx.t_prompt_build_start) * 1000, 1
            )
            adapter_timing["vllm_inference_ms"] = round(ctx.inference_time * 1000, 1)
            adapter_timing["post_process_ms"] = round((t_end - ctx.t_inference_end) * 1000, 1)
            adapter_timing["pre_inference_ms"] = round(
                (ctx.t_prompt_build_start - ctx.t_start) * 1000, 1
            )

        if not ctx.is_forced_silence:
            LOGGER.info(
                "[%s] turn=%d timing: total=%.1fms pre=%.1fms prompt_build=%.1fms vllm=%.1fms post=%.1fms",
                state.session_id,
                ctx.turn_count,
                adapter_timing["adapter_total_ms"],
                adapter_timing["pre_inference_ms"],
                adapter_timing["prompt_build_ms"],
                adapter_timing["vllm_inference_ms"],
                adapter_timing["post_process_ms"],
            )
        else:
            LOGGER.info(
                "[%s] turn=%d timing: total=%.1fms (forced silence, inference skipped)",
                state.session_id,
                ctx.turn_count,
                adapter_timing["adapter_total_ms"],
            )

        decision, _, delegation_question = parse_model_decision(ctx.raw_text or "")
        result = _chat_completion_response(
            model=self.config.adapter_model,
            content=ctx.generated_text,
            usage=ctx.usage,
            raw_model=model_name,
            raw_text=ctx.raw_text,
            decision=decision,
            delegation_question=delegation_question,
        )
        result["streamingharness"]["timing"] = adapter_timing
        summarizer_timing = {}
        if state.mid_term_history:
            last_mid = state.mid_term_history[-1]
            summarizer_timing["last_mid_term_ms"] = round(
                last_mid.get("inference_time", 0) * 1000, 1
            )
            summarizer_timing["last_mid_term_chunk"] = last_mid.get("chunk_index")
            if last_mid.get("barrier_wait_time") is not None:
                summarizer_timing["barrier_wait_ms"] = round(
                    last_mid["barrier_wait_time"] * 1000, 1
                )
        if state.long_term_history:
            last_long = state.long_term_history[-1]
            summarizer_timing["last_long_term_ms"] = round(
                last_long.get("inference_time", 0) * 1000, 1
            )
        result["streamingharness"]["summarizer_timing"] = summarizer_timing
        result["streamingharness"]["memory"] = {
            "mid_term_summaries": [
                {
                    "chunk_index": e["chunk_index"],
                    "frame_range": e["frame_range"],
                    "summary_text": e["summary_text"],
                }
                for e in state.mid_term_summaries
            ],
            "long_term_memory": state.memory_state.get("long_term_memory", ""),
        }
        return result

    async def _forward_text_only(
        self,
        payload: dict[str, Any],
        *,
        client: AsyncOpenAI | None = None,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        client = client or self.main_client
        model_name = model_name or self.config.main_model
        generation_kwargs = self._main_generation_kwargs(payload)
        response = await client.chat.completions.create(
            model=model_name,
            messages=payload.get("messages") or [],
            **generation_kwargs,
        )
        raw_text = response.choices[0].message.content if response.choices else ""
        usage = response.usage.model_dump() if getattr(response, "usage", None) else None
        decision, _, delegation_question = parse_model_decision(raw_text or "")
        return _chat_completion_response(
            model=self.config.adapter_model,
            content=raw_text or "",
            usage=usage,
            raw_model=model_name,
            raw_text=raw_text or "",
            decision=decision,
            delegation_question=delegation_question,
        )

    def _time_range_for_frame(self, frame_index: int) -> str:
        start = frame_index * self.config.frame_seconds
        return f"{start:.1f} seconds"

    def _resolve_frame_ref(
        self,
        image_ref: dict[str, str],
        state: SessionState,
    ) -> str:
        if image_ref.get("kind") == "path":
            return str(self._validate_local_image_path(image_ref.get("value", "")))
        if image_ref.get("kind") == "data_url":
            return self._save_base64_frame(image_ref.get("value", ""), state)
        raise web.HTTPBadRequest(text="unsupported image reference kind")

    def _save_base64_frame(self, data_url: str, state: SessionState) -> str:
        match = re.match(r"data:image/\w+;base64,(.+)", data_url)
        if not match:
            raise web.HTTPBadRequest(text="invalid data URL format")
        state.session_frame_counter += 1
        return data_url

    def _validate_local_image_path(self, raw_path: str) -> Path:
        if not self.config.allowed_local_image_roots:
            raise web.HTTPBadRequest(text="local image paths are disabled")

        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise web.HTTPBadRequest(text=f"local image path does not exist: {path}")
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
            raise web.HTTPBadRequest(text=f"unsupported local image extension: {path.suffix}")

        for root in self.config.allowed_local_image_roots:
            root_path = Path(root).expanduser().resolve()
            try:
                path.relative_to(root_path)
                return path
            except ValueError:
                continue

        allowed = ", ".join(self.config.allowed_local_image_roots)
        raise web.HTTPBadRequest(text=f"local image path is outside allowed roots: {allowed}")

    def _update_query_state(
        self,
        state: SessionState,
        prompt_text: str,
        time_range: str,
    ) -> str | None:
        if not self.config.use_prompt_as_query:
            return None

        normalized_prompt = (prompt_text or "").strip()
        if not normalized_prompt:
            return None

        if state.current_query_text is None:
            state.current_query_text = normalized_prompt
            state.query_start_time = time_range
            state.query_in_current_chunk = True
            return normalized_prompt

        if normalized_prompt != state.current_query_text:
            state._pending_qa_archive = (
                state.current_query_text,
                state.query_start_time,
            )
            state.current_query_text = normalized_prompt
            state.query_start_time = time_range
            state.query_in_current_chunk = True
            return normalized_prompt

        return state.current_query_text

    async def _call_main_model(
        self,
        inbound_payload: dict[str, Any],
        api_messages: list[dict[str, Any]],
        *,
        client: AsyncOpenAI | None = None,
        model_name: str | None = None,
        session_state: SessionState | None = None,
        generation_kwargs: dict[str, Any] | None = None,
        http_messages: list[dict[str, Any]] | None = None,
    ) -> tuple[str, dict[str, Any] | None]:
        client = client or self.main_client
        model_name = model_name or self.config.main_model
        generation_kwargs = generation_kwargs or self._main_generation_kwargs(inbound_payload)
        max_total_chars = _compute_prompt_guard_max_chars(self.config.main_ctx_tokens)
        api_messages = http_messages or self._build_main_http_messages(
            api_messages,
            session_state=session_state,
            max_total_chars=max_total_chars,
        )
        response = await client.chat.completions.create(
            model=model_name,
            messages=api_messages,
            **generation_kwargs,
        )
        raw_text = response.choices[0].message.content if response.choices else ""
        usage = response.usage.model_dump() if getattr(response, "usage", None) else None
        return raw_text or "", usage
