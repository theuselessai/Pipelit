"""Browser tools for the browser agent."""
import os
import subprocess
import tempfile

from langchain_core.tools import tool

from app.config import settings


@tool
def navigate_to_url(url: str) -> str:
    """Navigate to a URL in the browser and return the page title and text content."""
    try:
        from playwright.sync_api import sync_playwright

        headless = settings.BROWSER_HEADLESS
        profile_path = os.path.expanduser(settings.CHROME_PROFILE_PATH)

        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                profile_path,
                headless=headless,
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            title = page.title()
            text = page.inner_text("body")[:5000]
            browser.close()
            return f"Title: {title}\n\nContent:\n{text}"
    except ImportError:
        return "Error: playwright is not installed. Run: pip install playwright && playwright install chromium"
    except Exception as e:
        return f"Error navigating to {url}: {e}"


@tool
def take_screenshot(url: str = "") -> str:
    """Take a screenshot of the current page or a URL. Returns the file path of the screenshot."""
    try:
        from playwright.sync_api import sync_playwright

        headless = settings.BROWSER_HEADLESS
        profile_path = os.path.expanduser(settings.CHROME_PROFILE_PATH)
        screenshot_path = os.path.join(tempfile.gettempdir(), "screenshot.png")

        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                profile_path,
                headless=headless,
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            if url:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.screenshot(path=screenshot_path, full_page=False)
            browser.close()
            return f"[IMAGE:{screenshot_path}]"
    except ImportError:
        return "Error: playwright is not installed. Run: pip install playwright && playwright install chromium"
    except Exception as e:
        return f"Error taking screenshot: {e}"


@tool
def click_element(selector: str) -> str:
    """Click an element on the current page by CSS selector."""
    try:
        from playwright.sync_api import sync_playwright

        headless = settings.BROWSER_HEADLESS
        profile_path = os.path.expanduser(settings.CHROME_PROFILE_PATH)

        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                profile_path,
                headless=headless,
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.click(selector, timeout=10000)
            title = page.title()
            browser.close()
            return f"Clicked '{selector}'. Page title: {title}"
    except ImportError:
        return "Error: playwright is not installed."
    except Exception as e:
        return f"Error clicking element: {e}"


@tool
def type_text(selector: str, text: str) -> str:
    """Type text into an element on the current page by CSS selector."""
    try:
        from playwright.sync_api import sync_playwright

        headless = settings.BROWSER_HEADLESS
        profile_path = os.path.expanduser(settings.CHROME_PROFILE_PATH)

        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                profile_path,
                headless=headless,
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.fill(selector, text, timeout=10000)
            browser.close()
            return f"Typed into '{selector}'"
    except ImportError:
        return "Error: playwright is not installed."
    except Exception as e:
        return f"Error typing text: {e}"


@tool
def get_page_text(url: str = "") -> str:
    """Get the text content of the current page or a URL."""
    try:
        from playwright.sync_api import sync_playwright

        headless = settings.BROWSER_HEADLESS
        profile_path = os.path.expanduser(settings.CHROME_PROFILE_PATH)

        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                profile_path,
                headless=headless,
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            if url:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            text = page.inner_text("body")[:10000]
            browser.close()
            return text
    except ImportError:
        return "Error: playwright is not installed."
    except Exception as e:
        return f"Error getting page text: {e}"


def get_browser_tools() -> list:
    """Return all browser tools."""
    return [navigate_to_url, take_screenshot, click_element, type_text, get_page_text]
