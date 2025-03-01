from __future__ import annotations

import io
import random
import re
from typing import Any, Optional

import httpx
import pydub
import speech_recognition
from playwright.sync_api import Frame, Locator, Page, Response

from playwright_recaptcha.errors import RecaptchaRateLimitError, RecaptchaSolveError
from playwright_recaptcha.recaptchav2.utils import (
    get_recaptcha_checkbox,
    get_recaptcha_frame,
)


class SyncSolver:
    """
    A class used to solve reCAPTCHA v2 synchronously.

    Parameters
    ----------
    page : Page
        The playwright page to solve the reCAPTCHA on.
    retries : int, optional
        The number of retries, by default 3.

    Attributes
    ----------
    token : Optional[str]
        The reCAPTCHA token.

    Methods
    -------
    close() -> None
        Remove the userverify response listener.
    solve_recaptcha(retries: Optional[int] = None) -> str
        Solve the reCAPTCHA and return the token.

    Raises
    ------
    RecaptchaNotFoundError
        If the reCAPTCHA was not found.
    RecaptchaRateLimitError
        If the reCAPTCHA rate limit has been reached.
    RecaptchaSolveError
        If the reCAPTCHA could not be solved.
    """

    def __init__(self, page: Page, retries: int = 3) -> None:
        self._page = page
        self._retries = retries
        self.token = None

    def __repr__(self) -> str:
        return f"SyncSolver(page={self._page!r}, retries={self._retries!r})"

    def __enter__(self) -> SyncSolver:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _random_delay(self) -> None:
        """Delay the execution for a random amount of time between 1 and 4 seconds."""
        self._page.wait_for_timeout(random.randint(1, 4) * 1000)

    def _extract_token(self, response: Response) -> None:
        """
        Extract the reCAPTCHA token from the userverify response.

        Parameters
        ----------
        response : Response
            The response to extract the token from.
        """
        if re.search("/recaptcha/(api2|enterprise)/userverify", response.url) is None:
            return

        token_match = re.search(r'"uvresp","(.*?)"', response.text())

        if token_match is not None:
            self.token = token_match.group(1)

    def _get_audio_url(self, recaptcha_frame: Frame) -> str:
        """
        Get the reCAPTCHA audio URL.

        Parameters
        ----------
        recaptcha_frame : Frame
            The reCAPTCHA frame.

        Returns
        -------
        str
            The reCAPTCHA audio URL.

        Raises
        ------
        RecaptchaRateLimitError
            If the reCAPTCHA rate limit has been reached.
        """
        audio_challenge_button = recaptcha_frame.get_by_role(
            "button", name="Get an audio challenge"
        )

        if audio_challenge_button.is_visible():
            audio_challenge_button.click()

        while True:
            if recaptcha_frame.get_by_text("Press PLAY to listen").is_visible():
                break

            if recaptcha_frame.get_by_text("Try again later").is_visible():
                raise RecaptchaRateLimitError

            self._page.wait_for_timeout(100)

        return recaptcha_frame.get_by_role(
            "link", name="Alternatively, download audio as MP3"
        ).get_attribute("href")

    @staticmethod
    def _convert_audio_to_text(audio_url: str) -> str:
        """
        Convert the reCAPTCHA audio to text.

        Parameters
        ----------
        audio_url : str
            The reCAPTCHA audio URL.

        Returns
        -------
        str
            The reCAPTCHA audio text.
        """
        response = httpx.get(audio_url)

        wav_audio = io.BytesIO()
        mp3_audio = io.BytesIO(response.content)
        audio = pydub.AudioSegment.from_mp3(mp3_audio)
        audio.export(wav_audio, format="wav")

        recognizer = speech_recognition.Recognizer()

        with speech_recognition.AudioFile(wav_audio) as source:
            audio_data = recognizer.record(source)

        text = recognizer.recognize_google(audio_data, show_all=True)
        return text["alternative"][0]["transcript"]

    def _submit_audio_text(
        self, recaptcha_frame: Frame, recaptcha_checkbox: Locator, text: str
    ) -> None:
        """
        Submit the reCAPTCHA audio text.

        Parameters
        ----------
        recaptcha_frame : Frame
            The reCAPTCHA frame.
        recaptcha_checkbox : Locator
            The reCAPTCHA checkbox.
        text : str
            The reCAPTCHA audio text.

        Raises
        ------
        RecaptchaRateLimitError
            If the reCAPTCHA rate limit has been reached.
        """
        recaptcha_frame.get_by_role("textbox", name="Enter what you hear").fill(text)
        recaptcha_frame.get_by_role("button", name="Verify").click()

        while True:
            if (
                recaptcha_frame.get_by_text(
                    "Multiple correct solutions required - please solve more."
                ).is_visible()
                or recaptcha_checkbox.is_checked()
            ):
                break

            if recaptcha_frame.get_by_text("Try again later").is_visible():
                raise RecaptchaRateLimitError

            self._page.wait_for_timeout(100)

    def close(self) -> None:
        """Remove the userverify response listener."""
        try:
            self._page.remove_listener("response", self._extract_token)
        except KeyError:
            pass

    def solve_recaptcha(self, retries: Optional[int] = None) -> str:
        """
        Solve the reCAPTCHA and return the token.

        Parameters
        ----------
        retries : Optional[int], optional
            The number of retries, by default None

        Returns
        -------
        str
            The reCAPTCHA token.

        Raises
        ------
        RecapchaSolveError
            If the reCAPTCHA could not be solved.
        """
        self._page.on("response", self._extract_token)
        retries = retries or self._retries

        self._page.wait_for_load_state("networkidle")
        recaptcha_frame = get_recaptcha_frame(self._page.frames)
        recaptcha_checkbox = get_recaptcha_checkbox(self._page.frames)
        recaptcha_checkbox.click()

        if recaptcha_checkbox.is_checked():
            return self.token

        while retries > 0:
            self._random_delay()
            url = self._get_audio_url(recaptcha_frame)
            text = self._convert_audio_to_text(url)
            self._random_delay()
            self._submit_audio_text(recaptcha_frame, recaptcha_checkbox, text)

            if recaptcha_checkbox.is_checked():
                break

            recaptcha_frame.get_by_role("button", name="Get a new challenge").click()
            retries -= 1

        if not recaptcha_checkbox.is_checked():
            raise RecaptchaSolveError

        return self.token
