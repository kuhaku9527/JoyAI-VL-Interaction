"""Summarizer-routing mixin: hot-swap endpoint, chunk flush, mid/long-term summary build/compress, async summary commit.

Defines :class:`SummarizerRoutingMixin`, which carries the summarizer
hot-swap route handler, chunk flush, mid/long-term summary construction and
compression, and the async-summary submission/commit-barrier helpers
previously on ``StreamingInferAdapter``.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from typing import Any

from adapter_types import SessionState
from aiohttp import web
from config import reset_chunk_state
from io_utils import _file_to_data_url_cached
from request_parsing import _read_json
from response_format import _openai_error_response
from time_ranges import _compute_chunk_frame_range, _get_response_frame_indices

LOGGER = logging.getLogger("streaming_infer_adapter")


class SummarizerRoutingMixin:
    """Summarizer hot-swap routing, chunk flush, and async summary commit."""

    async def handle_summarizer_route(self, request: web.Request) -> web.Response:
        """GET = snapshot current summarizer routing. POST = hot-swap.

        The webui services config panel proxies to this endpoint so the
        webui never mutates the summarizer directly. This keeps webinfer
        the single main path: webui -> webinfer -> mutate -> webinfer -> webui.

        POST body (all keys optional; omitted fields are left alone):
          { "api_base": str, "model_name": str, "api_key": str | null }
        """
        if self.summarizer is None:
            return _openai_error_response("summarizer not enabled", status=503)
        if request.method == "GET":
            return web.json_response(self.summarizer.snapshot_routing())
        try:
            payload = await _read_json(request)
        except Exception as exc:
            return _openai_error_response(f"invalid JSON body: {exc}", status=400)
        snapshot = self.summarizer.update_routing(
            api_base=payload.get("api_base"),
            model_name=payload.get("model_name"),
            api_key=payload.get("api_key"),
        )
        LOGGER.info(
            "summarizer routing updated: api_base=%s model_name=%s api_key_set=%s",
            snapshot["api_base"],
            snapshot["model_name"],
            snapshot["api_key_set"],
        )
        return web.json_response(snapshot)

    async def _flush_chunk(self, state: SessionState, use_async_summary: bool = False) -> None:
        current_chunk = state.current_chunk
        if current_chunk["frame_count"] <= 0:
            return

        _file_to_data_url_cached.cache_clear()

        if self.summarizer is not None and use_async_summary:
            await self._commit_required_async_summaries(
                state,
                state.turn_count,
                non_blocking=False,
            )
        elif self.summarizer is not None:
            mid_term_entry, summary_time = await asyncio.to_thread(
                self._build_mid_term_summary_entry,
                state,
                copy.deepcopy(current_chunk),
            )
            state.mid_term_summaries.append(mid_term_entry)
            state.mid_term_history.append(mid_term_entry)
            LOGGER.info(
                "[%s] chunk=%d range=%s mid-summary %.3fs (%d/%d buffered)",
                state.session_id,
                mid_term_entry["chunk_index"],
                mid_term_entry["frame_range"],
                summary_time,
                len(state.mid_term_summaries),
                self.config.compress_every_n_chunks,
            )
            if len(state.mid_term_summaries) >= self.config.compress_every_n_chunks:
                await asyncio.to_thread(self._compress_mid_terms, state)

    def _build_mid_term_summary_entry(
        self,
        state: SessionState,
        chunk_snapshot: dict[str, Any],
        chunk_index: int | None = None,
        current_query_text: str | None = None,
        query_start_time: str | None = None,
    ) -> tuple[dict[str, Any], float]:
        assert self.summarizer is not None
        resolved_chunk_index = chunk_index if chunk_index is not None else state.chunk_index
        resolved_query_text = (
            current_query_text
            if current_query_text is not None
            else (state.current_query_text or "")
        )
        resolved_query_start_time = (
            query_start_time if query_start_time is not None else state.query_start_time
        )
        frame_range = _compute_chunk_frame_range(chunk_snapshot)
        key_frames = self.summarizer.select_key_frames(
            chunk_snapshot["image_paths"],
            chunk_snapshot["frame_time_ranges"],
            _get_response_frame_indices(chunk_snapshot["messages"]),
            chunk_snapshot["summarizer_frame_cache"],
        )
        start = time.time()
        summary, mid_term_debug_input = self.summarizer.generate_detailed_summary(
            resolved_chunk_index,
            frame_range,
            key_frames,
            chunk_snapshot["frame_count"],
            resolved_query_text,
        )
        elapsed = time.time() - start
        debug_input_path = self._save_summarizer_debug_input(
            state,
            "mid_term",
            resolved_chunk_index,
            copy.deepcopy(mid_term_debug_input),
        )
        entry = {
            "chunk_index": resolved_chunk_index,
            "frame_range": frame_range,
            "query": resolved_query_text,
            "query_start_time": resolved_query_start_time,
            "summary_text": summary,
            "frame_count": chunk_snapshot["frame_count"],
            "key_frame_count": len(key_frames),
            "inference_time": round(elapsed, 3),
            "compressed_to_long_term": False,
        }
        if debug_input_path:
            entry["debug_input_path"] = debug_input_path
        return entry, elapsed

    def _compress_mid_terms(self, state: SessionState) -> None:
        assert self.summarizer is not None
        batch_index = state.long_term_compression_next_index
        state.long_term_compression_next_index += 1
        source_chunk_indices = [entry["chunk_index"] for entry in state.mid_term_summaries]
        source_frame_ranges = [entry["frame_range"] for entry in state.mid_term_summaries]
        start = time.time()
        merged, token_count, compressed_text, long_term_debug_input = (
            self.summarizer.batch_compress_to_longterm(
                state.memory_state["long_term_memory"],
                state.mid_term_summaries,
            )
        )
        elapsed = time.time() - start
        state.memory_state["long_term_memory"] = merged
        for entry in state.mid_term_summaries:
            entry["compressed_to_long_term"] = True
            entry["compressed_batch_index"] = batch_index

        long_term_entry = {
            "batch_index": batch_index,
            "query": state.current_query_text,
            "query_start_time": state.query_start_time,
            "source_chunk_indices": source_chunk_indices,
            "source_frame_ranges": source_frame_ranges,
            "source_summary_count": len(source_frame_ranges),
            "compressed_text": compressed_text,
            "inference_time": round(elapsed, 3),
            "token_count_after_append": token_count,
        }
        debug_input_path = self._save_summarizer_debug_input(
            state,
            "long_term",
            batch_index,
            copy.deepcopy(long_term_debug_input),
        )
        if debug_input_path:
            long_term_entry["debug_input_path"] = debug_input_path
        state.long_term_history.append(long_term_entry)

        window = int(self.config.long_term_memory_window or 0)
        if window > 0 and len(state.long_term_history) > window:
            dropped_count = len(state.long_term_history) - window
            del state.long_term_history[:dropped_count]
            state.memory_state["long_term_memory"] = "\n\n".join(
                entry["compressed_text"].rstrip()
                for entry in state.long_term_history
                if entry.get("compressed_text")
            )
            token_count = self.summarizer.estimate_tokens(state.memory_state["long_term_memory"])
            long_term_entry["token_count_after_slide"] = token_count

        state.mid_term_summaries.clear()
        LOGGER.info(
            "[%s] long-term compression batch=%d %.3fs tokens=%d",
            state.session_id,
            batch_index,
            elapsed,
            token_count,
        )

    def _async_summary_enabled(self) -> bool:
        return (
            self.summarizer is not None
            and self.config.chunk > 0
            and int(self.config.async_summary_lead_frames or 0) > 0
        )

    def _async_first_summary_turns(self) -> int:
        lead_turns = max(0, int(self.config.async_summary_lead_frames or 0))
        chunk = max(1, int(self.config.chunk or 1))
        return max(1, chunk - lead_turns + 1) if lead_turns > 0 else chunk

    def _append_async_summary_user_message(
        self,
        state: SessionState,
        time_range=None,
        image_path=None,
        query_text=None,
        *,
        time_ranges=None,
        image_paths=None,
    ) -> None:
        if time_ranges is None:
            time_ranges = [time_range] if time_range else []
        if image_paths is None:
            image_paths = [image_path] if image_path else []
        segment = state.async_summary_segment
        for tr, ip in zip(time_ranges, image_paths):
            segment["image_paths"].append(ip)
            segment["frame_time_ranges"].append(tr)
            segment["summarizer_frame_cache"].append({"path": ip})
            segment["frame_count"] += 1
        segment["turn_count"] += 1
        segment["messages"].append(
            self._build_internal_user_message(
                time_ranges=time_ranges,
                image_paths=image_paths,
                query_text=query_text,
            )
        )

    def _submit_async_summary_if_needed(self, state: SessionState) -> None:
        if not self._async_summary_enabled():
            return

        if state.async_next_summary_target_turns <= 0:
            state.async_next_summary_target_turns = self._async_first_summary_turns()
        if state.async_summary_segment["turn_count"] < state.async_next_summary_target_turns:
            return

        segment_snapshot = copy.deepcopy(state.async_summary_segment)
        summary_index = state.async_next_summary_index
        required_turn_count = state.turn_count + max(
            0, int(self.config.async_summary_lead_frames or 0) - 1
        )
        task = asyncio.create_task(
            asyncio.to_thread(
                self._build_mid_term_summary_entry,
                state,
                segment_snapshot,
                summary_index,
                state.current_query_text or "",
                state.query_start_time,
            )
        )
        state.async_pending_summary_jobs.append(
            {
                "summary_index": summary_index,
                "submitted_turn_count": state.turn_count,
                "submitted_frame_count": state.frame_count,
                "required_turn_count": required_turn_count,
                "task": task,
            }
        )
        LOGGER.info(
            "[%s] submitted async mid-summary %d at turn=%d required_by_turn=%d",
            state.session_id,
            summary_index,
            state.turn_count,
            required_turn_count,
        )

        state.async_summary_segment = reset_chunk_state()
        state.async_next_summary_index += 1
        state.async_next_summary_target_turns = max(1, int(self.config.chunk or 1))

    async def _commit_required_async_summaries(
        self,
        state: SessionState,
        upto_turn_count: int | None = None,
        wait_all: bool = False,
        non_blocking: bool = False,
    ) -> None:
        if not self._async_summary_enabled():
            return

        while state.async_pending_summary_jobs:
            job = state.async_pending_summary_jobs[0]
            is_required = wait_all or (
                upto_turn_count is not None and job["required_turn_count"] <= upto_turn_count
            )
            if not is_required:
                break

            if non_blocking and not job["task"].done():
                break

            wait_start = time.time()
            mid_term_entry, summary_time = await job["task"]
            wait_time = time.time() - wait_start
            mid_term_entry["async_summary"] = True
            mid_term_entry["turn_count"] = job.get("submitted_turn_count", 0)
            mid_term_entry["submitted_turn_count"] = job["submitted_turn_count"]
            mid_term_entry["submitted_frame_count"] = job["submitted_frame_count"]
            mid_term_entry["required_turn_count"] = job["required_turn_count"]
            mid_term_entry["barrier_wait_time"] = round(wait_time, 3)
            state.async_pending_summary_jobs.pop(0)

            state.mid_term_summaries.append(mid_term_entry)
            state.mid_term_history.append(mid_term_entry)
            LOGGER.info(
                "[%s] committed async mid-summary %d range=%s wait=%.3fs (%d/%d buffered)",
                state.session_id,
                mid_term_entry["chunk_index"],
                mid_term_entry["frame_range"],
                wait_time,
                len(state.mid_term_summaries),
                self.config.compress_every_n_chunks,
            )
            if len(state.mid_term_summaries) >= self.config.compress_every_n_chunks:
                await asyncio.to_thread(self._compress_mid_terms, state)
