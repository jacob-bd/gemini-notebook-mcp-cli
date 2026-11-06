#!/usr/bin/env python3
"""StudioMixin for NotebookLM client - studio content creation and status."""

import contextlib
from typing import Any, Protocol, cast

from . import constants
from .base import BaseClient
from .errors import KickoffOutcomeUnknownError
from .utils import is_mind_map_json, parse_timestamp


class _SourceLookupProtocol(Protocol):
    def get_notebook_sources_with_types(self, notebook_id: str) -> list[dict[str, Any]]: ...


class StudioMixin(BaseClient):
    """Mixin providing studio content creation and status operations.

    This mixin handles all studio artifact operations:
    - Audio overview creation (podcasts)
    - Video overview creation
    - Report generation (briefing docs, study guides, blog posts)
    - Flashcards and quiz generation
    - Infographic creation
    - Slide deck creation
    - Data table creation
    - Mind map generation and management
    - Status polling and artifact deletion
    """

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_all_source_ids(self, notebook_id: str) -> list[str]:
        """Get all source IDs from a notebook.

        Uses get_notebook_sources_with_types() for structured, reliable access.

        Args:
            notebook_id: The notebook UUID

        Returns:
            List of source UUIDs, or empty list if none found
        """
        source_client = cast(_SourceLookupProtocol, self)
        sources = source_client.get_notebook_sources_with_types(notebook_id)
        return [s["id"] for s in sources if s.get("id")]

    def _audio_has_media_urls(self, artifact_data: list[Any]) -> bool:
        """Return True when an audio artifact exposes playable/downloadable media URLs."""
        if len(artifact_data) <= 6:
            return False

        audio_options = artifact_data[6]
        if not isinstance(audio_options, list) or len(audio_options) <= 5:
            return False

        media_list = audio_options[5]
        if not isinstance(media_list, list):
            return False

        return any(
            isinstance(item, list)
            and len(item) > 0
            and isinstance(item[0], str)
            and item[0].startswith("http")
            for item in media_list
        )

    def _extract_audio_media_url(self, artifact_data: list[Any]) -> str | None:
        """Extract the best available audio media URL from an audio artifact payload.

        Google's media list contains entries with different URL suffixes:
          ``=m140-dv``  (priority 4, download variant — fast CDN)
          ``=m140``     (priority 1, streaming transcode — slow CDN)
        Prefer the ``-dv`` variant for downloads.

        See: https://github.com/jacob-bd/gemini-notebook-mcp-cli/issues/158
        """
        if len(artifact_data) <= 6:
            return None

        audio_options = artifact_data[6]
        if not isinstance(audio_options, list):
            return None

        if len(audio_options) > 5 and isinstance(audio_options[5], list):
            media_list = audio_options[5]

            # First pass: prefer the -dv download variant (fast CDN).
            for item in media_list:
                if (
                    isinstance(item, list)
                    and len(item) > 2
                    and isinstance(item[0], str)
                    and item[0].startswith("http")
                    and item[2] == "audio/mp4"
                    and item[0].endswith("-dv")
                ):
                    return item[0]

            # Second pass: any audio/mp4 URL.
            for item in media_list:
                if (
                    isinstance(item, list)
                    and len(item) > 2
                    and isinstance(item[0], str)
                    and item[0].startswith("http")
                    and item[2] == "audio/mp4"
                ):
                    return item[0]

            # Third pass: first valid media URL regardless of type.
            for item in media_list:
                if (
                    isinstance(item, list)
                    and len(item) > 0
                    and isinstance(item[0], str)
                    and item[0].startswith("http")
                ):
                    return item[0]

        # Older payloads may still expose a direct URL at position 3.
        if len(audio_options) > 3 and isinstance(audio_options[3], str):
            return audio_options[3]

        return None

    @staticmethod
    def _coerce_source_ids(raw: Any) -> list[str]:
        """Coerce a raw source list into UUID strings.

        Entries appear as bare strings (``"uuid"``), UUIDs wrapped in one or
        more lists, or (interactive reports) ``[["uuid"], null, 5]`` where
        metadata follows the id; the id is always the first item. Anything
        else is ignored.
        """
        if not isinstance(raw, list):
            return []
        ids: list[str] = []
        for entry in raw:
            while isinstance(entry, list) and entry:
                entry = entry[0]
            if isinstance(entry, str):
                ids.append(entry)
        return ids

    def _extract_artifact_source_ids(self, artifact_data: list[Any], type_code: Any) -> list[str]:
        """Source UUIDs an artifact was generated from.

        Per the ``gArtLc`` poll response (see ``docs/API_REFERENCE.md``), the
        source list is carried at the top-level index ``[3]`` for all artifact
        types. Some audio payloads also nest it inside the options blob at
        ``[6][1][3]``; fall back to that when the top-level field is empty.
        """
        # Top-level source field — documented, type-agnostic.
        if len(artifact_data) > 3:
            ids = self._coerce_source_ids(artifact_data[3])
            if ids:
                return ids

        # Audio fallback: sources nested in the options blob at [6][1][3].
        if type_code == self.STUDIO_TYPE_AUDIO and len(artifact_data) > 6:
            options_data = artifact_data[6]
            if isinstance(options_data, list) and len(options_data) > 1:
                inner = options_data[1]
                if isinstance(inner, list) and len(inner) > 3:
                    return self._coerce_source_ids(inner[3])

        return []

    def _normalize_studio_status(self, artifact_data: Any) -> str:
        """Map raw artifact status codes to stable CLI status labels.

        Audio artifacts have been observed returning status code ``2`` after
        generation, while simultaneously exposing media URLs in their payload.
        Treat only that verified combination as completed; keep other unknown
        codes unchanged.
        """
        if not isinstance(artifact_data, list) or len(artifact_data) <= 4:
            return "unknown"

        status_code = artifact_data[4] if len(artifact_data) > 4 else None
        if status_code == 1:
            return "in_progress"
        if status_code == 3:
            return "completed"
        if status_code == 4:
            return "failed"
        if status_code == 5:
            # Suggested artifacts are the placeholder elements an interactive
            # report embeds (mind map / quiz / flashcards / slide deck / ...).
            return "suggested"

        type_code = artifact_data[2] if len(artifact_data) > 2 else None
        if (
            status_code == 2
            and type_code == self.STUDIO_TYPE_AUDIO
            and self._audio_has_media_urls(artifact_data)
        ):
            return "completed"

        if status_code == 2 and type_code in (
            self.STUDIO_TYPE_INTERACTIVE_REPORT,
            self.STUDIO_TYPE_FLASHCARDS,
            self.STUDIO_TYPE_SLIDE_DECK,
            self.STUDIO_TYPE_INFOGRAPHIC,
            self.STUDIO_TYPE_AUDIO,
            self.STUDIO_TYPE_VIDEO,
        ):
            # Interactive reports and their embedded elements report code 2
            # (queued/generating) before flipping to 3 (completed). Verified
            # live for the report and every element kind. Audio with media
            # URLs at code 2 is handled above as completed.
            return "queued"

        return "unknown"

    # =========================================================================
    # Studio Operations
    # =========================================================================

    def create_audio_overview(
        self,
        notebook_id: str,
        source_ids: list[str] | None = None,
        format_code: int = 1,  # AUDIO_FORMAT_DEEP_DIVE
        length_code: int = 2,  # AUDIO_LENGTH_DEFAULT
        language: str = "en",
        focus_prompt: str = "",
    ) -> dict[str, Any] | None:
        """Create an Audio Overview (podcast) for a notebook."""
        # Default to all sources if not specified
        if source_ids is None:
            source_ids = self._get_all_source_ids(notebook_id)

        if not source_ids:
            raise ValueError(
                f"No sources found in notebook {notebook_id}. Add sources before creating studio content."
            )

        # Build source IDs in the nested format: [[[id1]], [[id2]], ...]
        sources_nested = [[[sid]] for sid in source_ids]

        # Build source IDs in the simpler format: [[id1], [id2], ...]
        sources_simple = [[sid] for sid in source_ids]

        audio_options = [
            None,
            [focus_prompt, length_code, None, sources_simple, language, None, format_code],
        ]

        params = [
            [2],
            notebook_id,
            [None, None, self.STUDIO_TYPE_AUDIO, sources_nested, None, None, audio_options],
        ]

        result = self._call_rpc(self.RPC_CREATE_STUDIO, params, f"/notebook/{notebook_id}")

        if result and isinstance(result, list) and len(result) > 0:
            artifact_data = result[0]
            artifact_id = (
                artifact_data[0]
                if isinstance(artifact_data, list) and len(artifact_data) > 0
                else None
            )

            return {
                "artifact_id": artifact_id,
                "notebook_id": notebook_id,
                "type": "audio",
                "status": self._normalize_studio_status(artifact_data),
                "format": constants.AUDIO_FORMATS.get_name(format_code),
                "length": constants.AUDIO_LENGTHS.get_name(length_code),
                "language": language,
            }

        return None

    def create_video_overview(
        self,
        notebook_id: str,
        source_ids: list[str] | None = None,
        format_code: int = 1,  # VIDEO_FORMAT_EXPLAINER
        visual_style_code: int | None = 1,  # VIDEO_STYLE_AUTO_SELECT
        visual_style_prompt: str = "",
        language: str = "en",
        focus_prompt: str = "",
    ) -> dict[str, Any] | None:
        """Create a Video Overview for a notebook."""
        # Default to all sources if not specified
        if source_ids is None:
            source_ids = self._get_all_source_ids(notebook_id)

        if not source_ids:
            raise ValueError(
                f"No sources found in notebook {notebook_id}. Add sources before creating studio content."
            )

        # Build source IDs in the nested format: [[[id1]], [[id2]], ...]
        sources_nested = [[[sid]] for sid in source_ids]

        # Build source IDs in the simpler format: [[id1], [id2], ...]
        sources_simple = [[sid] for sid in source_ids]

        # Build inner options — Cinematic (code 3) and Short (code 4) omit visual_style_code
        inner_options = [
            sources_simple,
            None if format_code == constants.VIDEO_FORMAT_SHORT else language,
            focus_prompt,
            None,
            format_code,
        ]
        if format_code == constants.VIDEO_FORMAT_SHORT:
            # Live captures send null in the language slot for Short videos.
            # The service adds a best-effort language requirement to the focus
            # prompt when callers request a non-English language. The trailing
            # flag value `1` was observed on 2026-06-30; its meaning is unknown.
            inner_options.extend([None, None, 1])
        elif format_code != constants.VIDEO_FORMAT_CINEMATIC:
            inner_options.append(visual_style_code)
            if visual_style_prompt:
                inner_options.append(visual_style_prompt)

        video_options = [None, None, inner_options]

        params = [
            [2],
            notebook_id,
            [
                None,
                None,
                self.STUDIO_TYPE_VIDEO,
                sources_nested,
                None,
                None,
                None,
                None,
                video_options,
            ],
        ]

        result = self._call_rpc(self.RPC_CREATE_STUDIO, params, f"/notebook/{notebook_id}")

        if result and isinstance(result, list) and len(result) > 0:
            artifact_data = result[0]
            artifact_id = (
                artifact_data[0]
                if isinstance(artifact_data, list) and len(artifact_data) > 0
                else None
            )

            return {
                "artifact_id": artifact_id,
                "notebook_id": notebook_id,
                "type": "video",
                "status": self._normalize_studio_status(artifact_data),
                "format": constants.VIDEO_FORMATS.get_name(format_code),
                "visual_style": constants.VIDEO_STYLES.get_name(visual_style_code)
                if format_code
                not in (constants.VIDEO_FORMAT_CINEMATIC, constants.VIDEO_FORMAT_SHORT)
                and visual_style_code is not None
                else None,
                "visual_style_prompt": visual_style_prompt or None,
                "language": "en" if format_code == constants.VIDEO_FORMAT_SHORT else language,
            }

        return None

    def poll_studio_status(self, notebook_id: str) -> list[dict[str, Any]]:
        """Poll for studio content (audio/video overviews) status."""
        # Poll params: [[2], notebook_id, 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"']
        params = [[2], notebook_id, 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"']
        result = self._call_rpc(self.RPC_POLL_STUDIO, params, path=f"/notebook/{notebook_id}")

        artifacts = []
        if result and isinstance(result, list) and len(result) > 0:
            # Response is an array of artifacts, possibly wrapped
            artifact_list = result[0] if isinstance(result[0], list) else result

            for artifact_data in artifact_list:
                if not isinstance(artifact_data, list) or len(artifact_data) < 5:
                    continue

                artifact_id = artifact_data[0]
                title = artifact_data[1] if len(artifact_data) > 1 else ""
                type_code = artifact_data[2] if len(artifact_data) > 2 else None
                audio_url = None
                video_url = None
                duration_seconds = None

                # Audio artifacts have URLs at position 6
                if type_code == self.STUDIO_TYPE_AUDIO and len(artifact_data) > 6:
                    audio_options = artifact_data[6]
                    if isinstance(audio_options, list) and len(audio_options) > 3:
                        audio_url = self._extract_audio_media_url(artifact_data)
                        # Duration is often at position 9
                        if len(audio_options) > 9 and isinstance(audio_options[9], list):
                            duration_seconds = audio_options[9][0] if audio_options[9] else None

                # Video artifacts have URLs at position 8
                if type_code == self.STUDIO_TYPE_VIDEO and len(artifact_data) > 8:
                    video_options = artifact_data[8]
                    if isinstance(video_options, list) and len(video_options) > 3:
                        video_url = video_options[3] if isinstance(video_options[3], str) else None

                # Infographic artifacts have image URL at position 14
                infographic_url = None
                if type_code == self.STUDIO_TYPE_INFOGRAPHIC and len(artifact_data) > 14:
                    infographic_options = artifact_data[14]
                    if isinstance(infographic_options, list) and len(infographic_options) > 2:
                        # URL is at [2][0][1][0] - image_data[0][1][0]
                        image_data = infographic_options[2]
                        if isinstance(image_data, list) and len(image_data) > 0:
                            first_image = image_data[0]
                            if isinstance(first_image, list) and len(first_image) > 1:
                                image_details = first_image[1]
                                if isinstance(image_details, list) and len(image_details) > 0:
                                    url = image_details[0]
                                    if isinstance(url, str) and url.startswith("http"):
                                        infographic_url = url

                # Slide deck artifacts have download URL at position 16
                slide_deck_url = None
                if type_code == self.STUDIO_TYPE_SLIDE_DECK and len(artifact_data) > 16:
                    slide_deck_options = artifact_data[16]
                    if isinstance(slide_deck_options, list) and len(slide_deck_options) > 0:
                        # URL is typically at position 0 in the options
                        if isinstance(slide_deck_options[0], str) and slide_deck_options[
                            0
                        ].startswith("http"):
                            slide_deck_url = slide_deck_options[0]
                        # Or may be nested deeper
                        elif len(slide_deck_options) > 3 and isinstance(slide_deck_options[3], str):
                            slide_deck_url = slide_deck_options[3]

                # Type-10 file exports expose metadata at position 24. The
                # MIME determines whether the export is an XLSX data table or
                # another generic file format.
                download_filename = None
                mime_type = None
                if type_code == self.STUDIO_TYPE_DATA_TABLE_XLSX and len(artifact_data) > 24:
                    file_metadata = artifact_data[24]
                    if isinstance(file_metadata, list):
                        if len(file_metadata) > 0 and isinstance(file_metadata[0], str):
                            download_filename = file_metadata[0]
                        if len(file_metadata) > 1 and isinstance(file_metadata[1], str):
                            mime_type = file_metadata[1]

                # Report artifacts have content at position 7
                report_content = None
                if type_code == self.STUDIO_TYPE_REPORT and len(artifact_data) > 7:
                    report_options = artifact_data[7]
                    if isinstance(report_options, list) and len(report_options) > 1:
                        # Content is nested in the options
                        content_data = (
                            report_options[1] if isinstance(report_options[1], list) else None
                        )
                        if content_data and len(content_data) > 0:
                            # Report content is typically markdown text
                            report_content = (
                                content_data[0] if isinstance(content_data[0], str) else None
                            )

                # Interactive reports (type 11) keep the prompt/language block
                # at index 34 and, once generated, the structured document that
                # we render back to markdown. The embedded element ids come from
                # the document's embed blocks.
                report_prompt = None
                report_language = None
                report_elements = None
                if type_code == self.STUDIO_TYPE_INTERACTIVE_REPORT:
                    options = interactive_report_options(artifact_data)
                    report_prompt = options["prompt"]
                    report_language = options["language"]
                    if interactive_report_document(artifact_data) is not None:
                        report_content = render_interactive_report_markdown(artifact_data)
                        report_elements = extract_interactive_report_elements(artifact_data)

                # Flashcard/Quiz/Mind Map artifacts share type code 4 and are
                # distinguished by options[1][0]:
                #   - Flashcards: 1
                #   - Quiz: 2
                #   - Mind Map: 4 (observed in live status payloads)
                flashcard_count = None
                is_quiz = False
                is_mind_map = False
                if type_code == self.STUDIO_TYPE_FLASHCARDS and len(artifact_data) > 9:
                    flashcard_options = artifact_data[9]
                    if isinstance(flashcard_options, list) and len(flashcard_options) > 1:
                        inner_options = flashcard_options[1]
                        if isinstance(inner_options, list) and len(inner_options) > 0:
                            # Check subtype code: 1=flashcards, 2=quiz, 4=mind map
                            format_code = inner_options[0]
                            if format_code == 2:
                                is_quiz = True
                            elif format_code == 4:
                                is_mind_map = True
                        # Count only genuine flashcard/quiz options. Mind-map
                        # metadata occupies the same position but is not cards.
                        if not is_mind_map:
                            cards_data = (
                                flashcard_options[1]
                                if isinstance(flashcard_options[1], list)
                                else None
                            )
                            if cards_data:
                                flashcard_count = (
                                    len(cards_data) if isinstance(cards_data, list) else None
                                )

                # Extract created_at timestamp
                # Position varies by type but often at position 10, 15, or similar
                created_at = None
                # Try common timestamp positions
                for ts_pos in [10, 15, 17]:
                    if len(artifact_data) > ts_pos:
                        ts_candidate = artifact_data[ts_pos]
                        if isinstance(ts_candidate, list) and len(ts_candidate) >= 2:  # noqa: SIM102
                            # Check if it looks like a timestamp [seconds, nanos]
                            if (
                                isinstance(ts_candidate[0], (int, float))
                                and ts_candidate[0] > 1700000000
                            ):
                                created_at = parse_timestamp(ts_candidate)
                                break

                # Map type codes to type names
                type_map = {
                    self.STUDIO_TYPE_AUDIO: "audio",
                    self.STUDIO_TYPE_REPORT: "report",
                    self.STUDIO_TYPE_VIDEO: "video",
                    self.STUDIO_TYPE_FLASHCARDS: "flashcards",  # Quiz also uses type 4, but detected via is_quiz
                    self.STUDIO_TYPE_INFOGRAPHIC: "infographic",
                    self.STUDIO_TYPE_SLIDE_DECK: "slide_deck",
                    self.STUDIO_TYPE_DATA_TABLE: "data_table",
                    self.STUDIO_TYPE_INTERACTIVE_REPORT: "interactive_report",
                }
                if is_mind_map:
                    artifact_type = "mind_map"
                elif is_quiz:
                    artifact_type = "quiz"
                elif type_code == self.STUDIO_TYPE_DATA_TABLE_XLSX:
                    artifact_type = (
                        "data_table_xlsx"
                        if mime_type
                        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        else "file"
                    )
                else:
                    artifact_type = type_map.get(cast(int, type_code), "unknown")
                status = self._normalize_studio_status(artifact_data)

                # Extract custom_instructions (focus prompt) if present
                # Different artifact types store prompts at different indices:
                # - Audio: artifact_data[6][1][0]
                # - Video: artifact_data[8][2][2] (focus), artifact_data[8][2][6] (style prompt)
                # - Slides: artifact_data[16][0][0]
                # - Quiz/Flashcards: artifact_data[9][1][1]
                custom_instructions = None
                visual_style_prompt = None
                source_ids = self._extract_artifact_source_ids(artifact_data, type_code)

                if type_code == self.STUDIO_TYPE_AUDIO and len(artifact_data) > 6:
                    options_data = artifact_data[6]
                    if isinstance(options_data, list) and len(options_data) > 1:
                        inner = options_data[1]
                        if isinstance(inner, list) and len(inner) > 0:  # noqa: SIM102
                            if isinstance(inner[0], str) and inner[0]:
                                custom_instructions = inner[0]

                elif type_code == self.STUDIO_TYPE_VIDEO and len(artifact_data) > 8:
                    options_data = artifact_data[8]
                    if isinstance(options_data, list) and len(options_data) > 2:
                        inner = options_data[2]
                        if isinstance(inner, list):
                            if len(inner) > 2 and isinstance(inner[2], str) and inner[2]:
                                custom_instructions = inner[2]
                            if len(inner) > 6 and isinstance(inner[6], str) and inner[6]:
                                visual_style_prompt = inner[6]

                elif type_code == self.STUDIO_TYPE_SLIDE_DECK and len(artifact_data) > 16:
                    options_data = artifact_data[16]
                    if isinstance(options_data, list) and len(options_data) > 0:
                        inner = options_data[0]
                        if isinstance(inner, list) and len(inner) > 0:  # noqa: SIM102
                            if isinstance(inner[0], str) and inner[0]:
                                custom_instructions = inner[0]

                elif type_code == self.STUDIO_TYPE_FLASHCARDS and len(artifact_data) > 9:
                    # Quiz and Flashcards both use type 4, stored at position 9
                    # Format: ['', [format_code, None, 'prompt_text', 'lang', ...]]
                    options_data = artifact_data[9]
                    if isinstance(options_data, list) and len(options_data) > 1:
                        inner = options_data[1]
                        if isinstance(inner, list) and len(inner) > 2:  # noqa: SIM102
                            if isinstance(inner[2], str) and inner[2]:
                                custom_instructions = inner[2].strip()  # Strip whitespace/newlines

                artifacts.append(
                    {
                        "artifact_id": artifact_id,
                        "title": title,
                        "type": artifact_type,
                        "status": status,
                        "created_at": created_at,
                        "custom_instructions": custom_instructions,
                        "source_ids": source_ids,
                        "visual_style_prompt": visual_style_prompt,
                        "audio_url": audio_url,
                        "video_url": video_url,
                        "infographic_url": infographic_url,
                        "slide_deck_url": slide_deck_url,
                        "download_filename": download_filename,
                        "mime_type": mime_type,
                        "report_content": report_content,
                        "report_prompt": report_prompt,
                        "report_language": report_language,
                        "report_elements": report_elements,
                        "flashcard_count": flashcard_count,
                        "duration_seconds": duration_seconds,
                    }
                )

        return artifacts

    def get_studio_status(self, notebook_id: str) -> list[dict[str, Any]]:
        """Alias for poll_studio_status (used by CLI)."""
        return self.poll_studio_status(notebook_id)

    def delete_studio_artifact(self, artifact_id: str, notebook_id: str | None = None) -> bool:
        """Delete a studio artifact (Audio, Video, or Mind Map).

        WARNING: This action is IRREVERSIBLE. The artifact will be permanently deleted.

        Args:
            artifact_id: The artifact UUID to delete
            notebook_id: Optional notebook ID. Required for deleting Mind Maps.

        Returns:
            True on success, False on failure
        """
        # 1. Try standard deletion (Audio, Video, etc.)
        try:
            params = [[2], artifact_id]
            result = self._call_rpc(self.RPC_DELETE_STUDIO, params)
            if result is not None:
                return True
        except Exception:
            # Continue to fallback if standard delete fails
            pass

        # 2. Fallback: Try Mind Map deletion if we have a notebook ID
        # Mind maps require a different RPC (AH0mwd) and payload structure
        if notebook_id:
            return self.delete_mind_map(notebook_id, artifact_id)

        return False

    def delete_mind_map(self, notebook_id: str, mind_map_id: str) -> bool:
        """Delete a Mind Map artifact using the observed two-step RPC sequence.

        Args:
            notebook_id: The notebook UUID.
            mind_map_id: The Mind Map artifact UUID.

        Returns:
            True on success
        """
        # 1. We need the artifact-specific timestamp from LIST_MIND_MAPS
        params = [notebook_id]
        list_result = self._call_rpc(self.RPC_LIST_MIND_MAPS, params, f"/notebook/{notebook_id}")

        timestamp = None
        if list_result and isinstance(list_result, list) and len(list_result) > 0:
            mm_list = list_result[0] if isinstance(list_result[0], list) else []
            for mm_entry in mm_list:
                if isinstance(mm_entry, list) and mm_entry[0] == mind_map_id:
                    # Based on debug output: item[1][2][2] contains [seconds, micros]
                    with contextlib.suppress(IndexError, TypeError):
                        timestamp = mm_entry[1][2][2]
                    break

        # 2. Step 1: UUID-based deletion (AH0mwd)
        params_v2 = [notebook_id, None, [mind_map_id], [2]]
        self._call_rpc(self.RPC_DELETE_MIND_MAP, params_v2, f"/notebook/{notebook_id}")

        # 3. Step 2: Timestamp-based sync/deletion (cFji9)
        # This is required to fully remove it from the list and avoid "ghosts"
        if timestamp:
            params_v1 = [notebook_id, None, timestamp, [2]]
            self._call_rpc(self.RPC_LIST_MIND_MAPS, params_v1, f"/notebook/{notebook_id}")

        return True

    def rename_studio_artifact(self, artifact_id: str, new_title: str) -> bool:
        """Rename a studio artifact (Audio, Video, Report, etc.).

        Args:
            artifact_id: The artifact UUID to rename
            new_title: The new title for the artifact

        Returns:
            True on success, False on failure
        """
        # Payload structure discovered via browser network intercept:
        # [[ "<artifact_id>", "<new_title>" ], [["title"]]]
        params = [[artifact_id, new_title], [["title"]]]

        try:
            result = self._call_rpc(self.RPC_RENAME_ARTIFACT, params)
            return result is not None
        except Exception:
            return False

    def revise_slide_deck(
        self,
        artifact_id: str,
        slide_instructions: list[tuple[int, str]],
    ) -> dict[str, Any] | None:
        """Revise an existing slide deck with per-slide instructions.

        Creates a NEW slide deck artifact with the requested changes applied.
        The original artifact is not modified.

        Args:
            artifact_id: UUID of the existing slide deck to revise
            slide_instructions: List of (0-based_index, instruction) tuples.
                Each tuple specifies which slide to change and how.

        Returns:
            Dict with new artifact_id, title, and status, or None on failure
        """
        # RPC KmcKPe params: [[2], artifact_id, [[[slide_index, instruction], ...]]]
        instruction_pairs = [[idx, text] for idx, text in slide_instructions]
        params = [[2], artifact_id, [instruction_pairs]]

        result = self._call_rpc(
            self.RPC_REVISE_SLIDE_DECK,
            params,
        )

        if result and isinstance(result, list) and len(result) > 0:
            artifact_data = result[0]
            if isinstance(artifact_data, list) and len(artifact_data) > 0:
                new_artifact_id = artifact_data[0]
                # Studio artifact payloads use index 1 for the title and index 2
                # for the artifact type code. Reuse the same layout as status polling.
                title = artifact_data[1] if len(artifact_data) > 1 else None

                return {
                    "artifact_id": new_artifact_id,
                    "title": title,
                    "original_artifact_id": artifact_id,
                    "status": self._normalize_studio_status(artifact_data),
                }

        return None

    def create_infographic(
        self,
        notebook_id: str,
        source_ids: list[str] | None = None,
        orientation_code: int = 1,  # INFOGRAPHIC_ORIENTATION_LANDSCAPE
        detail_level_code: int = 2,  # INFOGRAPHIC_DETAIL_STANDARD
        visual_style_code: int = 1,  # INFOGRAPHIC_STYLE_AUTO_SELECT
        language: str = "en",
        focus_prompt: str = "",
    ) -> dict[str, Any] | None:
        """Create an Infographic from notebook sources."""
        # Default to all sources if not specified
        if source_ids is None:
            source_ids = self._get_all_source_ids(notebook_id)

        if not source_ids:
            raise ValueError(
                f"No sources found in notebook {notebook_id}. Add sources before creating studio content."
            )

        # Build source IDs in the nested format: [[[id1]], [[id2]], ...]
        sources_nested = [[[sid]] for sid in source_ids]

        # Options at position 14: [[focus_prompt, language, null, orientation, detail_level, visual_style]]
        # Captured RPC structure: [[null, "en", null, 1, 2, 2]]
        infographic_options = [
            [
                focus_prompt or None,
                language,
                None,
                orientation_code,
                detail_level_code,
                visual_style_code,
            ]
        ]

        content = [
            None,
            None,
            self.STUDIO_TYPE_INFOGRAPHIC,
            sources_nested,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,  # 10 nulls (positions 4-13)
            infographic_options,  # position 14
        ]

        params = [[2], notebook_id, content]

        result = self._call_rpc(self.RPC_CREATE_STUDIO, params, f"/notebook/{notebook_id}")

        if result and isinstance(result, list) and len(result) > 0:
            artifact_data = result[0]
            artifact_id = (
                artifact_data[0]
                if isinstance(artifact_data, list) and len(artifact_data) > 0
                else None
            )

            return {
                "artifact_id": artifact_id,
                "notebook_id": notebook_id,
                "type": "infographic",
                "status": self._normalize_studio_status(artifact_data),
                "orientation": constants.INFOGRAPHIC_ORIENTATIONS.get_name(orientation_code),
                "detail_level": constants.INFOGRAPHIC_DETAILS.get_name(detail_level_code),
                "visual_style": constants.INFOGRAPHIC_STYLES.get_name(visual_style_code),
                "language": language,
            }

        return None

    def create_slide_deck(
        self,
        notebook_id: str,
        source_ids: list[str] | None = None,
        format_code: int = 1,  # SLIDE_DECK_FORMAT_DETAILED
        length_code: int = 3,  # SLIDE_DECK_LENGTH_DEFAULT
        language: str = "en",
        focus_prompt: str = "",
    ) -> dict[str, Any] | None:
        """Create a Slide Deck from notebook sources."""
        # Default to all sources if not specified
        if source_ids is None:
            source_ids = self._get_all_source_ids(notebook_id)

        if not source_ids:
            raise ValueError(
                f"No sources found in notebook {notebook_id}. Add sources before creating studio content."
            )

        # Build source IDs in the nested format: [[[id1]], [[id2]], ...]
        sources_nested = [[[sid]] for sid in source_ids]

        # Options at position 16: [[focus_prompt, language, format, length]]
        slide_deck_options = [[focus_prompt or None, language, format_code, length_code]]

        content = [
            None,
            None,
            self.STUDIO_TYPE_SLIDE_DECK,
            sources_nested,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,  # 12 nulls (positions 4-15)
            slide_deck_options,  # position 16
        ]

        params = [[2], notebook_id, content]

        result = self._call_rpc(self.RPC_CREATE_STUDIO, params, f"/notebook/{notebook_id}")

        if result and isinstance(result, list) and len(result) > 0:
            artifact_data = result[0]
            artifact_id = (
                artifact_data[0]
                if isinstance(artifact_data, list) and len(artifact_data) > 0
                else None
            )

            return {
                "artifact_id": artifact_id,
                "notebook_id": notebook_id,
                "type": "slide_deck",
                "status": self._normalize_studio_status(artifact_data),
                "format": constants.SLIDE_DECK_FORMATS.get_name(format_code),
                "length": constants.SLIDE_DECK_LENGTHS.get_name(length_code),
                "language": language,
            }

        return None

    def create_report(
        self,
        notebook_id: str,
        source_ids: list[str] | None = None,
        report_format: str = "Briefing Doc",
        custom_prompt: str = "",
        language: str = "en",
    ) -> dict[str, Any] | None:
        """Create a Report from notebook sources."""
        # Default to all sources if not specified
        if source_ids is None:
            source_ids = self._get_all_source_ids(notebook_id)

        if not source_ids:
            raise ValueError(
                f"No sources found in notebook {notebook_id}. Add sources before creating studio content."
            )

        # Build source IDs in the nested format: [[[id1]], [[id2]], ...]
        sources_nested = [[[sid]] for sid in source_ids]

        # Build source IDs in the simpler format: [[id1], [id2], ...]
        sources_simple = [[sid] for sid in source_ids]

        # Map report format to title, description, and prompt
        format_configs = {
            "Briefing Doc": {
                "title": "Briefing Doc",
                "description": "Key insights and important quotes",
                "prompt": (
                    "Create a comprehensive briefing document that includes an "
                    "Executive Summary, detailed analysis of key themes, important "
                    "quotes with context, and actionable insights."
                ),
            },
            "Study Guide": {
                "title": "Study Guide",
                "description": "Short-answer quiz, essay questions, glossary",
                "prompt": (
                    "Create a comprehensive study guide that includes key concepts, "
                    "short-answer practice questions, essay prompts for deeper "
                    "exploration, and a glossary of important terms."
                ),
            },
            "Blog Post": {
                "title": "Blog Post",
                "description": "Insightful takeaways in readable article format",
                "prompt": (
                    "Write an engaging blog post that presents the key insights "
                    "in an accessible, reader-friendly format. Include an attention-"
                    "grabbing introduction, well-organized sections, and a compelling "
                    "conclusion with takeaways."
                ),
            },
            "Create Your Own": {
                "title": "Custom Report",
                "description": "Custom format",
                "prompt": custom_prompt or "Create a report based on the provided sources.",
            },
        }

        if report_format not in format_configs:
            raise ValueError(
                f"Invalid report_format: {report_format}. "
                f"Must be one of: {list(format_configs.keys())}"
            )

        config = format_configs[report_format]

        # Options at position 7: [null, [title, desc, null, sources, lang, prompt, null, True]]
        report_options = [
            None,
            [
                config["title"],
                config["description"],
                None,
                sources_simple,
                language,
                config["prompt"],
                None,
                True,
            ],
        ]

        content = [
            None,
            None,
            self.STUDIO_TYPE_REPORT,
            sources_nested,
            None,
            None,
            None,
            report_options,
        ]

        params = [[2], notebook_id, content]

        result = self._call_rpc(self.RPC_CREATE_STUDIO, params, f"/notebook/{notebook_id}")

        if result and isinstance(result, list) and len(result) > 0:
            artifact_data = result[0]
            artifact_id = (
                artifact_data[0]
                if isinstance(artifact_data, list) and len(artifact_data) > 0
                else None
            )

            return {
                "artifact_id": artifact_id,
                "notebook_id": notebook_id,
                "type": "report",
                "status": self._normalize_studio_status(artifact_data),
                "format": report_format,
                "language": language,
            }

        return None

    def create_interactive_report(
        self,
        notebook_id: str,
        source_ids: list[str] | None = None,
        template: str = constants.DEFAULT_INTERACTIVE_REPORT_TEMPLATE,
        custom_prompt: str = "",
        language: str = "en",
    ) -> dict[str, Any] | None:
        """Create an Interactive Report (type 11) from notebook sources.

        Interactive reports are long-form reports that weave Studio outputs
        (a recommended mind map / infographic / flashcards / slide deck / quiz)
        into a single browsable document. The element placeholders are created
        automatically as *suggested* artifacts (status code 5); each one can be
        generated later via ``start_artifact_generation``.

        Payload layout discovered in the wild (``R7cb6c``, type 11):
        - config block: ``[2, null, null, [1, null x9, [<template>]], [<element types>]]``
        - content block: ``[null, null, 11, <sources>, null x30, [null, [prompt, language]]]``
          (the options block sits at index 34 instead of index 7 as with type 2)
        """
        if source_ids is None:
            source_ids = self._get_all_source_ids(notebook_id)

        if not source_ids:
            raise ValueError(
                f"No sources found in notebook {notebook_id}. Add sources before creating studio content."
            )

        template_code = constants.INTERACTIVE_REPORT_TEMPLATES.get_code(template)

        # Build source IDs in the nested format: [[[id1]], [[id2]], ...]
        sources_nested = [[[sid]] for sid in source_ids]

        # Config: [2, null, null, [1, null×9, [template_code]], [element types]]
        template_block: list[Any] = [1] + [None] * 9 + [[template_code]]
        config = [2, None, None, template_block, [list(constants.INTERACTIVE_REPORT_ELEMENT_TYPES)]]

        # Content: options (prompt/language) live at index 34 for type 11.
        content: list[Any] = [None, None, self.STUDIO_TYPE_INTERACTIVE_REPORT, sources_nested]
        content.extend([None] * 30)
        content.append([None, [custom_prompt, language]])

        params = [config, notebook_id, content]

        result = self._call_rpc(self.RPC_CREATE_STUDIO, params, f"/notebook/{notebook_id}")

        if result and isinstance(result, list) and len(result) > 0:
            artifact_data = result[0]
            artifact_id = (
                artifact_data[0]
                if isinstance(artifact_data, list) and len(artifact_data) > 0
                else None
            )

            return {
                "artifact_id": artifact_id,
                "notebook_id": notebook_id,
                "type": "interactive_report",
                "status": self._normalize_studio_status(artifact_data),
                "template": template,
                "language": language,
                "prompt": custom_prompt or None,
            }

        return None

    def get_artifact(self, notebook_id: str, artifact_id: str) -> list[Any] | None:
        """Fetch a single studio artifact by id (``v9rmvd``).

        Returns the raw artifact array (same layout as poll entries), which is
        also how interactive-report element metadata is read. The web client
        sends the same config block used at creation time plus a wider type
        allowlist; we mirror that.
        """
        config = [
            2,
            None,
            None,
            [1] + [None] * 9 + [[1]],
            [list(constants.INTERACTIVE_REPORT_GET_TYPES)],
        ]
        result = self._call_rpc(
            self.RPC_GET_ARTIFACT, [artifact_id, config], f"/notebook/{notebook_id}"
        )
        if result and isinstance(result, list) and len(result) > 0:
            first = result[0]
            if isinstance(first, list) and first and isinstance(first[0], str):
                return first
        return None

    def describe_artifact(self, notebook_id: str, artifact_id: str) -> dict[str, Any] | None:
        """Fetch one artifact by id and return a normalized description.

        Mirrors the per-artifact fields of ``poll_studio_status`` so services
        can work with a single artifact (in particular interactive reports and
        their suggested elements). Returns None when the artifact is missing.
        """
        raw = self.get_artifact(notebook_id, artifact_id)
        if raw is None:
            return None

        type_code = raw[2] if len(raw) > 2 else None
        info: dict[str, Any] = {
            "artifact_id": raw[0] if raw and isinstance(raw[0], str) else None,
            "title": raw[1] if len(raw) > 1 and isinstance(raw[1], str) else "",
            "type": classify_artifact_kind(raw),
            "status": self._normalize_studio_status(raw),
            "source_ids": self._extract_artifact_source_ids(raw, type_code),
            "steering_prompt": _artifact_steering_prompt(raw),
            "description": _artifact_card_description(raw),
        }

        if type_code == self.STUDIO_TYPE_INTERACTIVE_REPORT:
            options = interactive_report_options(raw)
            info["report_prompt"] = options["prompt"]
            info["report_language"] = options["language"]
            info["report_content"] = render_interactive_report_markdown(raw)
            info["report_elements"] = extract_interactive_report_elements(raw)
            info["report_sections"] = extract_report_sections(raw)
            info["parse_status"] = interactive_report_parse_status(raw)

        return info

    def start_artifact_generation(
        self,
        notebook_id: str,
        artifact_id: str,
        steering_prompt: str = "",
        language: str = "en",
        source_ids: list[str] | None = None,
        settings: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Generate a *suggested* artifact (e.g. an interactive-report element).

        Two-step flow observed in the web UI for every element kind ("Add" ->
        "Generate" on an element card):

        1. ``rc3d8d`` updates the artifact's generation options through a field
           mask (free-text steering prompt, language, structured options,
           sources). The mask and option block are kind-specific - see
           :func:`build_artifact_generation_payloads`.
        2. ``Rytqqe`` kicks the generation off (same config for every kind,
           ``[config, "<artifact id>"]``) and returns the refreshed artifact
           with the standard status codes (2 queued -> 1 in progress ->
           3 completed / 4 failed).
        """
        artifact = self.get_artifact(notebook_id, artifact_id)
        if artifact is None:
            raise ValueError(f"Artifact {artifact_id} not found in notebook {notebook_id}.")

        if source_ids is None:
            type_code = artifact[2] if len(artifact) > 2 else None
            source_ids = self._extract_artifact_source_ids(artifact, type_code)
        if not source_ids:
            # Never widen to every notebook source: the element must stay
            # scoped to its report's sources (callers pass them explicitly).
            raise ValueError(
                f"No sources available on artifact {artifact_id}; pass source_ids explicitly."
            )

        sources_nested = [[[sid]] for sid in source_ids]

        update, field_mask = build_artifact_generation_payloads(
            artifact,
            sources_nested,
            steering_prompt,
            language,
            settings=settings,
        )

        config = [
            2,
            None,
            None,
            [1] + [None] * 9 + [[1]],
            [list(constants.INTERACTIVE_REPORT_GET_TYPES)],
        ]

        self._call_rpc(
            self.RPC_SET_ARTIFACT_FIELDS,
            [update, field_mask, None, config],
            f"/notebook/{notebook_id}",
        )

        # The artifact id is passed as a plain string, not wrapped in a list;
        # a wrapped id is rejected with INVALID_ARGUMENT (verified 2026-09-24).
        kickoff_config = [
            2,
            None,
            None,
            [1] + [None] * 9 + [[1]],
            [list(constants.INTERACTIVE_REPORT_ELEMENT_TYPES)],
        ]
        import httpx  # local: only this path needs transport exception types

        try:
            result = self._call_rpc(
                self.RPC_START_ARTIFACT,
                [kickoff_config, artifact_id],
                f"/notebook/{notebook_id}",
                retry_server_errors=False,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise  # never delivered: a definite failure, safe to report as such
        except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
            raise KickoffOutcomeUnknownError(
                f"Kickoff response for {artifact_id} was lost: {e}"
            ) from e
        except httpx.TransportError as e:
            raise KickoffOutcomeUnknownError(
                f"Kickoff delivery for {artifact_id} is uncertain: {e}"
            ) from e

        if not (
            isinstance(result, list)
            and result
            and isinstance(result[0], list)
            and result[0]
            and isinstance(result[0][0], str)
        ):
            raise KickoffOutcomeUnknownError(
                f"Kickoff response for {artifact_id} was malformed: {str(result)[:200]}"
            )
        artifact_data = result[0]
        return {
            "artifact_id": artifact_data[0],
            "title": artifact_data[1] if len(artifact_data) > 1 else None,
            "type": classify_artifact_kind(artifact_data),
            "status": self._normalize_studio_status(artifact_data),
        }

    def create_flashcards(
        self,
        notebook_id: str,
        source_ids: list[str] | None = None,
        difficulty_code: int = 2,  # FLASHCARD_DIFFICULTY_MEDIUM
        focus_prompt: str = "",
    ) -> dict[str, Any] | None:
        """Create Flashcards from notebook sources."""
        # Default to all sources if not specified
        if source_ids is None:
            source_ids = self._get_all_source_ids(notebook_id)

        if not source_ids:
            raise ValueError(
                f"No sources found in notebook {notebook_id}. Add sources before creating studio content."
            )

        # Build source IDs in the nested format: [[[id1]], [[id2]], ...]
        sources_nested = [[[sid]] for sid in source_ids]

        # Card count code (default = 2)
        count_code = constants.FLASHCARD_COUNT_DEFAULT

        # Options at position 9: [null, [1, null, focus_prompt, null*3, [difficulty, card_count]]]
        flashcard_options = [
            None,
            [
                1,  # Unknown (possibly default count base)
                None,  # Reserved (must be null)
                focus_prompt or None,  # Focus prompt (index 2)
                None,
                None,
                None,
                [difficulty_code, count_code],
            ],
        ]

        content = [
            None,
            None,
            self.STUDIO_TYPE_FLASHCARDS,
            sources_nested,
            None,
            None,
            None,
            None,
            None,  # 5 nulls (positions 4-8)
            flashcard_options,  # position 9
        ]

        params = [[2], notebook_id, content]

        result = self._call_rpc(self.RPC_CREATE_STUDIO, params, f"/notebook/{notebook_id}")

        if result and isinstance(result, list) and len(result) > 0:
            artifact_data = result[0]
            artifact_id = (
                artifact_data[0]
                if isinstance(artifact_data, list) and len(artifact_data) > 0
                else None
            )

            return {
                "artifact_id": artifact_id,
                "notebook_id": notebook_id,
                "type": "flashcards",
                "status": self._normalize_studio_status(artifact_data),
                "difficulty": constants.FLASHCARD_DIFFICULTIES.get_name(difficulty_code),
            }

        return None

    def create_quiz(
        self,
        notebook_id: str,
        source_ids: list[str] | None = None,
        question_count: int = 2,
        difficulty: int = 2,
        focus_prompt: str = "",
    ) -> dict[str, Any] | None:
        """Create Quiz from notebook sources.

        Args:
            notebook_id: Notebook UUID
            source_ids: List of source UUIDs (defaults to all sources)
            question_count: Number of questions (default: 2)
            difficulty: Difficulty level (default: 2)
            focus_prompt: Optional focus prompt to guide quiz generation
        """
        # Default to all sources if not specified
        if source_ids is None:
            source_ids = self._get_all_source_ids(notebook_id)

        if not source_ids:
            raise ValueError(
                f"No sources found in notebook {notebook_id}. Add sources before creating studio content."
            )

        sources_nested = [[[sid]] for sid in source_ids]

        # Quiz options at position 9: [null, [2, null, focus_prompt, null*4, [question_count, difficulty]]]
        quiz_options = [
            None,
            [
                2,  # Format/variant code
                None,  # Reserved (must be null)
                focus_prompt or None,  # Focus prompt (index 2)
                None,
                None,
                None,
                None,
                [question_count, difficulty],
            ],
        ]

        content = [
            None,
            None,
            self.STUDIO_TYPE_FLASHCARDS,  # Type 4 (shared with flashcards)
            sources_nested,
            None,
            None,
            None,
            None,
            None,
            quiz_options,  # position 9
        ]

        params = [[2], notebook_id, content]

        result = self._call_rpc(self.RPC_CREATE_STUDIO, params, f"/notebook/{notebook_id}")

        if result and isinstance(result, list) and len(result) > 0:
            artifact_data = result[0]
            artifact_id = (
                artifact_data[0]
                if isinstance(artifact_data, list) and len(artifact_data) > 0
                else None
            )

            return {
                "artifact_id": artifact_id,
                "notebook_id": notebook_id,
                "type": "quiz",
                "status": self._normalize_studio_status(artifact_data),
                "question_count": question_count,
                "difficulty": constants.FLASHCARD_DIFFICULTIES.get_name(difficulty),
            }

        return None

    def create_data_table(
        self,
        notebook_id: str,
        source_ids: list[str] | None = None,
        description: str = "",
        language: str = "en",
    ) -> dict[str, Any] | None:
        """Create Data Table from notebook sources.

        Args:
            notebook_id: Notebook UUID
            source_ids: List of source UUIDs (defaults to all sources)
            description: Description of the data table to create
            language: Language code (default: "en")
        """
        # Default to all sources if not specified
        if source_ids is None:
            source_ids = self._get_all_source_ids(notebook_id)

        if not source_ids:
            raise ValueError(
                f"No sources found in notebook {notebook_id}. Add sources before creating studio content."
            )

        sources_nested = [[[sid]] for sid in source_ids]

        # Data Table options at position 18: [null, [description, language]]
        datatable_options = [None, [description, language]]

        content = [
            None,
            None,
            self.STUDIO_TYPE_DATA_TABLE,  # Type 9
            sources_nested,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,  # 14 nulls (positions 4-17)
            datatable_options,  # position 18
        ]

        params = [[2], notebook_id, content]

        result = self._call_rpc(self.RPC_CREATE_STUDIO, params, f"/notebook/{notebook_id}")

        if result and isinstance(result, list) and len(result) > 0:
            artifact_data = result[0]
            artifact_id = (
                artifact_data[0]
                if isinstance(artifact_data, list) and len(artifact_data) > 0
                else None
            )

            return {
                "artifact_id": artifact_id,
                "notebook_id": notebook_id,
                "type": "data_table",
                "status": self._normalize_studio_status(artifact_data),
                "description": description,
            }

        return None

    def generate_mind_map(
        self,
        notebook_id: str,
        source_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Generate a Mind Map JSON from sources.

        This is step 1 of 2 for creating a mind map. After generation,
        use save_mind_map() to save it to a notebook.

        BREAKING CHANGE (v0.2.3+):
            The signature changed from generate_mind_map(source_ids) to
            generate_mind_map(notebook_id, source_ids=None).

            Old usage: generate_mind_map(["source1", "source2"])
            New usage: generate_mind_map("notebook_id", ["source1", "source2"])

            If source_ids is None, all sources in the notebook will be used.

        Args:
            notebook_id: Notebook UUID (used to get sources if source_ids not provided)
            source_ids: List of source UUIDs to include (defaults to all sources)

        Returns:
            Dict with mind_map_json and generation_id, or None on failure

        Raises:
            ValueError: If no sources found in notebook
        """
        # Default to all sources if not specified
        if source_ids is None:
            source_ids = self._get_all_source_ids(notebook_id)

        if not source_ids:
            raise ValueError(
                f"No sources found in notebook {notebook_id}. Add sources before creating studio content."
            )

        # Build source IDs in the nested format: [[[id1]], [[id2]], ...]
        sources_nested = [[[sid]] for sid in source_ids]

        params = [
            sources_nested,
            None,
            None,
            None,
            None,
            ["interactive_mindmap", [["[CONTEXT]", ""]], ""],
            None,
            [2, None, [1]],
        ]

        result = self._call_rpc(self.RPC_GENERATE_MIND_MAP, params)

        if result and isinstance(result, list) and len(result) > 0:
            # Response is nested: [[json_string, null, [gen_ids]]]
            # So result[0] is [json_string, null, [gen_ids]]
            inner = result[0] if isinstance(result[0], list) else result

            mind_map_json = inner[0] if isinstance(inner[0], str) else None
            generation_info = inner[2] if len(inner) > 2 else None

            generation_id = None
            if isinstance(generation_info, list) and len(generation_info) > 0:
                generation_id = generation_info[0]

            return {
                "mind_map_json": mind_map_json,
                "generation_id": generation_id,
                "source_ids": source_ids,
            }

        return None

    def save_mind_map(
        self,
        notebook_id: str,
        mind_map_json: str,
        source_ids: list[str] | None = None,
        title: str = "Mind Map",
    ) -> dict[str, Any] | None:
        """Save a generated Mind Map to a notebook.

        This is step 2 of 2 for creating a mind map. First use
        generate_mind_map() to create the JSON structure.

        Args:
            notebook_id: The notebook UUID
            mind_map_json: The JSON string from generate_mind_map()
            source_ids: List of source UUIDs used to generate the map (defaults to all sources)
            title: Display title for the mind map

        Returns:
            Dict with mind_map_id and saved info, or None on failure
        """
        # Default to all sources if not specified
        if source_ids is None:
            source_ids = self._get_all_source_ids(notebook_id)

        if not source_ids:
            raise ValueError(
                f"No sources found in notebook {notebook_id}. Add sources before creating studio content."
            )

        # Build source IDs in the simpler format: [[id1], [id2], ...]
        sources_simple = [[sid] for sid in source_ids]

        metadata = [2, None, None, 5, sources_simple]

        params = [notebook_id, mind_map_json, metadata, None, title]

        result = self._call_rpc(self.RPC_SAVE_MIND_MAP, params, f"/notebook/{notebook_id}")

        if result and isinstance(result, list) and len(result) > 0:
            # Response is nested: [[mind_map_id, json, metadata, null, title]]
            inner = result[0] if isinstance(result[0], list) else result

            mind_map_id = inner[0] if len(inner) > 0 else None
            saved_json = inner[1] if len(inner) > 1 else None
            saved_title = inner[4] if len(inner) > 4 else title

            return {
                "mind_map_id": mind_map_id,
                "notebook_id": notebook_id,
                "title": saved_title,
                "mind_map_json": saved_json,
            }

        return None

    def list_mind_maps(self, notebook_id: str) -> list[dict[str, Any]]:
        """List all Mind Maps in a notebook."""
        params = [notebook_id]

        result = self._call_rpc(self.RPC_LIST_MIND_MAPS, params, f"/notebook/{notebook_id}")

        mind_maps = []
        if result and isinstance(result, list) and len(result) > 0:
            mind_map_list = result[0] if isinstance(result[0], list) else []

            for mind_map_data in mind_map_list:
                # Skip invalid or tombstone entries (deleted entries have details=None)
                # Tombstone format: [uuid, null, 2]
                if not isinstance(mind_map_data, list) or len(mind_map_data) < 2:
                    continue

                details = mind_map_data[1]
                if details is None:
                    # This is a tombstone/deleted entry, skip it
                    continue

                mind_map_id = mind_map_data[0]

                if isinstance(details, list) and len(details) >= 5:
                    # Details: [id, json, metadata, null, title]
                    mind_map_json = details[1] if len(details) > 1 else None
                    title = details[4] if len(details) > 4 else "Mind Map"
                    metadata = details[2] if len(details) > 2 else []

                    # The notes store holds both regular notes (prose content)
                    # and mind maps (JSON content) — keep only real mind maps,
                    # mirroring the inverse filter in NotesMixin.list_notes.
                    if not is_mind_map_json(mind_map_json):
                        continue

                    created_at = None
                    if isinstance(metadata, list) and len(metadata) > 2:
                        ts = metadata[2]
                        created_at = parse_timestamp(ts)

                    mind_maps.append(
                        {
                            "mind_map_id": mind_map_id,
                            "title": title,
                            "mind_map_json": mind_map_json,
                            "created_at": created_at,
                        }
                    )

        return mind_maps


# =============================================================================
# Interactive report helpers (STUDIO_TYPE_INTERACTIVE_REPORT = 11)
#
# An interactive report artifact carries its options at index 34 instead of
# index 7:  ``[<document or null>, [<prompt>, <language>, <generated?>]]``.
# Once generated, ``document`` is a one-element wrapper around a flat list of
# blocks: headings, paragraphs (with character-offset spans), bullet items and
# embed blocks that reference the suggested Studio elements.
# =============================================================================


def interactive_report_options(artifact_data: Any) -> dict[str, Any]:
    """Extract prompt/language/generation flag from an interactive report artifact."""
    out: dict[str, Any] = {"prompt": None, "language": None, "generated": None}
    if not isinstance(artifact_data, list) or len(artifact_data) <= 34:
        return out
    options = artifact_data[34]
    if not isinstance(options, list) or len(options) <= 1:
        return out
    inner = options[1]
    if not isinstance(inner, list):
        return out
    if len(inner) > 0 and isinstance(inner[0], str):
        out["prompt"] = inner[0] or None
    if len(inner) > 1 and isinstance(inner[1], str):
        out["language"] = inner[1] or None
    if len(inner) > 2 and inner[2] is not None:
        out["generated"] = bool(inner[2])
    return out


def interactive_report_document(artifact_data: Any) -> list[Any] | None:
    """Return the flat block list of a generated interactive report, or None."""
    if not isinstance(artifact_data, list) or len(artifact_data) <= 34:
        return None
    options = artifact_data[34]
    if not isinstance(options, list) or not options:
        return None
    wrapper = options[0]
    # Layout: [[<blocks>]] -> options[0][0][0] is the flat block list.
    if (
        isinstance(wrapper, list)
        and wrapper
        and isinstance(wrapper[0], list)
        and wrapper[0]
        and isinstance(wrapper[0][0], list)
    ):
        blocks = wrapper[0][0]
        if blocks and all(isinstance(b, list) for b in blocks):
            return blocks
    return None


def _is_embed_block(block: Any) -> bool:
    """Embed blocks look like ``[null x12, [<element_id>, <flag>], ...]``.

    Extra trailing fields are tolerated so a new Google field does not make
    every element silently disappear.
    """
    return (
        isinstance(block, list)
        and len(block) >= 13
        and all(item is None for item in block[:12])
        and isinstance(block[12], list)
        and len(block[12]) >= 1
        and isinstance(block[12][0], str)
    )


def extract_interactive_report_elements(artifact_data: Any) -> list[dict[str, Any]]:
    """Return the embedded element references carried by an interactive report.

    Each entry: ``{"element_id": str, "flag": int|None, "block_index": int}``.
    The elements themselves are *suggested* artifacts (status 5) that can be
    generated via ``start_artifact_generation``.
    """
    blocks = interactive_report_document(artifact_data)
    if not blocks:
        return []
    elements: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        if _is_embed_block(block):
            elements.append(
                {
                    "element_id": block[12][0],
                    "flag": block[12][1] if len(block[12]) > 1 else None,
                    "block_index": index,
                }
            )
    return elements


def _is_heading_block(block: list[Any]) -> bool:
    return block[0] is None and (len(block) < 2 or block[1] is None) and not _is_embed_block(block)


def extract_report_sections(artifact_data: Any) -> dict[str, dict[str, str] | None]:
    """Map each embedded element id to the section it sits in.

    A section is the nearest preceding heading plus the paragraph and bullet
    text between that heading and the element. Elements before any heading
    map to ``None`` so callers never anchor a prompt to guessed text.
    """
    blocks = interactive_report_document(artifact_data)
    if not blocks:
        return {}
    sections: dict[str, dict[str, str] | None] = {}
    heading: str | None = None
    texts: list[str] = []
    for block in blocks:
        if not isinstance(block, list) or not block:
            continue
        if _is_embed_block(block):
            sections[block[12][0]] = (
                {"heading": heading, "text": "\n".join(t for t in texts if t)}
                if heading is not None
                else None
            )
            continue
        if _is_heading_block(block):
            heading = _first_string(block[2] if len(block) > 2 else None)
            texts = []
            continue
        if isinstance(block[0], int):
            texts.append(_report_block_text(block))
    return sections


def interactive_report_parse_status(artifact_data: Any) -> str:
    """Classify how well the report document was understood.

    ``pending``: no document yet. ``unrecognized``: a document is present but
    its structure is not understood. ``empty``: understood, no embeds.
    ``ok``: understood with at least one embedded element.
    """
    if not isinstance(artifact_data, list) or len(artifact_data) <= 34:
        return "pending"
    options = artifact_data[34]
    if not isinstance(options, list) or not options or options[0] is None:
        return "pending"
    if interactive_report_document(artifact_data) is None:
        return "unrecognized"
    return "ok" if extract_interactive_report_elements(artifact_data) else "empty"


def _report_span_text(span: Any) -> str:
    """Render one text span. A single-element ``[true]`` attribute means bold."""
    if not (isinstance(span, list) and len(span) >= 3 and isinstance(span[2], list)):
        return ""
    parts = span[2]
    if not parts or not isinstance(parts[0], str):
        return ""
    text = parts[0]
    attrs = parts[1] if len(parts) > 1 else None
    if attrs == [True]:
        return f"**{text}**"
    return text


def _report_block_text(block: list[Any]) -> str:
    """Concatenate the text spans of a paragraph or bullet block."""
    groups = block[2] if len(block) > 2 else None
    if not isinstance(groups, list):
        return ""
    pieces: list[str] = []
    for group in groups:
        spans = group if isinstance(group, list) else [group]
        for span in spans:
            pieces.append(_report_span_text(span))
    return "".join(pieces)


def _report_bullet_meta(block: list[Any]) -> dict[str, Any] | None:
    """Return the bullet metadata dict of a list-item block, if present.

    Bullet blocks carry their marker at ``block[2][3]``:
    ``[null, null, 0, {"101": "•", "102": 1, "103": <index>, "104": <level>}]``.
    """
    if len(block) <= 2 or not isinstance(block[2], list) or len(block[2]) <= 3:
        return None
    candidate = block[2][3]
    if (
        isinstance(candidate, list)
        and len(candidate) > 3
        and isinstance(candidate[3], dict)
        and "101" in candidate[3]
    ):
        return candidate[3]
    return None


def _first_string(node: Any) -> str | None:
    """Return the first string inside a nested list structure (heading titles)."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        for item in node:
            found = _first_string(item)
            if found is not None:
                return found
    return None


def render_interactive_report_markdown(artifact_data: Any) -> str | None:
    """Render an interactive report document to Markdown.

    Faithful-but-simple: section headings become ``##``, bullet levels map to
    indentation, bold spans keep their weight, and embedded Studio elements are
    rendered as ``[Embedded element: <id>]`` placeholders (enrich them with
    ``get_artifact`` for titles/types).
    """
    blocks = interactive_report_document(artifact_data)
    if not blocks:
        return None

    lines: list[str] = []
    for block in blocks:
        if not isinstance(block, list) or not block:
            continue

        if _is_embed_block(block):
            lines.append("")
            lines.append(f"[Embedded element: {block[12][0]}]")
            lines.append("")
            continue

        # Heading blocks start with [null, null, ...]
        if _is_heading_block(block):
            title = _first_string(block[2] if len(block) > 2 else None)
            if title:
                lines.append("")
                lines.append(f"## {title}")
                lines.append("")
            continue

        if isinstance(block[0], int):
            text = _report_block_text(block)
            if not text:
                continue
            bullet_meta = _report_bullet_meta(block)
            if bullet_meta is not None:
                # {"101": bullet char, "102": ?, "103": item index, "104": running
                # counter}. The web UI renders all observed lists flat, so keep
                # a flat "- " marker (nested-list rendering is unverified).
                lines.append(f"- {text}")
            else:
                lines.append(text)
                lines.append("")

    markdown = "\n".join(lines).strip()
    return markdown + "\n" if markdown else ""


def classify_artifact_kind(artifact_data: Any) -> str:
    """Best-effort human type label for a raw artifact array."""
    if not isinstance(artifact_data, list) or len(artifact_data) < 3:
        return "unknown"

    type_code = artifact_data[2]
    subtype = None
    if len(artifact_data) > 9:
        options = artifact_data[9]
        if (
            isinstance(options, list)
            and len(options) > 1
            and isinstance(options[1], list)
            and options[1]
        ):
            subtype = options[1][0]

    if type_code == constants.STUDIO_TYPE_FLASHCARDS:
        if subtype == 2:
            return "quiz"
        if subtype == 4:
            return "mind_map"
        if subtype in (None, 1):
            return "flashcards"
        return "unsupported"

    return {
        constants.STUDIO_TYPE_AUDIO: "audio",
        constants.STUDIO_TYPE_REPORT: "report",
        constants.STUDIO_TYPE_VIDEO: "video",
        constants.STUDIO_TYPE_INFOGRAPHIC: "infographic",
        constants.STUDIO_TYPE_SLIDE_DECK: "slide_deck",
        constants.STUDIO_TYPE_DATA_TABLE: "data_table",
        constants.STUDIO_TYPE_INTERACTIVE_REPORT: "interactive_report",
    }.get(type_code, "unknown")


# Field masks for element generation, captured live from the report UI for
# each recommended element kind. The sparse update arrays only set the fields
# named by the mask; everything else stays null.
_APP_OPTIONS_MASK = [
    "app.generation_options.free_text_steering_prompt",
    "app.generation_options.language_code",
    "sources",
]
_QUIZ_OPTIONS_MASK = [
    "app.generation_options.free_text_steering_prompt",
    "app.generation_options.language_code",
    "app.generation_options.quiz_generation_options.question_quantity",
    "app.generation_options.quiz_generation_options.quiz_difficulty",
    "sources",
]
_FLASHCARD_OPTIONS_MASK = [
    "app.generation_options.free_text_steering_prompt",
    "app.generation_options.language_code",
    "app.generation_options.flashcards_generation_options.card_quantity",
    "app.generation_options.flashcards_generation_options.flashcards_difficulty",
    "sources",
]
_INFOGRAPHIC_OPTIONS_MASK = [
    "infographic.generation_options.user_steering_prompt",
    "infographic.generation_options.language_code",
    "infographic.generation_options.aspect_ratio",
    "infographic.generation_options.information_density",
    "infographic.generation_options.style",
    "sources",
]
_SLIDES_OPTIONS_MASK = [
    "slides.generation_options.user_steering_prompt",
    "slides.generation_options.language_code",
    "slides.generation_options.deck_type",
    "slides.generation_options.length",
    "sources",
]
_AUDIO_OPTIONS_MASK = [
    "audio_overview.generation_options.episode_focus",
    "audio_overview.generation_options.episode_length",
    "audio_overview.generation_options.language_code",
    "audio_overview.generation_options.show_format",
    "sources",
]
_VIDEO_SHORT_OPTIONS_MASK = [
    "explainer_video.generation_options.language_code",
    "explainer_video.generation_options.video_focus",
    "explainer_video.generation_options.template_format",
    "sources",
]
_VIDEO_OPTIONS_MASK = [
    "explainer_video.generation_options.language_code",
    "explainer_video.generation_options.video_focus",
    "explainer_video.generation_options.template_format",
    "explainer_video.generation_options.video_overview_style",
    "sources",
]


def build_artifact_generation_payloads(
    artifact: list[Any],
    sources_nested: list[Any],
    steering_prompt: str,
    language: str,
    settings: dict[str, int] | None = None,
) -> tuple[list[Any], list[list[str]]]:
    """Build the (sparse update, field mask) pair for one suggested artifact.

    ``settings`` holds resolved codes (see services.interactive_reports);
    missing keys fall back to the web UI's plain-Generate defaults.
    Audio and video use the Customize mask with the fixed values the page
    sends (episode length 2, video style 1); neither is user-settable. Short
    videos are the exception: the page sends them without the style field.
    """
    s = settings or {}
    type_code = artifact[2] if isinstance(artifact, list) and len(artifact) > 2 else None
    subtype = None
    if (
        isinstance(artifact, list)
        and len(artifact) > 9
        and isinstance(artifact[9], list)
        and len(artifact[9]) > 1
        and isinstance(artifact[9][1], list)
        and artifact[9][1]
    ):
        subtype = artifact[9][1][0]

    artifact_id = artifact[0]
    prompt = steering_prompt or None

    if type_code == constants.STUDIO_TYPE_AUDIO:
        update: list[Any] = [artifact_id, None, None, sources_nested] + [None] * 2
        update.append([None, [prompt, 2, None, None, language, None, s.get("audio_format", 2)]])
        return update, [_AUDIO_OPTIONS_MASK]

    if type_code == constants.STUDIO_TYPE_VIDEO:
        update = [artifact_id, None, None, sources_nested] + [None] * 4
        video_format = s.get("video_format", 3)
        if video_format == constants.VIDEO_FORMAT_SHORT:
            # The page sends Short without the style field and its mask.
            update.append([None, None, [None, language, prompt, None, video_format]])
            return update, [_VIDEO_SHORT_OPTIONS_MASK]
        update.append([None, None, [None, language, prompt, None, video_format, 1]])
        return update, [_VIDEO_OPTIONS_MASK]

    if type_code == constants.STUDIO_TYPE_INFOGRAPHIC:
        update = [artifact_id, None, None, sources_nested] + [None] * 10
        update.append(
            [
                [
                    prompt,
                    language,
                    None,
                    s.get("orientation", 1),
                    s.get("detail_level", 2),
                    s.get("infographic_style", 1),
                ]
            ]
        )
        return update, [_INFOGRAPHIC_OPTIONS_MASK]

    if type_code == constants.STUDIO_TYPE_SLIDE_DECK:
        update = [artifact_id, None, None, sources_nested] + [None] * 12
        update.append([[prompt, language, s.get("slide_format", 1), s.get("slide_length", 3)]])
        return update, [_SLIDES_OPTIONS_MASK]

    if subtype == 4:
        update = [artifact_id, None, None, sources_nested] + [None] * 5
        update.append([None, [4, None, prompt, language]])
        return update, [_APP_OPTIONS_MASK]

    if subtype == 2:
        update = [artifact_id, None, None, sources_nested] + [None] * 5
        update.append(
            [
                None,
                [
                    2,
                    None,
                    prompt,
                    language,
                    None,
                    None,
                    None,
                    [s.get("amount", 2), s.get("difficulty", 2)],
                ],
            ]
        )
        return update, [_QUIZ_OPTIONS_MASK]

    if subtype == 1:
        update = [artifact_id, None, None, sources_nested] + [None] * 5
        update.append(
            [
                None,
                [
                    1,
                    None,
                    prompt,
                    language,
                    None,
                    None,
                    [s.get("amount", 1), s.get("difficulty", 2)],
                ],
            ]
        )
        return update, [_FLASHCARD_OPTIONS_MASK]

    update = [artifact_id, None, None, sources_nested] + [None] * 5
    update.append([None, [subtype, None, prompt, language]])
    return update, [_APP_OPTIONS_MASK]


def _artifact_card_description(artifact_data: Any) -> str | None:
    """Return the recommendation text of a suggested element card.

    Suggested artifacts carry ``[title, description]`` at index 35; the web UI
    shows the description on the card and sends it as the steering prompt
    when the user clicks Generate without customizing.
    """
    if not isinstance(artifact_data, list) or len(artifact_data) <= 35:
        return None
    card = artifact_data[35]
    if isinstance(card, list) and len(card) > 1 and isinstance(card[1], str):
        return card[1].strip() or None
    return None


def _artifact_steering_prompt(artifact_data: Any) -> str | None:
    """Best-effort extraction of an artifact's steering/focus prompt.

    Positions mirror the per-type reads in ``poll_studio_status``:
    - options[1][2] for the type-4 family (flashcards / quiz / mind map)
    - options[0][0] for slide decks
    - options[1][0] for audio, options[2][2] for video
    """
    if not isinstance(artifact_data, list) or len(artifact_data) < 3:
        return None
    type_code = artifact_data[2]

    def _inner(options_index: int, path: tuple[int, ...]) -> str | None:
        if len(artifact_data) <= options_index:
            return None
        node: Any = artifact_data[options_index]
        for step in path:
            if isinstance(node, list) and len(node) > step:
                node = node[step]
            else:
                return None
        return node.strip() if isinstance(node, str) and node.strip() else None

    if type_code == constants.STUDIO_TYPE_FLASHCARDS:
        return _inner(9, (1, 2))
    if type_code == constants.STUDIO_TYPE_SLIDE_DECK:
        return _inner(16, (0, 0))
    if type_code == constants.STUDIO_TYPE_AUDIO:
        return _inner(6, (1, 0))
    if type_code == constants.STUDIO_TYPE_VIDEO:
        return _inner(8, (2, 2))
    return None
