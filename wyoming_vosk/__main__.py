#!/usr/bin/env python
import argparse
import asyncio
import json
import logging
import sqlite3
import sys
import time
from functools import partial
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from text_to_num import alpha2digit
from vosk import KaldiRecognizer, Model, SetLogLevel
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioChunkConverter, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import AsrModel, AsrProgram, Attribution, Describe, Info
from wyoming.server import AsyncEventHandler, AsyncServer

from . import __version__
from .download import CASING_FOR_MODEL, MODELS, UNK_FOR_MODEL, download_model
from .sentences import correct_sentence, load_sentences_for_language

_LOGGER = logging.getLogger()
_DIR = Path(__file__).parent
_CASING = {
    "casefold": lambda s: s.casefold(),
    "lower": lambda s: s.lower(),
    "upper": lambda s: s.upper(),
    "keep": lambda s: s,
}
_DEFAULT_CASING = "casefold"
_DEFAULT_UNK = "[unk]"


class State:
    """State of system"""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.models: Dict[str, Tuple[str, Model]] = {}

    def get_model(
        self, language: str, model_name: Optional[str] = None
    ) -> Optional[Tuple[str, Model]]:
        # Allow override
        model_name = self.args.model_for_language.get(language, model_name)

        if not model_name:
            # Use model matching --model-index
            available_models = MODELS[language]
            model_name = available_models[
                min(self.args.model_index, len(available_models) - 1)
            ]

        assert model_name is not None

        name_and_model = self.models.get(model_name)
        if name_and_model is not None:
            return name_and_model

        # Check if model is already downloaded
        for data_dir in self.args.data_dir:
            model_dir = Path(data_dir) / model_name
            if model_dir.is_dir():
                _LOGGER.debug("Found %s at %s", model_name, model_dir)
                model = Model(str(model_dir))
                name_and_model = (model_name, model)
                self.models[model_name] = name_and_model

                return name_and_model

        model_dir = download_model(language, model_name, self.args.download_dir)
        model = Model(str(model_dir))

        name_and_model = (model_name, model)
        self.models[model_name] = name_and_model

        return name_and_model


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default="stdio://", help="unix:// or tcp://")
    parser.add_argument(
        "--data-dir",
        required=True,
        action="append",
        help="Data directory to check for downloaded models",
    )
    parser.add_argument(
        "--download-dir",
        help="Directory to download models into (default: first data dir)",
    )
    parser.add_argument("--language", default="en", help="Set default model language")
    parser.add_argument(
        "--preload-language",
        action="append",
        default=[],
        help="Preload model for language(s)",
    )
    parser.add_argument(
        "--model-for-language",
        nargs=2,
        metavar=("language", "model"),
        action="append",
        default=[],
        help="Override default model for language",
    )
    parser.add_argument(
        "--casing-for-language",
        nargs=2,
        metavar=("language", "casing"),
        action="append",
        default=[],
        help="Override casing for language (casefold, lower, upper, keep)",
    )
    parser.add_argument(
        "--model-index",
        default=0,
        type=int,
        help="Index of model to use when name is not specified",
    )
    #
    parser.add_argument(
        "--sentences-dir", help="Directory with YAML files for each language"
    )
    parser.add_argument(
        "--database-dir",
        help="Directory to store databases with sentences (default: sentences-dir)",
    )
    parser.add_argument(
        "--correct-sentences",
        nargs="?",
        type=float,
        const=0,
        help="Enable sentence correction with optional score cutoff (0=strict, higher=less strict)",
    )
    parser.add_argument(
        "--limit-sentences",
        action="store_true",
        help="Only sentences in --sentences-dir can be spoken",
    )
    parser.add_argument(
        "--allow-unknown",
        action="store_true",
        help="Return empty transcript when unknown words are spoken",
    )
    #
    parser.add_argument("--debug", action="store_true", help="Log DEBUG messages")
    parser.add_argument(
        "--log-format", default=logging.BASIC_FORMAT, help="Format for log messages"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=__version__,
        help="Print version and exit",
    )
    args = parser.parse_args()

    if (args.correct_sentences is not None) or args.limit_sentences:
        if not args.sentences_dir:
            _LOGGER.fatal(
                "--sentences-dir is required with --correct-sentences or --limit-sentences"
            )
            sys.exit(1)

    if not args.download_dir:
        # Download to first data dir by default
        args.download_dir = args.data_dir[0]

    if not args.database_dir:
        args.database_dir = args.sentences_dir

    # Convert to dict of language -> model
    args.model_for_language = dict(args.model_for_language)

    # Convert to dict of language -> casing
    args.casing_for_language = dict(args.casing_for_language)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO, format=args.log_format
    )
    _LOGGER.debug(args)

    if args.debug:
        # Enable vosk debug logging
        SetLogLevel(0)

    wyoming_info = Info(
        asr=[
            AsrProgram(
                name="vosk",
                description="A speech recognition toolkit",
                attribution=Attribution(
                    name="Alpha Cephei",
                    url="https://alphacephei.com/vosk/",
                ),
                installed=True,
                version=__version__,
                models=[
                    AsrModel(
                        name=model_name,
                        description=model_name.replace("vosk-model-", ""),
                        attribution=Attribution(
                            name="Alpha Cephei",
                            url="https://alphacephei.com/vosk/models",
                        ),
                        installed=True,
                        version=None,
                        languages=[language],
                    )
                    for language, model_names in MODELS.items()
                    for model_name in model_names
                ],
            )
        ],
    )

    state = State(args)
    for language in args.preload_language:
        _LOGGER.debug("Preloading model for %s", language)
        state.get_model(language)
        load_sentences_for_language(args.sentences_dir, language, args.database_dir)

    _LOGGER.info("Ready")

    # Start server
    server = AsyncServer.from_uri(args.uri)

    try:
        await server.run(partial(VoskEventHandler, wyoming_info, args, state))
    except KeyboardInterrupt:
        pass


