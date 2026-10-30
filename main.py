#!/usr/bin/env python3
"""Local CLI: runs the same pipeline as the API, synchronously, in-process.

    pipenv run python main.py "https://youtu.be/XXXXXXXX" [--keep-audio] [--keep-video] [--language pt]

.env is loaded automatically by app.config.Settings (pydantic-settings'
env_file=".env") — no separate dotenv bootstrap needed here.
"""

import argparse
import logging
import sys

from app import jobstore
from app.config import settings
from app.extractor import resolve_metadata
from app.pipeline import PipelineError, run_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("contexty.cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="contexty",
        description="Baixa/transcreve um vídeo (yt-dlp + ffmpeg + AssemblyAI) e gera data-[ID]/*.md",
    )
    parser.add_argument(
        "source", help="URL suportada pelo yt-dlp, ou um ID (assume YouTube)"
    )
    parser.add_argument(
        "--keep-audio", action="store_true", help="mantém audio.<ext> em data-[ID]/"
    )
    parser.add_argument(
        "--keep-video",
        action="store_true",
        help="baixa o vídeo completo (não só o áudio) e mantém video.<ext> em data-[ID]/",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="força o idioma da transcrição (ex: pt, en); default: auto-detect",
    )
    parser.add_argument(
        "--force-assemblyai",
        action="store_true",
        help="ignora legendas nativas do yt-dlp e sempre transcreve via AssemblyAI",
    )
    parser.add_argument(
        "--cookies-from-browser",
        default=None,
        metavar="BROWSER",
        help="lê cookies do browser local (chrome, firefox, edge, brave, safari, "
        "...) — contorna bloqueios de bot-check do YouTube; só funciona aqui "
        "no CLI local, não no server (sem browser lá — ver CONTEXTY_COOKIES_FILE)",
    )
    args = parser.parse_args(argv)

    if not settings.assemblyai_api_key:
        parser.error(
            "ASSEMBLYAI_API_KEY não configurada (.env ou variável de ambiente)"
        )

    if args.cookies_from_browser:
        # Mutates the shared settings singleton — app.extractor reads it via
        # the same import, no extra plumbing needed (see _cookie_opts()).
        settings.cookies_from_browser = args.cookies_from_browser

    metadata = resolve_metadata(args.source)

    if settings.enable_history_guard and not jobstore.claim(
        metadata.id, args.source, metadata.title
    ):
        print(f"já processado nas últimas 24h: {metadata.id} (nada escrito)")
        return 0

    try:
        result = run_pipeline(
            metadata,
            args.source,
            keep_audio=args.keep_audio,
            keep_video=args.keep_video,
            language=args.language,
            prefer_native_subtitles=not args.force_assemblyai,
        )
    except PipelineError as exc:
        logger.error("pipeline failed: %s", exc)
        return 1

    print(result["data_dir"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
