import pytest
from playwright.async_api import async_playwright

from playwright_recaptcha import (
    RecaptchaTimeoutError,
    RecaptchaVersionError,
    recaptchav3,
)


@pytest.mark.asyncio
async def test_solver() -> None:
    """Test the solver with a normal browser."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        await page.goto("https://antcpt.com/score_detector/")

        async with recaptchav3.AsyncSolver(page) as solver:
            token = await solver.solve_recaptcha()
            assert token is not None


@pytest.mark.asyncio
async def test_solver_with_slow_browser() -> None:
    """Test the solver with a slow browser."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(slow_mo=1000)
        page = await browser.new_page()
        await page.goto("https://antcpt.com/score_detector/")

        async with recaptchav3.AsyncSolver(page) as solver:
            token = await solver.solve_recaptcha()
            assert token is not None


@pytest.mark.asyncio
async def test_recaptcha_not_found() -> None:
    """Test the solver with a page that does not have a reCAPTCHA."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        await page.goto("https://www.google.com/")

        with pytest.raises(RecaptchaTimeoutError):
            async with recaptchav3.AsyncSolver(page, timeout=10) as solver:
                await solver.solve_recaptcha()


@pytest.mark.asyncio
async def test_recaptcha_version_error() -> None:
    """Test the solver with a page that has a reCAPTCHA v2."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        await page.goto("https://cobra.ehr.com/ESS/Home/Login.aspx")

        with pytest.raises(RecaptchaVersionError):
            async with recaptchav3.AsyncSolver(page) as solver:
                await solver.solve_recaptcha()