# -----------------------------------------------------------------------------


class VoskEventHandler(AsyncEventHandler):
    """Event handler for clients."""

    def __init__(
        self,
        wyoming_info: Info,
        cli_args: argparse.Namespace,
        state: State,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)

        self.cli_args = cli_args
        self.wyoming_info_event = wyoming_info.event()
        self.client_id = str(time.monotonic_ns())
        self.state = state
        self.converter = AudioChunkConverter(rate=16000, width=2, channels=1)
        self.audio_buffer = bytes()
        self.language: Optional[str] = None
        self.model_name: Optional[str] = None
        self.recognizer: Optional[KaldiRecognizer] = None

        _LOGGER.debug("Client connected: %s", self.client_id)

    async def handle_event(self, event: Event) -> bool:
        if Describe.is_type(event.type):
            await self.write_event(self.wyoming_info_event)
            _LOGGER.debug("Sent info to client: %s", self.client_id)
            return True

        if Transcribe.is_type(event.type):
            # Request to transcribe: set language/model
            transcribe = Transcribe.from_event(event)
            self.language = transcribe.language
            self.model_name = transcribe.name
        elif AudioStart.is_type(event.type):
            # Recognized, but we don't do anything until we get an audio chunk
            pass
        elif AudioChunk.is_type(event.type):
            if self.recognizer is None:
                # Load recognizer on first audio chunk
                self.language = self.language or self.cli_args.language
                name_and_model = self.state.get_model(self.language, self.model_name)
                assert (
                    name_and_model is not None
                ), f"No model named: {self.model_name} for language: {self.language}"
                self.model_name, model = name_and_model

                start_time = time.monotonic()
                self.recognizer = self._load_recognizer(model)
                end_time = time.monotonic()
                _LOGGER.debug(
                    "Loaded recognizer in %0.2f second(s)", end_time - start_time
                )

            assert self.recognizer is not None

            # Process audio chunk
            chunk = AudioChunk.from_event(event)
            chunk = self.converter.convert(chunk)
            self.recognizer.AcceptWaveform(chunk.audio)

        elif AudioStop.is_type(event.type):
            # Get transcript
            assert self.recognizer is not None
            result = json.loads(self.recognizer.FinalResult())
            text = alpha2digit(result["text"], self.language)
            _LOGGER.debug("Transcript for client %s: %s", self.client_id, text)

            if self.cli_args.correct_sentences is not None:
                original_text = text
                text = self._fix_transcript(original_text)
                if text != original_text:
                    _LOGGER.debug("Corrected transcript: %s", text)

            await self.write_event(Transcript(text=text).event())

            return False
        else:
            _LOGGER.debug("Unexpected event: type=%s, data=%s", event.type, event.data)

        return True

    async def disconnect(self) -> None:
        _LOGGER.debug("Client disconnected: %s", self.client_id)

    def _load_recognizer(self, model: Model) -> KaldiRecognizer:
        """Loads Kaldi recognizer for the model, optionally limited by user-provided sentences."""
        if self.cli_args.limit_sentences:
            assert self.language, "Language not set"
            lang_config = load_sentences_for_language(
                self.cli_args.sentences_dir,
                self.language,
                self.cli_args.database_dir,
            )
            if (lang_config is not None) and lang_config.database_path.is_file():
                words: List[str] = []
                with sqlite3.connect(str(lang_config.database_path)) as db_conn:
                    cursor = db_conn.execute("SELECT word from WORDS")
                    for row in cursor:
                        words.append(row[0])

                casing_func_name = CASING_FOR_MODEL.get(
                    self.model_name,
                    self.cli_args.casing_for_language.get(
                        self.language, _DEFAULT_CASING
                    ),
                )
                _LOGGER.debug(
                    "Limiting to %s possible word(s) with casing=%s",
                    len(words),
                    casing_func_name,
                )

                if self.cli_args.allow_unknown:
                    # Enable unknown words (will return empty transcript)
                    words.append(UNK_FOR_MODEL.get(self.model_name, _DEFAULT_UNK))

                casing_func = _CASING[casing_func_name]
                limited_str = json.dumps(
                    [casing_func(w) for w in words], ensure_ascii=False
                )
                return KaldiRecognizer(model, 16000, limited_str)

        # Open-ended
        return KaldiRecognizer(model, 16000)

    def _fix_transcript(self, text: str) -> str:
        """Corrects a transcript using user-provided sentences."""
        assert self.language, "Language not set"
        lang_config = load_sentences_for_language(
            self.cli_args.sentences_dir,
            self.language,
            self.cli_args.database_dir,
        )

        if self.cli_args.allow_unknown and self._has_unknown(text):
            if lang_config is not None:
                return lang_config.unknown_text or ""

            return ""

        if lang_config is None:
            # Can't fix
            return text

        return correct_sentence(
            text, lang_config, score_cutoff=self.cli_args.correct_sentences
        )

    def _has_unknown(self, text: str) -> bool:
        """Return true if text contains unknown token."""
        unk_token = UNK_FOR_MODEL.get(self.model_name, _DEFAULT_UNK)
        return (text == unk_token) or (unk_token in text.split())


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
