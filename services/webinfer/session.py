"""Session lifecycle, output persistence, and debug-input persistence mixin.

Defines :class:`SessionMixin`, which carries the session-management,
output/debug-input persistence, and meta route-handler methods previously
housed on ``StreamingInferAdapter`` in ``adapter_core.py``. It is one of the
five responsibility mixins composed by the coordinator (``adapter_core``).
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from adapter_types import SessionState
from aiohttp import web
from io_utils import derive_light_out_dir, sanitize_output_name
from request_parsing import _read_json, _request_session_id, _safe_session_id
from response_format import _openai_error_response, archive_chunk_response_records

LOGGER = logging.getLogger("streaming_infer_adapter")


class SessionMixin:
    """Session lifecycle, persistence, and meta route handlers."""

    def get_session(self, session_id: str) -> SessionState:
        session_id = _safe_session_id(session_id or "default")
        state = self.sessions.get(session_id)
        if state is None:
            state = SessionState(session_id=session_id)
            if self.config.per_session_dirs and self.config.save_root:
                self._init_session_dirs(state)
            state.output_path = self._session_output_path(state, light=False)
            state.light_output_path = self._session_output_path(state, light=True)
            state.debug_input_dir = self._session_debug_input_dir(state)
            state.async_next_summary_target_turns = self._async_first_summary_turns()
            # Per-session frame directory
            frame_dir = Path(self.config.frame_save_dir) / session_id
            frame_dir.mkdir(parents=True, exist_ok=True)
            state.session_frame_dir = frame_dir
            self.sessions[session_id] = state
            # Memory-store v0.2: fire-and-forget warmup so the first
            # /v1/chat request may already see a populated cache.
            if self.memory_store.is_enabled and state._memory_warmup_task is None:
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    pass  # not in async context; warmup is lazy on first recall
                else:
                    state._memory_warmup_task = asyncio.ensure_future(self._memory_warmup(state))
            LOGGER.info(
                "Created session %s (output=%s light=%s debug_input=%s frames=%s)",
                session_id,
                state.output_path,
                state.light_output_path,
                state.debug_input_dir,
                state.session_frame_dir,
            )
        state.last_access = time.time()
        return state

    def _cleanup_expired_sessions(self) -> list[SessionState]:
        now = time.time()
        timeout = self.config.session_timeout_seconds
        expired = [sid for sid, s in self.sessions.items() if now - s.last_access > timeout]
        expired_states = []
        for sid in expired:
            state = self.sessions.pop(sid, None)
            if state is not None:
                for job in state.async_pending_summary_jobs:
                    job["task"].cancel()
                expired_states.append(state)
                LOGGER.info("Expired session %s (idle %.0fs)", sid, now - state.last_access)
        return expired_states

    async def _session_cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(300)
            try:
                expired_states = self._cleanup_expired_sessions()
                for state in expired_states:
                    await self._flush_session_outputs(state)
                    await self._memory_push(state)
            except Exception:
                LOGGER.exception("session cleanup error")

    def start_background_tasks(self) -> None:
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.ensure_future(self._session_cleanup_loop())

    async def stop_background_tasks(self) -> None:
        """Cancel the cleanup loop and close the memory-store client.

        Wired to aiohttp ``on_cleanup`` so the process can exit cleanly
        without leaking the httpx connection pool.
        """
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except (asyncio.CancelledError, Exception):
                pass
            self._cleanup_task = None
        # Cancel any in-flight per-session warmup tasks.
        for state in list(self.sessions.values()):
            task = getattr(state, "_memory_warmup_task", None)
            if task is not None and not task.done():
                task.cancel()
        # Best-effort close of the memory-store httpx pool.
        try:
            await self.memory_store.aclose()
        except Exception as exc:
            LOGGER.warning("memory_store aclose raised: %s", exc)

    def _init_session_dirs(self, state: SessionState) -> None:
        """Create per-session timestamped output/input directories."""
        session_ts = datetime.fromtimestamp(state.session_started_at).strftime("%Y%m%d_%H%M%S")
        model_name = self.config.output_model_name
        save_root = self.config.save_root

        state.session_out_dir = os.path.join(save_root, f"output_{session_ts}_{model_name}")
        state.session_light_out_dir = derive_light_out_dir(state.session_out_dir)

        Path(state.session_out_dir).mkdir(parents=True, exist_ok=True)
        Path(state.session_light_out_dir).mkdir(parents=True, exist_ok=True)

        if self.config.save_debug_inputs:
            state.debug_input_dir = Path(
                os.path.join(save_root, f"input_{session_ts}_{model_name}")
            )
            state.debug_input_dir.mkdir(parents=True, exist_ok=True)

    async def handle_models(self, request: web.Request) -> web.Response:
        del request
        now = int(time.time())
        data = [
            {
                "id": name,
                "object": "model",
                "created": now,
                "owned_by": "streamingharness",
            }
            for name in self.main_clients
        ]
        return web.json_response({"object": "list", "data": data})

    async def handle_health(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(
            {
                "ok": True,
                "model": self.config.adapter_model,
                "backends": list(self.main_clients.keys()),
                "summarizer_enabled": self.summarizer is not None,
                "sessions": len(self.sessions),
                "memory_store": self.memory_store.health_snapshot(),
            }
        )

    async def handle_reset(self, request: web.Request) -> web.Response:
        payload = await _read_json(request)
        session_id = _request_session_id(request, payload)
        session_id = _safe_session_id(session_id)
        removed_state = self.sessions.pop(session_id, None)
        if removed_state is not None:
            for job in removed_state.async_pending_summary_jobs:
                job["task"].cancel()
            await self._flush_session_outputs(removed_state)
            pushed = await self._memory_push(removed_state)
        else:
            pushed = 0
        removed = removed_state is not None
        return web.json_response(
            {
                "ok": True,
                "session_id": session_id,
                "removed": removed,
                "pushed": pushed,
            }
        )

    async def handle_prompts_active(self, request: web.Request) -> web.Response:
        del request
        paths = self.active_character_prompt_paths()
        return web.json_response(
            {
                "ok": True,
                "enabled": self.config.character_prompts_enabled,
                "extra_paths": list(self.config.character_prompt_paths),
                "files": paths,
                "cache_size": len(self._system_prompt_cache),
                "last_mtime": self._character_prompt_mtime,
                "language": self.config.language,
            }
        )

    async def handle_prompts_reload(self, request: web.Request) -> web.Response:
        del request
        try:
            profiles = self.reload_character_prompts()
        except Exception as exc:
            LOGGER.exception("character prompt reload failed")
            return _openai_error_response(f"reload failed: {exc}", status=500)
        return web.json_response(
            {
                "ok": True,
                "reloaded_files": self.active_character_prompt_paths(),
                "profile_count": len(profiles),
                "enabled": self.config.character_prompts_enabled,
            }
        )

    def _session_output_path(self, state: SessionState, light: bool) -> Path | None:
        if light:
            root = state.session_light_out_dir or self.config.light_out_dir
        else:
            root = state.session_out_dir or self.config.out_dir
        if not root:
            return None
        safe_session = sanitize_output_name(state.session_id)
        return Path(root) / "live" / f"{safe_session}.json"

    def _session_debug_input_dir(self, state: SessionState) -> Path | None:
        if state.debug_input_dir:
            return state.debug_input_dir
        if not self.config.debug_input_dir:
            return None
        return Path(self.config.debug_input_dir)

    def _session_sample_data(self, state: SessionState) -> dict[str, Any]:
        return {
            "task_type": "live",
            "session_id": state.session_id,
            "adapter_model": self.config.adapter_model,
            "main_model": self.config.main_model,
            "main_api_base": self.config.main_api_base,
            "summarizer_model": self.config.summarizer_model,
            "summarizer_api_base": self.config.summarizer_api_base,
            "longterm_model": self.config.longterm_model,
            "longterm_api_base": self.config.longterm_api_base,
            "started_at": datetime.fromtimestamp(state.session_started_at).isoformat(
                timespec="seconds"
            ),
        }

    def _memory_trace(self, state: SessionState) -> dict[str, Any]:
        return {
            "mid_term_summaries": list(state.mid_term_history),
            "long_term_history": list(state.long_term_history),
            "qa_history": list(state.memory_state.get("qa_history", [])),
            "long_term_memory": state.memory_state.get("long_term_memory", ""),
        }

    def _write_json_file(self, path: Path, obj: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as file_obj:
            json.dump(obj, file_obj, ensure_ascii=False, indent=2)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(tmp_path, path)

    def _light_predictions(
        self,
        predictions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        light_keys = (
            "turn",
            "time_range",
            "query",
            "prediction",
            "total_time",
            "inference_time",
            "fourb_mid_term_inference_time",
            "fourb_long_term_inference_time",
            "ground_truth",
        )
        return [
            {key: prediction[key] for key in light_keys if key in prediction}
            for prediction in predictions
        ]

    @staticmethod
    def _strip_base64_images(obj: Any) -> tuple[Any, dict[str, str]]:
        """Recursively strip inline base64 image data from an object.

        Returns a (stripped_obj, images_dict) tuple where images_dict maps
        placeholder keys to the original base64 strings.
        """
        images: dict[str, str] = {}
        counter = [0]

        def _strip(node: Any) -> Any:
            if isinstance(node, str):
                if node.startswith("data:image/") and len(node) > 200:
                    key = f"__image_{counter[0]}__"
                    counter[0] += 1
                    images[key] = node
                    return key
                return node
            if isinstance(node, list):
                return [_strip(item) for item in node]
            if isinstance(node, dict):
                return {k: _strip(v) for k, v in node.items()}
            return node

        stripped = _strip(obj)
        return stripped, images

    def _write_session_outputs_sync(
        self,
        output_path: Path | None,
        light_output_path: Path | None,
        full_result: dict[str, Any] | None,
        light_result: dict[str, Any] | None,
    ) -> None:
        if light_output_path and light_result:
            self._write_json_file(light_output_path, light_result)
        if output_path and full_result:
            stripped_result, images = self._strip_base64_images(full_result)
            self._write_json_file(output_path, stripped_result)
            if images:
                images_path = output_path.with_suffix(".images.json")
                self._write_json_file(images_path, images)

    def _write_session_outputs(self, state: SessionState) -> None:
        total_time = time.time() - state.session_started_at
        output_path = state.output_path
        light_output_path = state.light_output_path
        if not output_path and not light_output_path:
            return
        predictions_snapshot = copy.deepcopy(state.predictions)
        sample_data = self._session_sample_data(state)
        memory_trace = copy.deepcopy(self._memory_trace(state))
        full_result = None
        light_result = None
        if output_path:
            full_result = {
                "sample_data": sample_data,
                "total_time": total_time,
                "total_turns": len(predictions_snapshot),
                "predictions": predictions_snapshot,
                "memory": memory_trace,
            }
        if light_output_path:
            light_result = {
                "sample_data": sample_data,
                "total_time": total_time,
                "total_turns": len(predictions_snapshot),
                "predictions": self._light_predictions(predictions_snapshot),
                "memory": memory_trace,
            }
        if state._pending_write_task and not state._pending_write_task.done():
            state._pending_write_task.cancel()
        task = asyncio.ensure_future(
            asyncio.to_thread(
                self._write_session_outputs_sync,
                output_path,
                light_output_path,
                full_result,
                light_result,
            )
        )
        task.add_done_callback(self._on_write_task_done)
        state._pending_write_task = task

    @staticmethod
    def _on_write_task_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            LOGGER.error("session output write failed: %s", exc, exc_info=exc)

    async def _flush_session_outputs(self, state: SessionState) -> None:
        """Write final session outputs synchronously at session end."""
        self._execute_pending_qa_archive(state)
        if self.config.keep_qa_history and state.current_query_text:
            archive_chunk_response_records(
                state.current_chunk,
                state.memory_state,
                state.current_query_text,
                state.query_start_time,
                chunk_index=state.chunk_index,
            )
        total_time = time.time() - state.session_started_at
        output_path = state.output_path
        light_output_path = state.light_output_path
        if not output_path and not light_output_path:
            return
        if not state.predictions:
            return
        sample_data = self._session_sample_data(state)
        memory_trace = self._memory_trace(state)
        full_result = None
        light_result = None
        if output_path:
            full_result = {
                "sample_data": sample_data,
                "total_time": total_time,
                "total_turns": len(state.predictions),
                "predictions": state.predictions,
                "memory": memory_trace,
            }
        if light_output_path:
            light_result = {
                "sample_data": sample_data,
                "total_time": total_time,
                "total_turns": len(state.predictions),
                "predictions": self._light_predictions(state.predictions),
                "memory": memory_trace,
            }
        await asyncio.to_thread(
            self._write_session_outputs_sync,
            output_path,
            light_output_path,
            full_result,
            light_result,
        )
        LOGGER.info(
            "[%s] final session output written (%d turns)",
            state.session_id,
            len(state.predictions),
        )

    def _save_live_debug_input(
        self,
        state: SessionState,
        record: dict[str, Any],
        stem: str,
    ) -> str | None:
        debug_dir = state.debug_input_dir or self.config.debug_input_dir
        if not debug_dir:
            return None
        path = Path(debug_dir) / f"{sanitize_output_name(state.session_id)}__{stem}.json"
        record = copy.deepcopy(record)
        record.setdefault("saved_at", datetime.now().isoformat(timespec="seconds"))
        record.setdefault("session_id", state.session_id)
        self._write_json_file(path, record)
        return str(path)

    def _maybe_save_chunk_start_model_input(
        self,
        state: SessionState,
        turn_count: int,
        time_range: str,
        model_input_record: dict[str, Any],
    ) -> str | None:
        if not (state.debug_input_dir or self.config.debug_input_dir):
            return None
        if state.chunk_index in state.chunk_start_input_saved:
            return None
        record = copy.deepcopy(model_input_record)
        record["stage"] = "main_8b_chunk_start"
        record["turn"] = turn_count
        record["time_range"] = time_range
        path = self._save_live_debug_input(
            state,
            record,
            f"chunk_{state.chunk_index:04d}__turn_{turn_count:04d}",
        )
        state.chunk_start_input_saved.add(state.chunk_index)
        return path

    def _save_summarizer_debug_input(
        self,
        state: SessionState,
        stage: str,
        index: int,
        record: dict[str, Any] | None,
    ) -> str | None:
        if not record:
            return None
        return self._save_live_debug_input(
            state,
            record,
            f"{stage}__{index:04d}",
        )
