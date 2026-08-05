"""aiohttp application factory, argument parsing, and CLI entry point (main)."""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime

from adapter_core import StreamingInferAdapter
from adapter_types import AdapterConfig
from aiohttp import web
from io_utils import (
    derive_light_out_dir,
    derive_model_output_name,
    resolve_save_dir,
    sanitize_output_name,
)
from prompt_constants import DEFAULT_SAVE_ROOT, DEFAULT_SYSTEM_PROMPT_EN
from system_prompts import (
    resolve_prompt_paths,
)

from config import _env_bool, _env_float, _env_int, _split_paths

LOGGER = logging.getLogger("streaming_infer_adapter")


def parse_args() -> AdapterConfig:
    """Parse command-line arguments into an :class:`AdapterConfig`."""
    parser = argparse.ArgumentParser(description="StreamingHarness live OpenAI adapter")
    parser.add_argument("--host", default=os.environ.get("ADAPTER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=_env_int("ADAPTER_PORT", 8070))
    parser.add_argument(
        "--adapter-model",
        default=os.environ.get("ADAPTER_MODEL", "streaming-infer-adapter"),
    )
    parser.add_argument(
        "--main-api-base",
        default=os.environ.get("MAIN_API_BASE", "http://127.0.0.1:7060/v1"),
        help="OpenAI-compatible base URL of the main 8B inference backend. Defaults to a local llama-server / vLLM on 127.0.0.1:7060. Override via MAIN_API_BASE to point at a llama-server elsewhere (the URL is OpenAI-compatible).",
    )
    parser.add_argument(
        "--main-model",
        default=os.environ.get("MAIN_MODEL", "streamingharness-8b"),
        help="Model name sent to the main backend (overridable per request via payload model field). Must match what the llama-server / vLLM reports via /v1/models.",
    )
    parser.add_argument(
        "--main-backends",
        default=os.environ.get("MAIN_BACKENDS", ""),
        help='JSON array of backends: [{"name":"...","api_base":"...","model":"..."},...]',
    )
    parser.add_argument("--api-key", default=os.environ.get("MODEL_API_KEY", "EMPTY"))
    parser.add_argument("--frame-seconds", type=float, default=_env_float("FRAME_SECONDS", 1.0))
    parser.add_argument("--max-pixels", type=int, default=_env_int("MAX_PIXELS", 1048576))
    parser.add_argument("--main-max-tokens", type=int, default=_env_int("MAIN_MAX_TOKENS", 128))
    parser.add_argument(
        "--main-ctx-tokens",
        type=int,
        default=_env_int("MAIN_CTX_TOKENS", 16384),
        help="llama-server -c context window (sync with run-windows.env MAIN_CONTEXT).",
    )
    parser.add_argument(
        "--main-temperature",
        type=float,
        default=_env_float("MAIN_TEMPERATURE", 0.8),
    )
    parser.add_argument("--main-top-p", type=float, default=_env_float("MAIN_TOP_P", 0.9))
    parser.add_argument("--main-top-k", type=int, default=_env_int("MAIN_TOP_K", 40))
    parser.add_argument(
        "--main-repetition-penalty",
        type=float,
        default=_env_float("MAIN_REPETITION_PENALTY", 1.0),
    )
    parser.add_argument(
        "--main-presence-penalty",
        type=float,
        default=_env_float("MAIN_PRESENCE_PENALTY", 0.0),
    )
    parser.add_argument(
        "--honor-inbound-generation-params",
        action="store_true",
        default=_env_bool("HONOR_INBOUND_GENERATION_PARAMS", False),
        help="Use max_tokens/temperature/top_p from incoming WebUI requests instead of infer.sh-style defaults.",
    )
    parser.add_argument("--chunk", type=int, default=_env_int("CHUNK", 200))
    parser.add_argument(
        "--compress-every-n-chunks",
        type=int,
        default=_env_int("COMPRESS_EVERY_N_CHUNKS", 5),
    )
    parser.add_argument(
        "--async-summary-lead-frames",
        type=int,
        default=_env_int("ASYNC_SUMMARY_LEAD_FRAMES", 10),
        help="Generate async summaries this many turns before the chunk boundary. Name kept for compatibility.",
    )
    parser.add_argument(
        "--no-prompt-as-query",
        action="store_true",
        default=not _env_bool("USE_PROMPT_AS_QUERY", True),
    )
    parser.add_argument(
        "--force-silence-before-query",
        action="store_true",
        default=_env_bool("FORCE_SILENCE_BEFORE_QUERY", True),
    )
    parser.add_argument(
        "--no-force-silence-before-query",
        action="store_false",
        dest="force_silence_before_query",
        help="Disable infer.sh-style forced </silence> before the first query.",
    )
    parser.add_argument(
        "--no-qa-history",
        action="store_true",
        default=not _env_bool("KEEP_QA_HISTORY", True),
    )
    parser.add_argument(
        "--qa-history-window",
        type=int,
        default=_env_int("QA_HISTORY_WINDOW", 12),
        help="Max recent Q&A pairs kept in memory_state['qa_history'] (0 = unbounded/legacy).",
    )
    parser.add_argument(
        "--no-normalize-output",
        action="store_true",
        default=not _env_bool("NORMALIZE_OUTPUT", True),
    )
    parser.add_argument(
        "--disable-summarizer",
        action="store_true",
        default=not _env_bool("ENABLE_SUMMARIZER", True),
    )
    parser.add_argument(
        "--summarizer-model",
        default=os.environ.get(
            "SUMMARIZER_MODEL",
            "/tmp/models/Qwen3-VL-4B-Instruct",  # noqa: S108
        ),
        help="Model name sent to the chunk-summary backend. The summary backend is OpenAI-compatible (port 8065 by default; pair with llama-server or vLLM).",
    )
    parser.add_argument(
        "--summarizer-api-base",
        default=os.environ.get("SUMMARIZER_API_BASE", "http://127.0.0.1:8065/v1"),
        help="OpenAI-compatible base URL of the summary model. Default targets a local llama-server on 127.0.0.1:8065; override via SUMMARIZER_API_BASE.",
    )
    parser.add_argument(
        "--longterm-model",
        default=os.environ.get(
            "LONGTERM_SUMMARIZER_MODEL",
            os.environ.get("SUMMARIZER_MODEL", "/tmp/models/Qwen3-VL-4B-Instruct"),  # noqa: S108
        ),
        help="Model name used for long-term memory compression. Falls back to SUMMARIZER_MODEL; both share the longterm-api-base.",
    )
    parser.add_argument(
        "--longterm-api-base",
        default=os.environ.get(
            "LONGTERM_SUMMARIZER_API_BASE",
            os.environ.get("SUMMARIZER_API_BASE", "http://127.0.0.1:8065/v1"),
        ),
    )
    parser.add_argument(
        "--summarizer-max-pixels",
        type=int,
        default=_env_int("SUMMARIZER_MAX_PIXELS", 1048576),
    )
    parser.add_argument(
        "--summarizer-key-frames",
        type=int,
        default=_env_int("SUMMARIZER_KEY_FRAMES", 0),
    )
    parser.add_argument(
        "--summarizer-phase-seconds",
        type=float,
        default=_env_float("SUMMARIZER_PHASE_SECONDS", 10.0),
    )
    parser.add_argument(
        "--mid-term-max-tokens",
        type=int,
        default=_env_int("MID_TERM_MAX_TOKENS", 4000),
    )
    parser.add_argument(
        "--mid-term-target-tokens",
        type=int,
        default=_env_int("MID_TERM_TARGET_TOKEN_COUNT", 3000),
    )
    parser.add_argument(
        "--long-term-max-tokens",
        type=int,
        default=_env_int("LONG_TERM_MAX_TOKENS", 2000),
    )
    parser.add_argument(
        "--long-term-target-tokens",
        type=int,
        default=_env_int("LONG_TERM_TARGET_TOKEN_COUNT", 1000),
    )
    parser.add_argument(
        "--mid-term-temperature",
        type=float,
        default=_env_float("MID_TERM_TEMPERATURE", 0.8),
    )
    parser.add_argument(
        "--mid-term-top-p",
        type=float,
        default=_env_float("MID_TERM_TOP_P", 0.9),
    )
    parser.add_argument(
        "--mid-term-top-k",
        type=int,
        default=_env_int("MID_TERM_TOP_K", 40),
    )
    parser.add_argument(
        "--mid-term-repetition-penalty",
        type=float,
        default=_env_float("MID_TERM_REPETITION_PENALTY", 1.0),
    )
    parser.add_argument(
        "--mid-term-presence-penalty",
        type=float,
        default=_env_float("MID_TERM_PRESENCE_PENALTY", 0.0),
    )
    parser.add_argument(
        "--long-term-temperature",
        type=float,
        default=_env_float("LONG_TERM_TEMPERATURE", 1.0),
    )
    parser.add_argument(
        "--long-term-top-p",
        type=float,
        default=_env_float("LONG_TERM_TOP_P", 1.0),
    )
    parser.add_argument(
        "--long-term-top-k",
        type=int,
        default=_env_int("LONG_TERM_TOP_K", 80),
    )
    parser.add_argument(
        "--long-term-repetition-penalty",
        type=float,
        default=_env_float("LONG_TERM_REPETITION_PENALTY", 1.0),
    )
    parser.add_argument(
        "--long-term-presence-penalty",
        type=float,
        default=_env_float("LONG_TERM_PRESENCE_PENALTY", 0.0),
    )
    parser.add_argument(
        "--long-term-memory-window",
        type=int,
        default=_env_int("LONG_TERM_MEMORY_WINDOW", 40),
    )
    parser.add_argument(
        "--long-term-memory-max-tokens",
        type=int,
        default=_env_int("LONG_TERM_MEMORY_MAX_TOKENS", 1800),
        help="Cumulative token budget for rebuilt long_term_memory text (0 = disable).",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=_env_float("REQUEST_TIMEOUT_SECONDS", 300.0),
    )
    parser.add_argument(
        "--allowed-local-image-roots",
        default=os.environ.get("ALLOWED_LOCAL_IMAGE_ROOTS", ""),
        help="Comma- or colon-separated directories whose image files may be referenced directly by requests.",
    )
    parser.add_argument(
        "--frame-save-dir",
        default=os.environ.get("FRAME_SAVE_DIR", "/tmp/streaming_adapter_frames"),  # noqa: S108
        help="Directory to save base64 frames received from WebUI.",
    )
    parser.add_argument(
        "--save-root",
        default=os.environ.get(
            "LIVE_ADAPTER_SAVE_ROOT",
            os.environ.get("SAVE_ROOT", DEFAULT_SAVE_ROOT),
        ),
        help="Root used for auto-generated output_*, output_light_*, and input_* dirs.",
    )
    parser.add_argument(
        "--run-timestamp",
        default=os.environ.get("LIVE_ADAPTER_RUN_TIMESTAMP", ""),
        help="Timestamp suffix for auto-generated live save dirs.",
    )
    parser.add_argument(
        "--output-model-name",
        default=os.environ.get("LIVE_ADAPTER_OUTPUT_MODEL_NAME", ""),
        help="Model-name suffix for auto-generated live save dirs.",
    )
    parser.add_argument(
        "--out-dir",
        default=os.environ.get("LIVE_ADAPTER_OUT_DIR") or os.environ.get("OUT_DIR"),
        help="Full live output directory. Relative paths resolve under save-root.",
    )
    parser.add_argument(
        "--light-out-dir",
        default=os.environ.get("LIVE_ADAPTER_LIGHT_OUT_DIR") or os.environ.get("LIGHT_OUT_DIR"),
        help="Light live output directory. Defaults to output_light_* derived from out-dir.",
    )
    parser.add_argument(
        "--debug-input-dir",
        default=os.environ.get("LIVE_ADAPTER_DEBUG_INPUT_DIR") or os.environ.get("DEBUG_INPUT_DIR"),
        help="Directory for live input_* debug snapshots. Relative paths resolve under save-root.",
    )
    parser.add_argument(
        "--no-live-save",
        action="store_true",
        default=not _env_bool("LIVE_SAVE_OUTPUTS", False),
        help="Disable live output_*/output_light_* writing.",
    )
    parser.add_argument(
        "--no-debug-inputs",
        action="store_true",
        default=not _env_bool("LIVE_SAVE_DEBUG_INPUTS", False),
        help="Disable live input_* debug snapshot writing.",
    )
    parser.add_argument(
        "--no-save-model-inputs",
        action="store_true",
        default=not _env_bool("SAVE_MODEL_INPUTS", True),
        help="Do not embed per-turn model_input records in output_*.",
    )
    parser.add_argument(
        "--no-summarizer-debug",
        action="store_true",
        default=not _env_bool("SUMMARIZER_DEBUG", True),
        help="Do not keep/save mid/long-term summary debug inputs.",
    )
    parser.add_argument(
        "--system-prompt",
        default=os.environ.get("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT_EN),
        help="Base system prompt prepended to every 8B main-model request. The character profile (see --character-prompt) is wrapped in a <character_profile> block ahead of this text. Pass --no-character-prompt to skip injection. Set SYSTEM_PROMPT='' in the env to disable the built-in default.",
    )
    parser.add_argument(
        "--character-prompt",
        action="append",
        default=None,
        metavar="PATH",
        help="Extra .txt/.md file or directory to load character prompts from. May be passed multiple times; defaults to <repo>/prompts/ and the CHARACTER_PROMPT_PATH env var. Hot-reload via POST /v1/prompts/reload.",
    )
    parser.add_argument(
        "--no-character-prompt",
        action="store_true",
        default=not _env_bool("ENABLE_CHARACTER_PROMPT", True),
        help="Disable character-prompt injection. Same as ENABLE_CHARACTER_PROMPT=0 in the env.",
    )
    parser.add_argument(
        "--memory-store-url",
        default=os.environ.get("MEMORY_STORE_URL", "http://127.0.0.1:8997"),
        help="memory-store JSON API base URL (env MEMORY_STORE_URL).",
    )
    parser.add_argument(
        "--no-memory-store",
        action="store_true",
        help="Disable memory-store integration (default: enabled).",
    )
    parser.add_argument(
        "--language",
        default=os.environ.get("ADAPTER_LANGUAGE", "en"),
        choices=["zh", "en"],
        help="Language for context injection text (Video History header, Q&A History header, User Query header). 'zh' for Chinese, 'en' for English.",
    )
    args = parser.parse_args()

    raw_save_root = (args.save_root or DEFAULT_SAVE_ROOT).strip() or DEFAULT_SAVE_ROOT
    save_root = os.path.normpath(os.path.expanduser(raw_save_root))
    run_timestamp = args.run_timestamp.strip() or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_model_name = (
        sanitize_output_name(args.output_model_name)
        if args.output_model_name.strip()
        else derive_model_output_name(args.main_model)
    )
    no_live_save = args.no_live_save
    no_debug_inputs = args.no_debug_inputs
    per_session_dirs = not no_live_save
    explicit_out_dir = resolve_save_dir(args.out_dir, save_root)
    explicit_light_out_dir = resolve_save_dir(args.light_out_dir, save_root)
    explicit_debug_input_dir = resolve_save_dir(args.debug_input_dir, save_root)
    if explicit_out_dir or explicit_light_out_dir or explicit_debug_input_dir:
        per_session_dirs = False

    if no_live_save or per_session_dirs:
        out_dir = None
        light_out_dir = None
    else:
        out_dir = explicit_out_dir
        if out_dir is None:
            out_dir = os.path.join(
                save_root,
                f"output_{run_timestamp}_{output_model_name}",
            )
        light_out_dir = explicit_light_out_dir
        if light_out_dir is None:
            light_out_dir = derive_light_out_dir(out_dir)

    if no_debug_inputs or per_session_dirs:
        debug_input_dir = None
    else:
        debug_input_dir = explicit_debug_input_dir
        if debug_input_dir is None:
            debug_input_dir = os.path.join(
                save_root,
                f"input_{run_timestamp}_{output_model_name}",
            )

    return AdapterConfig(
        host=args.host,
        port=args.port,
        adapter_model=args.adapter_model,
        main_api_base=args.main_api_base,
        main_model=args.main_model,
        main_backends=tuple(json.loads(args.main_backends)) if args.main_backends else (),
        api_key=args.api_key,
        allowed_local_image_roots=_split_paths(args.allowed_local_image_roots),
        frame_seconds=args.frame_seconds,
        max_pixels=args.max_pixels,
        main_max_tokens=args.main_max_tokens,
        main_ctx_tokens=args.main_ctx_tokens,
        main_temperature=args.main_temperature,
        main_top_p=args.main_top_p,
        main_top_k=args.main_top_k,
        main_repetition_penalty=args.main_repetition_penalty,
        main_presence_penalty=args.main_presence_penalty,
        honor_inbound_generation_params=args.honor_inbound_generation_params,
        chunk=args.chunk,
        compress_every_n_chunks=args.compress_every_n_chunks,
        async_summary_lead_frames=args.async_summary_lead_frames,
        use_prompt_as_query=not args.no_prompt_as_query,
        force_silence_before_query=args.force_silence_before_query,
        keep_qa_history=not args.no_qa_history,
        qa_history_window=args.qa_history_window,
        normalize_output=not args.no_normalize_output,
        enable_summarizer=not args.disable_summarizer,
        summarizer_model=args.summarizer_model,
        summarizer_api_base=args.summarizer_api_base,
        longterm_model=args.longterm_model,
        longterm_api_base=args.longterm_api_base,
        summarizer_max_pixels=args.summarizer_max_pixels,
        summarizer_key_frames=args.summarizer_key_frames,
        summarizer_phase_seconds=args.summarizer_phase_seconds,
        mid_term_max_tokens=args.mid_term_max_tokens,
        mid_term_target_tokens=args.mid_term_target_tokens,
        long_term_max_tokens=args.long_term_max_tokens,
        long_term_target_tokens=args.long_term_target_tokens,
        mid_term_temperature=args.mid_term_temperature,
        mid_term_top_p=args.mid_term_top_p,
        mid_term_top_k=args.mid_term_top_k,
        mid_term_repetition_penalty=args.mid_term_repetition_penalty,
        mid_term_presence_penalty=args.mid_term_presence_penalty,
        long_term_temperature=args.long_term_temperature,
        long_term_top_p=args.long_term_top_p,
        long_term_top_k=args.long_term_top_k,
        long_term_repetition_penalty=args.long_term_repetition_penalty,
        long_term_presence_penalty=args.long_term_presence_penalty,
        long_term_memory_window=args.long_term_memory_window,
        long_term_memory_max_tokens=args.long_term_memory_max_tokens,
        request_timeout_seconds=args.request_timeout_seconds,
        out_dir=out_dir,
        light_out_dir=light_out_dir,
        debug_input_dir=debug_input_dir,
        save_root=save_root if per_session_dirs else None,
        output_model_name=output_model_name,
        per_session_dirs=per_session_dirs,
        save_model_inputs=not args.no_save_model_inputs,
        save_debug_inputs=not no_debug_inputs,
        summarizer_debug=not args.no_summarizer_debug,
        frame_save_dir=args.frame_save_dir,
        language=args.language,
        system_prompt=args.system_prompt,
        character_prompts_enabled=not args.no_character_prompt,
        character_prompt_paths=tuple(args.character_prompt or ()),
        memory_store_url=args.memory_store_url,
        memory_store_enabled=not args.no_memory_store,
    )


def create_app(config: AdapterConfig) -> web.Application:
    """Build the aiohttp application and register all adapter routes."""
    adapter = StreamingInferAdapter(config)
    app = web.Application(client_max_size=128 * 1024 * 1024)
    app["adapter"] = adapter

    async def _on_startup(_app: web.Application) -> None:
        adapter.start_background_tasks()
        # Memory-store v0.2: one-shot health probe so the adapter logs
        # a clear WARNING at boot instead of failing silently later.
        try:
            ok = await adapter.memory_store.ping()
            if ok:
                LOGGER.info("memory-store reachable at %s", adapter.memory_store.base_url)
            else:
                LOGGER.warning(
                    "memory-store not reachable at %s; warmup/push will degrade to no-op",
                    adapter.memory_store.base_url,
                )
        except Exception as exc:
            LOGGER.warning("memory-store startup ping raised: %s", exc)

    app.on_startup.append(_on_startup)

    async def _on_cleanup(_app: web.Application) -> None:
        await adapter.stop_background_tasks()

    app.on_cleanup.append(_on_cleanup)
    app.router.add_get("/health", adapter.handle_health)
    app.router.add_get("/v1/models", adapter.handle_models)
    app.router.add_post("/v1/chat/completions", adapter.handle_chat_completions)
    app.router.add_get("/v1/summarizer/route", adapter.handle_summarizer_route)
    app.router.add_post("/v1/summarizer/route", adapter.handle_summarizer_route)
    app.router.add_post("/v1/text/chat", adapter.handle_text_chat)
    app.router.add_post("/v1/streaming/reset", adapter.handle_reset)
    app.router.add_get("/v1/prompts/active", adapter.handle_prompts_active)
    app.router.add_post("/v1/prompts/reload", adapter.handle_prompts_reload)
    return app


def main() -> None:
    """Entry point: parse args, configure logging, and run the adapter."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = parse_args()
    LOGGER.info("Starting adapter on %s:%s", config.host, config.port)
    LOGGER.info("Adapter model: %s", config.adapter_model)
    if config.main_backends:
        LOGGER.info("Multi-backend mode: %d backends", len(config.main_backends))
        for b in config.main_backends:
            LOGGER.info(
                "  Backend: %s -> %s (model=%s)",
                b["name"],
                b["api_base"],
                b.get("model", b["name"]),
            )
    else:
        LOGGER.info("Main model: %s at %s", config.main_model, config.main_api_base)
    if config.character_prompts_enabled:
        try:
            _paths = resolve_prompt_paths(config.character_prompt_paths)
        except Exception:
            _paths = []
        LOGGER.info(
            "Character prompt: enabled (files=%d extra_paths=%s)",
            len(_paths),
            list(config.character_prompt_paths),
        )
    else:
        LOGGER.info("Character prompt: disabled (--no-character-prompt)")
    if config.per_session_dirs:
        LOGGER.info("Live save mode: per-session directories under %s", config.save_root)
    else:
        LOGGER.info("Live output dir: %s", config.out_dir or "disabled")
        LOGGER.info("Live light output dir: %s", config.light_out_dir or "disabled")
        LOGGER.info("Live debug input dir: %s", config.debug_input_dir or "disabled")
    if config.enable_summarizer:
        LOGGER.info(
            "Summarizer APIs: mid=%s long=%s",
            config.summarizer_api_base,
            config.longterm_api_base,
        )
    else:
        LOGGER.info("Summarizer disabled")
    web.run_app(create_app(config), host=config.host, port=config.port)


if __name__ == "__main__":
    main()
